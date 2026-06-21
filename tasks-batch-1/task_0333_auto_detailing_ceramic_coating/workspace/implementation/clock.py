"""Server logical clock — test-drivable via POST /detailing/_clock/set_current_utc.

The clock holds the instant the server treats as "now". On boot it is the real
wall-clock UTC; setting it pins it to a supplied instant. All time-based
preconditions (check-in window, no-show timeout, cure completion, membership
renewal/lapse, guarantee window) read from here.
"""
from datetime import datetime, timezone

# When _override is set, now() returns it; otherwise real UTC.
_override = None


def reset():
    global _override
    _override = None


def set_now(dt):
    """Pin the logical clock to the supplied aware UTC datetime."""
    global _override
    _override = dt


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)
