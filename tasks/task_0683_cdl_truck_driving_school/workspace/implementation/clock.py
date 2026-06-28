"""Logical server clock (PRD §3.8).

At startup the clock is set to 2026-04-01T00:00:00Z, and it never falls back
to wall-clock time. A SchoolAdmin may move the clock to a supplied UTC instant.
"""
from datetime import datetime, timezone

_DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
