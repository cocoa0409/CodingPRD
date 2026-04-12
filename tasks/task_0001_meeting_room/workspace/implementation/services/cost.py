from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta


def compute_cost_cents(room, start_time, end_time):
    """Compute booking cost by iterating minute-by-minute.

    start_time, end_time are datetime objects (UTC).
    Returns integer cents.
    """
    hourly_rate = Decimal(str(room["hourly_rate_cents"]))
    peak_multiplier = Decimal(str(room.get("peak_multiplier", 1.0)))
    peak_start_str = room.get("peak_hours_start")
    peak_end_str = room.get("peak_hours_end")

    base_rate_per_minute = hourly_rate / Decimal("60")

    total = Decimal("0")

    current = start_time
    one_minute = timedelta(minutes=1)

    while current < end_time:
        minute_hhmm = current.strftime("%H:%M")

        is_peak = False
        if peak_start_str and peak_end_str:
            if peak_start_str <= peak_end_str:
                is_peak = peak_start_str <= minute_hhmm < peak_end_str
            else:
                # overnight peak window
                is_peak = minute_hhmm >= peak_start_str or minute_hhmm < peak_end_str

        if is_peak:
            total += base_rate_per_minute * peak_multiplier
        else:
            total += base_rate_per_minute

        current += one_minute

    cost_cents = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cost_cents
