"""Shared primitives: logical-clock friendly datetime handling and decimal math.

Every timestamp the service renders uses ISO 8601 UTC with exactly three
fractional-second digits (PRD 2.4).  Client-supplied instants are echoed back
verbatim, so each record keeps both the raw string and the parsed datetime.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, InvalidOperation

UTC = timezone.utc


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """Render an instant with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def dec(value):
    """Coerce an int/float/Decimal/str into a Decimal without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


TWO = Decimal("0.01")


def q2(value):
    """Round half-up to two decimal places (PRD 2.6)."""
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)


def floor_div_days(delta):
    """Whole days in a timedelta, discarding any partial day (floor)."""
    seconds = total_seconds(delta)
    return int((seconds / Decimal(86400)).to_integral_value(rounding=ROUND_FLOOR))


def total_seconds(delta):
    """Exact seconds of a timedelta as a Decimal."""
    return (
        Decimal(delta.days) * Decimal(86400)
        + Decimal(delta.seconds)
        + (Decimal(delta.microseconds) / Decimal(1000000))
    )


def ceil_hours(delta):
    """Elapsed hours rounded up to the next whole hour, floored at 0."""
    seconds = total_seconds(delta)
    if seconds < 0:
        seconds = Decimal(0)
    return int((seconds / Decimal(3600)).to_integral_value(rounding=ROUND_CEILING))


def add_days(instant, days):
    return instant + timedelta(days=int(days))


def add_minutes(instant, minutes):
    return instant + timedelta(minutes=int(minutes))
