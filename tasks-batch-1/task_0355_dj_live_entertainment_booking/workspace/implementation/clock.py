"""Logical server clock.

The server keeps a logical UTC clock that test-driving endpoint
POST /_clock/set can override. All time comparisons (event-in-future checks,
lead-day computations, blackout overlaps) use this clock's value.

Default (when never set) is the real wall-clock UTC.
"""
from datetime import datetime, timezone

# When None, fall back to real wall-clock time.
_now_override = None


def reset():
    global _now_override
    _now_override = None


def set_now(dt):
    """dt is a timezone-aware datetime (UTC)."""
    global _now_override
    _now_override = dt


def now():
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)
