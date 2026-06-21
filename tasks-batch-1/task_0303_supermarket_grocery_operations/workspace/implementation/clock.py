"""Logical clock: server-held UTC instant used for all window/expiry evaluation."""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        # Default current instant is real wall-clock now (UTC). Tests advance it
        # explicitly via POST /_clock/advance.
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = Clock()
