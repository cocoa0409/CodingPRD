"""Server logical clock.

PRD 2.4: On startup the clock reads exactly 2026-04-01T00:00:00Z; before any
clock-setting call it holds this default and never falls back to real wall-clock
time. A StudioAdmin moves the clock to a supplied UTC instant carried in
to_iso8601, and every downstream rule that mentions "now", "the current
instant", or "today" reads this clock.
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


clock = LogicalClock()
