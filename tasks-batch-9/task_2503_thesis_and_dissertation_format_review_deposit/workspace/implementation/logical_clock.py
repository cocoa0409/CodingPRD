"""The logical clock every temporal rule in the API reads (PRD section 2.4).

Before the first time it is set the clock reads exactly 2026-08-01T00:00:00Z and
it never falls back to real wall-clock time.
"""

from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant
        return self._now

    def reset(self):
        self._now = DEFAULT_NOW


clock = LogicalClock()
