"""Numeric, temporal and identifier helpers.

All monetary arithmetic is exact: integers and ``fractions.Fraction`` only.
No float ever participates in a money or ratio computation.
"""
import math
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

UTC = timezone.utc


# --------------------------------------------------------------------------
# exact arithmetic
# --------------------------------------------------------------------------
def to_fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not numeric here")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    if isinstance(value, str):
        return Fraction(Decimal(value))
    raise TypeError("not numeric: %r" % (value,))


F = to_fraction


def round_half_up(value):
    """round_half_up(x) = floor(x + 1/2) for x >= 0, -floor(-x + 1/2) for x < 0."""
    x = to_fraction(value)
    if x >= 0:
        return int(math.floor(x + Fraction(1, 2)))
    return -int(math.floor(-x + Fraction(1, 2)))


def floor_div(value):
    """Mathematical floor of an exact rational."""
    return int(math.floor(to_fraction(value)))


def ceil_div(a, b):
    """Integer ceiling division: ceil_div(a, b) = -((-a) // b)."""
    return -((-a) // b)


def ratio4(value):
    """A reported ratio: exactly four decimal places, round_half_up."""
    n = round_half_up(to_fraction(value) * 10000)
    return Decimal(n).scaleb(-4)


def frac4(value):
    """The same 4-decimal quantisation, kept exact for downstream arithmetic."""
    return Fraction(round_half_up(to_fraction(value) * 10000), 10000)


def fractional_part(x):
    x = to_fraction(x)
    return x - Fraction(math.floor(x))


# --------------------------------------------------------------------------
# time
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = _DT_RE.match(s)
    if not m:
        return None
    year, month, day, hh, mm, ss, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        d = datetime(
            int(year), int(month), int(day),
            int(hh or 0), int(mm or 0), int(ss or 0), micro, tzinfo=UTC,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        d = d - sign * delta
    return d


def fmt_dt(d):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if d is None:
        return None
    if d.tzinfo is not None:
        d = d.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000,
    )


def as_date(d):
    return date(d.year, d.month, d.day)


def end_of_day(day):
    return datetime(day.year, day.month, day.day, 23, 59, 59, 999000, tzinfo=UTC)


def start_of_day(day):
    return datetime(day.year, day.month, day.day, 0, 0, 0, 0, tzinfo=UTC)


def add_days(d, n):
    return d + timedelta(days=n)


def deadline_after_days(instant, days):
    """The calendar day ``days`` after ``instant``'s date, snapped to 23:59:59.999Z."""
    return end_of_day(as_date(instant) + timedelta(days=days))


def whole_days_between(a, b):
    """Whole-day count of (b - a); truncated toward negative infinity."""
    return int(math.floor((b - a).total_seconds() / 86400.0))


def days_inclusive(d1, d2):
    """Whole days from date d1 through date d2 counting both endpoints."""
    return (d2 - d1).days + 1


# --------------------------------------------------------------------------
# identifiers
# --------------------------------------------------------------------------
_ALPHABET = string.ascii_uppercase + string.digits


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))
