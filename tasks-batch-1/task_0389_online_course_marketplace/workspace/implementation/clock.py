"""Controllable logical clock (PRD §2.8).

The system reads "now" from this clock rather than wall time. An admin-only
endpoint sets the current UTC instant; all time-sensitive rules evaluate against
it. The clock is process-global mutable state, reset to wall-clock on boot.
"""
from datetime import datetime, timezone

# When _override is None, the clock follows wall-clock time. Once set via the
# clock endpoint, it returns the fixed instant.
_override = None  # type: datetime | None


def now():
    """Return the current logical UTC instant as a timezone-aware datetime."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_now(dt):
    global _override
    _override = dt


def reset():
    global _override
    _override = None
