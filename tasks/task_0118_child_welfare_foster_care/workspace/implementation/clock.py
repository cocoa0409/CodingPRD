"""Logical system clock.

The service maintains a logical UTC clock that an Admin sets explicitly via
POST /_clock/set. Every "current clock"/"now"/elapsed-time computation in the
service reads this logical clock, never the wall clock. When the clock has not
been set, it falls back to the real wall clock so timestamps are still valid.

All state is in-memory only; a fresh process boot resets the logical clock to
unset (wall-clock fallback). No persistence.
"""
from datetime import datetime, timezone

# None until an Admin sets it; module-level in-memory state only.
_logical_now = None


def set_clock(dt):
    """Fix the logical UTC clock to the given timezone-aware datetime."""
    global _logical_now
    _logical_now = dt


def now():
    """Return the current logical clock as a timezone-aware UTC datetime."""
    if _logical_now is not None:
        return _logical_now
    return datetime.now(timezone.utc)


def reset():
    """Reset the logical clock to unset (wall-clock fallback). For test isolation."""
    global _logical_now
    _logical_now = None


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # milliseconds = three fractional digits
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
