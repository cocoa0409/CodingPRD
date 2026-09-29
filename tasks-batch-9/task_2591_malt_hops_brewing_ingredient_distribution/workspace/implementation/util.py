"""Numeric and datetime helpers.

All money and poundage arithmetic goes through ``decimal.Decimal``.  Rounding is
always ROUND_HALF_UP (never Python's banker's ``round``).  Floor is used in
exactly the three places the PRD names: the allocatable harvest pool, the
carry-forward cap and cold-chain interval / cumulative excursion minutes.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

ZERO = Decimal("0")


def D(value):
    """Coerce anything numeric-ish into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """round_half_up(value, places) -> Decimal."""
    q = Decimal(1).scaleb(-int(places))
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """round_half_up to whole units, returned as a Python int (cents)."""
    return int(rhu(value, 0))


def floor_int(value):
    """Truncate toward negative infinity, returned as a Python int."""
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def dec_floor(value, places=0):
    q = Decimal(1).scaleb(-int(places))
    return D(value).quantize(q, rounding=ROUND_FLOOR)


def num(value):
    """JSON-friendly rendering of a Decimal: int when integral, else float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    d = D(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def parse_iso(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO-8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def whole_days_between(start, end):
    """Whole (floored) days from start forward to end; may be negative."""
    delta = end - start
    return floor_int(D(delta.total_seconds()) / D(86400))


def whole_minutes_between(start, end):
    delta = end - start
    return floor_int(D(delta.total_seconds()) / D(60))


def days(n):
    return timedelta(days=int(n))
