"""Numeric + temporal helpers.

All money / score arithmetic goes through decimal.Decimal with ROUND_HALF_UP,
per PRD 2.4 ("half-up at every rounding point ... never binary floating point").
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from datetime import datetime, timedelta, timezone

ZERO = Decimal(0)


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def n2(value):
    return float(rhu(value, 2))


def n4(value):
    return float(rhu(value, 4))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def div(a, b):
    return D(a) / D(b)


def clamp01(value):
    v = D(value)
    if v < 0:
        return ZERO
    if v > 1:
        return Decimal(1)
    return v


# ---------------------------------------------------------------- timestamps

def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant into a naive UTC datetime, or raise ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def minute_of_day(dt):
    """Minute-of-day of a UTC instant (seconds discarded)."""
    return dt.hour * 60 + dt.minute


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def start_of_day(dt):
    return datetime(dt.year, dt.month, dt.day)


def minutes_between_floor(later, earlier):
    """Whole minutes elapsed, remaining seconds discarded."""
    delta = later - earlier
    return int(delta.total_seconds() // 60)
