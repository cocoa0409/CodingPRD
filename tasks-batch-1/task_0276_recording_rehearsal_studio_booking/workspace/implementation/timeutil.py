"""Datetime parsing/formatting helpers. All instants are UTC-aware."""
from datetime import datetime, timezone, timedelta

from errors import err


def parse_iso(value, error_id="ERR_INVALID_REQUEST"):
    """Parse an ISO 8601 string into a UTC-aware datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as
    UTC. Raises ApiError(error_id) on a malformed value.
    """
    if not isinstance(value, str):
        raise err(error_id, "invalid timestamp")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(error_id, "invalid timestamp: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def seconds_between(later, earlier):
    return (later - earlier).total_seconds()


def whole_minutes_between(later, earlier):
    """Whole number of minutes between two instants (truncated toward zero)."""
    secs = (later - earlier).total_seconds()
    return int(secs // 60)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
