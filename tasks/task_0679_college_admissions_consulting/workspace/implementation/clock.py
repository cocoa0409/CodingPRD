"""Logical clock and datetime parsing helpers."""
from datetime import datetime, timezone

from db import store
from errors import err, ERR_INVALID_REQUEST


def now():
    """Current logical-clock instant as aware UTC datetime."""
    return store.clock


def set_clock(iso_str):
    dt = parse_datetime(iso_str)
    store.clock = dt


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Raises ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value")
    s = value.strip()
    # normalize trailing Z to +00:00 for fromisoformat
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Malformed datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
