"""Server logical clock.

PRD 3.12: At startup the logical clock is fixed at exactly 2026-04-01T00:00:00Z;
before any clock-setting call it reads exactly this default and never falls back
to wall-clock time. An authorized ProjectManager or FinanceOfficer may set the
clock by supplying a target instant `to_iso8601`.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt

    def reset(self):
        self._now = DEFAULT_CLOCK


clock = LogicalClock()
