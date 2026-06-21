"""Server logical clock. Defaults to real wall-clock UTC until set via /_clock/set_current_utc."""
from datetime import datetime, timezone

_override = None  # datetime (aware, UTC) or None


def set_clock(dt):
    """Set the logical clock to a specific instant (aware datetime in UTC)."""
    global _override
    _override = dt


def now():
    """Return current logical clock as an aware UTC datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def reset():
    global _override
    _override = None
