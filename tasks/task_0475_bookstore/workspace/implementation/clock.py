"""Logical clock. Starts at 2026-01-01T00:00:00Z and never falls back to wall time."""
from datetime import datetime, timezone

# Default startup clock instant per PRD §3.1
_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
