"""Server-controlled logical clock (PRD §3.8).

The test harness drives time through POST /_clock/set_current_utc. Until the
clock is explicitly set, "now" tracks real wall-clock UTC so that ordinary
created_at/updated_at timestamps remain monotonic on a fresh boot.
"""
from datetime import datetime, timezone

# When None, the clock follows real wall-clock UTC. When set, it is pinned to a
# fixed instant supplied by the test harness.
_pinned = None


def set_now(dt):
    """Pin the server clock to a fixed timezone-aware UTC datetime."""
    global _pinned
    _pinned = dt.astimezone(timezone.utc)


def now():
    """Return the current server time as a timezone-aware UTC datetime."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def reset():
    global _pinned
    _pinned = None
