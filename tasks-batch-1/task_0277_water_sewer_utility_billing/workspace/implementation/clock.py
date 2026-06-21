"""Server logical clock.

PRD §3.11: the system exposes a test-driving capability that sets the server's
current UTC clock. Shutoff due-dates and moratorium coverage both turn on this
clock. When unset, the clock falls back to real wall-clock UTC.
"""
from datetime import datetime, timezone

_current_utc = None  # datetime (aware UTC) or None -> use real now


def reset():
    global _current_utc
    _current_utc = None


def set_current_utc(dt):
    """dt: timezone-aware UTC datetime."""
    global _current_utc
    _current_utc = dt


def now():
    """Current server UTC instant (aware datetime)."""
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)
