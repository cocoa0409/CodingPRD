"""Server clock.

The server keeps a notion of "current UTC". By default it tracks the wall
clock, but a Manager may pin it to a fixed instant via
POST /_clock/set_current_utc (PRD §3.9). Time-gated transitions (no-show
grace, late-cancel cutoff, notify TTL, waitlist/hold expiry) read this clock.
"""
from datetime import datetime, timezone

_pinned = None  # datetime (UTC, tz-aware) or None when tracking wall clock


def now():
    """Return the current UTC instant the server believes it is."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def set_now(dt):
    """Pin the server clock to a fixed UTC instant."""
    global _pinned
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _pinned = dt.astimezone(timezone.utc)
    return _pinned


def reset():
    """Reset to wall-clock tracking (used only at boot)."""
    global _pinned
    _pinned = None
