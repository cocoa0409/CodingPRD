"""Parsing, date arithmetic, and decimal helpers.

Money is integer cents; rounding is always round-half-up via Decimal.
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT_RE = re.compile(r"^-?\d+$")


def parse_date(s):
    """Parse an ISO yyyy-mm-dd date string; None when malformed."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_datetime(s):
    """Parse an ISO 8601 datetime (Z or numeric offset); None when malformed."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_int_string(s):
    return isinstance(s, str) and bool(_INT_RE.match(s))


def is_weekday(d):
    return d.weekday() < 5  # Mon=0 .. Fri=4


def weekday_count(start, end):
    """Count of Mon-Fri dates inside the inclusive [start, end] range."""
    n = 0
    d = start
    while d <= end:
        if is_weekday(d):
            n += 1
        d += timedelta(days=1)
    return n


def is_next_workday(prev, d):
    """d is the next district workday after prev: consecutive days, or a
    Friday -> Monday weekend gap (weekend gaps never break a streak)."""
    delta = (d - prev).days
    if delta == 1:
        return True
    if delta == 3 and prev.weekday() == 4:
        return True
    return False


def ranges_overlap(a_start, a_end, b_start, b_end):
    """Closed date-interval intersection; adjacent ranges do not overlap."""
    return a_start <= b_end and b_start <= a_end


def rhu(dec):
    """Round half up to integer cents."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(v):
    """Exact Decimal from a JSON number."""
    return Decimal(str(v))


def round4(dec_value):
    """Round half up to 4 decimal places, returned as float."""
    return float(dec_value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def midnight_utc(d):
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def iso_week_bounds(d):
    """Monday and Sunday (ISO week) containing date d."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)
