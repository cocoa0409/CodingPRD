"""Logical clock: starts at 2026-08-01T00:00:00Z, advanced only via POST /_clock/set_current_utc."""
from datetime import datetime, timezone

_INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _INITIAL


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ApiError(ERR_INVALID_REQUEST, 400) on malformed input.
    """
    from errors import ApiError

    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "Invalid or missing datetime value", 400)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid ISO 8601 datetime: %r" % value, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))
