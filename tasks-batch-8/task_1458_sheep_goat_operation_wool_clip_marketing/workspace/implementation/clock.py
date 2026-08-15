"""The logical clock. Starts at exactly 2026-08-01T00:00:00Z; never wall-clock."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"current": _DEFAULT}


def now():
    return _state["current"]


def set_to(dt):
    _state["current"] = dt
    return _state["current"]
