"""Test-driving logical clock (PRD 2.5). Startup default 2026-08-01T00:00:00Z;
never reads the wall clock for system-stamped instants."""

from datetime import datetime, timezone


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = LogicalClock()
