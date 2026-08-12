"""In-memory data store and logical clock. Starts empty on every boot."""

from datetime import datetime, timedelta, timezone

COLLECTIONS = [
    "role_profiles", "employees", "new_hires", "cases", "tasks",
    "clearances", "orders", "items", "sessions", "checkins",
    "trainings", "cycles", "handoffs", "surveys",
]

store = {c: {} for c in COLLECTIONS}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


class _Clock:
    """Logical clock: starts at exactly 2026-05-01T00:00:00Z, never wall-clock."""

    def __init__(self):
        self.current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


clock = _Clock()

# Monotonic stamp source so entity created_at/updated_at values are unique
# and non-decreasing even when the logical clock is frozen.
_last_stamp = [None]


def take_stamp():
    """Return a timestamp >= clock, strictly greater than the last issued one."""
    t = clock.current
    if _last_stamp[0] is not None and t <= _last_stamp[0]:
        t = _last_stamp[0] + timedelta(milliseconds=1)
    _last_stamp[0] = t
    return t
