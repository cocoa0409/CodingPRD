"""Logical clock — a server-side time source advanced by POST /_clock/advance."""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._now

    def advance_to(self, ts: datetime):
        if ts < self._now:
            # Refuse going backward; clamp to current
            return
        self._now = ts


clock = Clock()
