import urllib.request
import urllib.parse
import json
from datetime import datetime

# ==========================================
# 텔레그램 설정
# ==========================================
TELEGRAM_TOKEN = "9154522261:AAGMLVAJcpkHguU4y5RNfngGNEzWejH6HXI"
TELEGRAM_CHAT_ID = "8316332813"

SYMBOL = "BTCUSDT"
TIMEFRAME = "1h"
MIN_FVG_GAP_PERCENT = 1.0


def send_telegram(message: str):
    """텔레그램 메시지 발송 함수"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[전송 실패] {e}")
        return False


def get_binance_candles():
    """바이낸스에서 1시간봉 캔들 데이터 수집"""
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={TIMEFRAME}&limit=100"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[시세 조회 실패] {e}")
        return []

    candles = []
    for c in raw:
        candles.append({
            "time": int(c[0]),
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "vol": float(c[5])
        })
    return candles


def run_hourly_check():
    """매시간 정각 1회 실행되는 분석 함수"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 클라우드 정각 분석 시작...")
    candles = get_binance_candles()
    if not candles or len(candles) < 10:
        print("캔들 데이터 부족")
        return

    detected_zones = []

    # 1. 1.0% 이상 FVG 탐색
    for i in range(2, len(candles) - 1):
        c_prev2 = candles[i-2]
        c_curr = candles[i-1]
        c_next = candles[i]

        if c_next["low"] > c_prev2["high"]:
            gap_bottom = c_prev2["high"]
            gap_top = c_next["low"]
            gap_pct = ((gap_top - gap_bottom) / gap_bottom) * 100.0
            if gap_pct >= MIN_FVG_GAP_PERCENT:
                detected_zones.append({
                    "id": f"FVG_BULL_{c_curr['time']}",
                    "type": "상승 FVG (대형 불균형)",
                    "direction": "BULL",
                    "top": gap_top,
                    "bottom": gap_bottom,
                    "ce": (gap_top + gap_bottom) / 2.0,
                    "gap_pct": gap_pct,
                    "invalidation_price": gap_bottom,
                    "created_time": c_curr["time"]
                })
        elif c_next["high"] < c_prev2["low"]:
            gap_top = c_prev2["low"]
            gap_bottom = c_next["high"]
            gap_pct = ((gap_top - gap_bottom) / gap_bottom) * 100.0
            if gap_pct >= MIN_FVG_GAP_PERCENT:
                detected_zones.append({
                    "id": f"FVG_BEAR_{c_curr['time']}",
                    "type": "하락 FVG (대형 불균형)",
                    "direction": "BEAR",
                    "top": gap_top,
                    "bottom": gap_bottom,
                    "ce": (gap_top + gap_bottom) / 2.0,
                    "gap_pct": gap_pct,
                    "invalidation_price": gap_top,
                    "created_time": c_curr["time"]
                })

    # 2. 타이트한 몸통 기준 OB 탐색
    for i in range(1, len(candles) - 1):
        c_origin = candles[i-1]
        c_break = candles[i]
        body_break = abs(c_break["close"] - c_break["open"])
        body_origin = abs(c_origin["close"] - c_origin["open"])

        origin_body_top = max(c_origin["open"], c_origin["close"])
        origin_body_bottom = min(c_origin["open"], c_origin["close"])

        if c_origin["close"] < c_origin["open"] and c_break["close"] > c_break["open"]:
            if body_break > body_origin * 1.3 and c_break["close"] > c_origin["high"]:
                detected_zones.append({
                    "id": f"OB_BULL_{c_origin['time']}",
                    "type": "상승 오더블록 (Bullish OB - 몸통)",
                    "direction": "BULL",
                    "top": origin_body_top,
                    "bottom": origin_body_bottom,
                    "ce": (origin_body_top + origin_body_bottom) / 2.0,
                    "gap_pct": 0,
                    "invalidation_price": c_origin["low"],
                    "created_time": c_origin["time"]
                })
        elif c_origin["close"] > c_origin["open"] and c_break["close"] < c_break["open"]:
            if body_break > body_origin * 1.3 and c_break["close"] < c_origin["low"]:
                detected_zones.append({
                    "id": f"OB_BEAR_{c_origin['time']}",
                    "type": "하락 오더블록 (Bearish OB - 몸통)",
                    "direction": "BEAR",
                    "top": origin_body_top,
                    "bottom": origin_body_bottom,
                    "ce": (origin_body_top + origin_body_bottom) / 2.0,
                    "gap_pct": 0,
                    "invalidation_price": c_origin["high"],
                    "created_time": c_origin["time"]
                })

    # 3. 최신 캔들(현재 진행 중 또는 직전 마감 캔들)이 구간에 진입했는지 확인
    latest_candle = candles[-1]
    prev_candle = candles[-2]
    c_high = max(latest_candle["high"], prev_candle["high"])
    c_low = min(latest_candle["low"], prev_candle["low"])
    current_price = latest_candle["close"]

    alert_sent = False
    for zone in detected_zones[-15:]:
        # 구간 생성 이후 도달 여부
        if latest_candle["time"] <= zone["created_time"]:
            continue

        # 진입 판정
        entered = (c_low <= zone["top"]) and (c_high >= zone["bottom"])
        if entered:
            direction_emoji = "🟢 [매수 / 롱 지지 타점]" if zone["direction"] == "BULL" else "🔴 [매도 / 숏 저항 타점]"
            create_dt = datetime.fromtimestamp(zone["created_time"] / 1000).strftime("%m월 %d일 %H시")
            gap_info = f"• <b>불균형 크기</b>: {zone['gap_pct']:.2f}%\n" if zone["gap_pct"] > 0 else ""

            msg = (
                f"☁️ <b>[정각 클라우드 점검] {zone['type']} 진입 감지!</b>\n\n"
                f"• <b>유형</b>: {zone['type']}\n"
                f"• <b>타점 방향</b>: {direction_emoji}\n"
                f"{gap_info}"
                f"• <b>진입 구간(몸통)</b>: ${zone['bottom']:,.2f} ~ ${zone['top']:,.2f}\n"
                f"• <b>중간값(CE 50%)</b>: ${zone['ce']:,.2f}\n"
                f"• <b>현재 가격</b>: ${current_price:,.2f}\n"
                f"• <b>무효화 기준</b>: ${zone['invalidation_price']:,.2f} 종가 이탈 시 손절\n"
                f"• <b>생성 시점</b>: {create_dt}\n\n"
                f"💡 <i>PC가 꺼져 있어도 정각마다 클라우드가 자동 감시 중입니다.</i>"
            )
            send_telegram(msg)
            print(f"[알림 발송 완료] {zone['type']}")
            alert_sent = True

    if not alert_sent:
        print("현재 진입 중인 구간 없음 (특이사항 없음)")


if __name__ == "__main__":
    run_hourly_check()
