"""Server clock. PRD §3.12: a PlatformAdmin may pin the clock for test-driving;
all subsequent reads of current time return the pinned instant."""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._pinned = None  # datetime (aware UTC) or None

    def reset(self):
        self._pinned = None

    def set_utc(self, dt):
        self._pinned = dt

    def now(self):
        if self._pinned is not None:
            return self._pinned
        return datetime.now(timezone.utc)


clock = Clock()
