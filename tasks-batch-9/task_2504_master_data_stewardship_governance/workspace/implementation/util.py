"""Time and numeric helpers.

Every quantity in this system is carried to two decimal places and rounded half
up (PRD 2.7).  Lead times are whole integer days.  All server-written instants
are ISO 8601 UTC with exactly three fractional digits.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

CENT = Decimal("0.01")


def round2(value):
    """Round half up to two decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def dec(value):
    """Coerce a JSON number to an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num(value):
    """Serialise a 2dp quantity as a JSON number."""
    if value is None:
        return None
    return float(round2(value))


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "T" not in text and "t" not in text:
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


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_hours(dt, hours):
    return dt + timedelta(hours=int(hours))


def whole_days_between(start, end):
    """Number of whole days from start to end (floored, never negative)."""
    delta = end - start
    days = Decimal(delta.total_seconds()) / Decimal(86400)
    floored = int(days.to_integral_value(rounding=ROUND_FLOOR))
    return max(0, floored)


CLASSIFICATION_RANK = {"PUBLIC": 1, "INTERNAL": 2, "CONFIDENTIAL": 3, "RESTRICTED": 4}
