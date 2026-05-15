"""Logical clock — advanced by POST /_clock/advance for time-gated tests."""

import threading
from datetime import datetime, timezone


_lock = threading.RLock()
_offset_seconds = 0.0   # added to real wall clock to derive logical now()
_pinned_now = None      # if set, return this exact instant (overrides offset)


def now():
    """Return the current logical UTC datetime."""
    with _lock:
        if _pinned_now is not None:
            return _pinned_now
        real = datetime.now(timezone.utc)
        if _offset_seconds:
            from datetime import timedelta
            return real + timedelta(seconds=_offset_seconds)
        return real


def advance_to(target: datetime):
    """Pin the logical clock to a specific instant (test capability)."""
    global _pinned_now
    with _lock:
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        else:
            target = target.astimezone(timezone.utc)
        _pinned_now = target


def reset():
    """For tests only — revert to real clock."""
    global _pinned_now, _offset_seconds
    with _lock:
        _pinned_now = None
        _offset_seconds = 0.0


def iso(dt: datetime = None) -> str:
    """Format dt (or now()) as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp; return tz-aware UTC datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    # Accept trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
