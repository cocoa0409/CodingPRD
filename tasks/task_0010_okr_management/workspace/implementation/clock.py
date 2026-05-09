"""Logical clock for ExternalEvent dedup window and stale-KR threshold."""

import datetime as _dt
from threading import RLock

_lock = RLock()
_offset_seconds = 0.0
_frozen_now = None  # if set, now() returns this; advanced via advance()


def _real_now():
    return _dt.datetime.now(_dt.timezone.utc)


def now():
    """Return the current logical UTC datetime (timezone-aware)."""
    with _lock:
        global _frozen_now
        if _frozen_now is None:
            _frozen_now = _real_now()
        return _frozen_now


def advance(seconds: float):
    with _lock:
        global _frozen_now
        if _frozen_now is None:
            _frozen_now = _real_now()
        _frozen_now = _frozen_now + _dt.timedelta(seconds=float(seconds))


def reset():
    """For test isolation if ever needed."""
    with _lock:
        global _frozen_now, _offset_seconds
        _frozen_now = None
        _offset_seconds = 0.0


def format_ts(dt: _dt.datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    else:
        dt = dt.astimezone(_dt.timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_ts(s: str) -> _dt.datetime:
    """Parse an ISO 8601 timestamp string. Accepts 'Z' suffix or offset."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt
