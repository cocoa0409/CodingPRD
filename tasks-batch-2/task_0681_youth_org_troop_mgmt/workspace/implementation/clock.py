"""Server-managed logical clock (PRD §2.10).

On startup the clock reads exactly 2026-04-01T00:00:00Z, and before any operator
sets it the clock returns this default and never falls back to real wall-clock
time. A CouncilRegistrar may advance the clock by supplying a target instant.
"""
from datetime import datetime, timezone

# PRD §2.10: "On startup the clock reads exactly 2026-04-01T00:00:00Z".
DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
