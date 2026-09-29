"""Numeric, date and time helpers.

All money and percentage arithmetic goes through Decimal with ROUND_HALF_UP
(PRD 2.4 / SCAFFOLD calculations precision).  Python's built-in round() is
never used.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")


def D(value):
    """Coerce anything numeric-ish into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    """round_half_up(value, places) as pinned by every calculation block."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q2(value):
    return round_half_up(value, 2)


def cents(value):
    """Money results are whole cents."""
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------- timestamps

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2/2.4)."""
    if dt is None:
        return None
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (u.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if value is None or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date.  Returns date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def as_date(value):
    """Normalise a date / datetime / ISO string to a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    d = parse_date(value)
    if d is not None:
        return d
    dt = parse_dt(value)
    return dt.date() if dt else None


def days_between(a, b):
    """Whole days from a to b, floored over UTC calendar dates (PRD 2.4).

    May be negative; callers clamp with max(0, ...) where the spec says so.
    """
    da, db = as_date(a), as_date(b)
    if da is None or db is None:
        return 0
    return (db - da).days


def add_days(value, n):
    d = as_date(value)
    if d is None:
        return None
    return d + timedelta(days=n)


def add_days_dt(dt, n):
    """Advance an instant by whole days, preserving its time of day."""
    if dt is None:
        return None
    return dt + timedelta(days=n)


def fmt_date(value):
    d = as_date(value)
    return d.isoformat() if d else None
