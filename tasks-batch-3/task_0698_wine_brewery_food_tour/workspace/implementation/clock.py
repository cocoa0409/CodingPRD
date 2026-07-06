"""The logical clock (PRD §2.5).

On server startup the logical clock reads exactly 2026-03-01T00:00:00Z and stays
at that value until it is explicitly moved; before any set call it never falls
back to wall-clock time. The clock is in-memory only and resets on every boot.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
