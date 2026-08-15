"""Logical clock. Starts at exactly 2026-05-01T00:00:00Z. Never wall-clock."""
from datetime import datetime, timezone

from errors import raise_error

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


def parse_iso8601(value, field="timestamp"):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be an ISO8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise_error("ERR_INVALID_REQUEST", f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    """Serialize aware datetime to ISO8601 UTC with Z suffix (second precision)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
