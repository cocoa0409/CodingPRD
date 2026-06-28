"""Logical clock (PRD §2.5).

Server startup default is 2026-01-01T00:00:00Z. The logical clock never falls
back to wall-clock time. Every deadline / cooldown / cycle / consent /
minor-classification rule reads this clock.
"""
from datetime import datetime, timezone

# Server startup default (PRD §2.5 / scaffold /_clock/set_current_utc).
DEFAULT_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = DEFAULT_NOW

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
