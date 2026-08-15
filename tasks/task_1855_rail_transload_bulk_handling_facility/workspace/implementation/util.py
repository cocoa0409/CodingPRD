"""Parsing, datetime arithmetic, and decimal helpers.

Tonnages are decimal values carried to three decimal places; money is integer
cents; rounding is always round-half-up via Decimal.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_INT_RE = re.compile(r"^-?\d+$")


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
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def dec(v):
    """Exact Decimal from a JSON number (or a stored float)."""
    return Decimal(str(v))


def round3(v):
    """Round half-up to three decimal places, returned as float."""
    return float(dec(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def tons_add(a, b):
    """Exact 3-decimal tonnage addition/subtraction via Decimal."""
    return float((dec(a) + dec(b)).quantize(Decimal("0.001")))


def tons_sub(a, b):
    return float((dec(a) - dec(b)).quantize(Decimal("0.001")))


def rhu_cents(dec_value):
    """Round half-up to integer cents."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_minutes(delta):
    """Whole minutes of a timedelta, floored, clamped at zero."""
    return max(0, math.floor(delta.total_seconds() / 60))


def floor_days(delta):
    """Whole 24h blocks of a timedelta, floored, clamped at zero."""
    return max(0, math.floor(delta.total_seconds() / 86400))


def half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) interval intersection."""
    return a_start < b_end and b_start < a_end


def within_buffer(a_start, a_end, b_start, b_end, buffer_minutes):
    """True when the gap between two half-open windows is strictly less than
    the buffer (overlap or touch counts as gap 0)."""
    buf = timedelta(minutes=buffer_minutes)
    return a_start < b_end + buf and b_start < a_end + buf


def same_utc_month(a, b):
    return (a.year, a.month) == (b.year, b.month)
