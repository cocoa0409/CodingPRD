from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = None  # None => use real wall clock

    def now(self):
        if self._now is not None:
            return self._now
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._now = dt


clock = Clock()
