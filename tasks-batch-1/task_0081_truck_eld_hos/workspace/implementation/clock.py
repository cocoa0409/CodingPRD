"""Server clock: pinnable for deterministic time-gated tests (PRD §3.11)."""
from datetime import datetime, timezone

_pinned = None  # type: ignore  # datetime in UTC, or None to use wall clock


def now():
    """Current UTC datetime (pinned instant if set, else wall clock)."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def set_now(dt):
    global _pinned
    _pinned = dt


def reset():
    global _pinned
    _pinned = None
