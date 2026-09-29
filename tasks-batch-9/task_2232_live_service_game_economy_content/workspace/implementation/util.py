"""Rounding discipline (PRD 2.6) and ISO-8601 handling (PRD 2.4)."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_ONE = Decimal(1)


def round_half_up(numerator, denominator):
    """Form the ratio first, then round half up (away from zero) to an integer."""
    if denominator == 0:
        raise ZeroDivisionError("round_half_up denominator is zero")
    return int((Decimal(int(numerator)) / Decimal(int(denominator))).quantize(_ONE, rounding=ROUND_HALF_UP))


def floor_div_seconds(delta_seconds, unit_seconds):
    """Whole units, truncated toward zero is *not* used here: durations are floored."""
    return int(delta_seconds // unit_seconds)


def whole_days(delta):
    return int(delta.total_seconds() // 86400)


def whole_hours(delta):
    return int(delta.total_seconds() // 3600)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utcnow():
    return datetime.now(timezone.utc)
