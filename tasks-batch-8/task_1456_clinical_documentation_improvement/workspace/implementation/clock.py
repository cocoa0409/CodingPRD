"""Logical clock. Startup default is exactly 2026-08-01T00:00:00Z (period 0);
each day is one period. Per-program period indexes advance independently via
/api/cdi-programs/{id}/clock/advance; this global clock only anchors the
period mapping and the test-driving set_current_utc endpoint."""
from datetime import datetime, timedelta, timezone

from errors import raise_error

_ANCHOR = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _ANCHOR
_last_emitted = None


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


def period_index():
    """Whole days elapsed since the period-0 anchor."""
    delta = _current - _ANCHOR
    seconds = delta.total_seconds()
    if seconds >= 0:
        return int(seconds // 86400)
    # Floor towards negative infinity for pre-anchor times.
    return - int((-seconds + 86399) // 86400)


def parse_iso8601(value, field="to_iso8601"):
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
    """ISO8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def timestamp():
    """Strictly increasing ISO8601 ms timestamp anchored on the logical clock.

    Entity created_at/updated_at values derive from the logical clock so they
    track the test-driving epoch; a monotonic bump keeps ordering stable when
    many records share the same logical instant.
    """
    global _last_emitted
    base = _current
    if _last_emitted is not None and base <= _last_emitted:
        base = _last_emitted + timedelta(milliseconds=1)
    _last_emitted = base
    return to_iso(base)
