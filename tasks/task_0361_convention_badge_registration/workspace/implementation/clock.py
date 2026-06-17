"""Server logical clock.

A ConventionAdmin can pin the server's current UTC clock to a fixed instant
via POST /_clock/set (PRD §3.1). Until pinned, the clock follows real UTC time.
State is in-memory only and reset on every fresh boot.
"""
from datetime import datetime, timezone

# When None, the clock follows real wall-clock time. Otherwise it is pinned.
_pinned = None  # type: ignore


def set_clock(dt):
    """Pin the server clock to a timezone-aware UTC datetime."""
    global _pinned
    _pinned = dt


def now():
    """Return the current server clock as a timezone-aware UTC datetime."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)
