"""Logical clock (PRD §2.9).

On server startup the clock reads exactly 2026-04-01T00:00:00Z, and before any
clock-setting call it stays at that default and never falls back to real time.
A PlatformAdmin may advance or reset the clock to any absolute ISO 8601 UTC
instant.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


class Clock:
    def __init__(self):
        self._now = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


# Module-level singleton; wiped on every fresh boot because the module is
# re-imported in a brand-new process.
clock = Clock()
