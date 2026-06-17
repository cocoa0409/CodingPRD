"""Datetime helpers. All times are UTC and serialized as ISO 8601 with three
fractional digits per PRD §2.4 / §2.10."""
from datetime import datetime, timezone

from errors import err


def iso_now(dt):
    """Serialize a tz-aware UTC datetime to ISO 8601 with millisecond precision
    and a trailing 'Z' (PRD §2.4: ISO 8601 UTC, three fractional digits)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds (three digits)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive timestamps are treated
    as UTC. Raises ERR_INVALID_REQUEST on malformed input.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "Invalid datetime value.")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def minute_of_day(dt):
    """Minutes since UTC midnight for a tz-aware datetime (§3.6)."""
    dt = dt.astimezone(timezone.utc)
    return dt.hour * 60 + dt.minute


def same_utc_date(a, b):
    a = a.astimezone(timezone.utc)
    b = b.astimezone(timezone.utc)
    return (a.year, a.month, a.day) == (b.year, b.month, b.day)
