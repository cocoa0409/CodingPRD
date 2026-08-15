"""Time parsing/formatting and pinned rounding helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction


def parse_dt(s):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_date(s):
    """Strict YYYY-MM-DD parse; returns datetime.date."""
    if not isinstance(s, str):
        raise ValueError("date must be a string")
    parts = s.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError("date must be YYYY-MM-DD")
    if not all(p.isdigit() for p in parts):
        raise ValueError("date must be YYYY-MM-DD")
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def days_between(d1, d2):
    """(d1 - d2) in whole days; accepts dates or datetimes (date part used)."""
    a = d1.date() if isinstance(d1, datetime) else d1
    b = d2.date() if isinstance(d2, datetime) else d2
    return (a - b).days


def round_half_up_decimal(value, places="1"):
    """Round half-up (ties away from zero) to the given Decimal quantum."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    elif not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def rate_2dp(numerator, denominator):
    """round_half_up(100 * numerator / denominator, 2); None on zero denominator."""
    if denominator == 0:
        return None
    d = (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(d)


def shift_interval(shift):
    return {"AM": (6, 12), "PM": (12, 18), "FULL": (6, 18)}[shift]


def shifts_overlap(a, b):
    s1, e1 = shift_interval(a)
    s2, e2 = shift_interval(b)
    return s1 < e2 and s2 < e1
