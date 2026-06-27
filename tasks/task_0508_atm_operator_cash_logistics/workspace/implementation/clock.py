"""The logical clock (PRD §3.12).

Starts at 2026-01-01T00:00:00Z and only advances via POST /_clock/set_current_utc.
It NEVER falls back to wall-clock time. All window comparisons, forecast
windows, and month-rollover rules read this clock.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def reset(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt
