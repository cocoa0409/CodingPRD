"""Datetime, decimal and misc helpers.

Every date/expiry/window rule in this service reads the server's logical clock
(see db.py); this module only holds format/arithmetic primitives.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional-second digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime, or None if unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def day_start(dt):
    """UTC midnight of the calendar day containing dt."""
    dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def date_key(dt):
    """UTC calendar date of dt as a (y, m, d) tuple."""
    dt = dt.astimezone(timezone.utc)
    return (dt.year, dt.month, dt.day)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_years(dt, years):
    """Advance dt by whole calendar years, clamping 29 Feb to 28 Feb."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, month=2, day=28)


def dec(value):
    """Exact Decimal from an int/float/str/Decimal without binary artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole number, returned as an int."""
    return int(rhu(value, 0))


def num_out(value):
    """Render a Decimal for JSON as a float; ints stay ints."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
