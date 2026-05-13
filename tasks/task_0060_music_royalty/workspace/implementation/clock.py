"""Logical clock for the server. Advanceable by PlatformAdmin via test-driving endpoint."""

import threading
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._lock = threading.Lock()
        self._offset_seconds = 0.0  # offset added to real now() to produce logical now

    def now(self) -> datetime:
        # logical now = real now + offset
        real = datetime.now(timezone.utc)
        if self._offset_seconds:
            return real + _td(self._offset_seconds)
        return real

    def set_to(self, target: datetime) -> datetime:
        with self._lock:
            real = datetime.now(timezone.utc)
            delta = (target - real).total_seconds()
            # Only allow forward advances; if target < current logical, hold steady.
            new_offset = delta
            if new_offset > self._offset_seconds:
                self._offset_seconds = new_offset
            return self.now()


def _td(seconds: float):
    from datetime import timedelta
    return timedelta(seconds=seconds)


clock = Clock()
