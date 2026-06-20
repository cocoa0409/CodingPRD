"""ISO 8601 datetime parsing for unit-assignment overlap math."""

from datetime import datetime, timedelta, timezone

from errors import ERR_INVALID_REQUEST, err


def parse_iso(value, field_name):
    """Parse an ISO 8601 UTC datetime string into an aware datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST on
    malformed input.
    """
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field_name} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
