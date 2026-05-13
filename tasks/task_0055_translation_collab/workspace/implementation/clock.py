"""Platform clock that can be advanced via /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class Clock:
    def __init__(self) -> None:
        self._offset_seconds: int = 0

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self._offset_seconds)

    def advance(self, seconds: int) -> datetime:
        if not isinstance(seconds, int) or isinstance(seconds, bool):
            raise ValueError("seconds must be a positive integer")
        if seconds <= 0:
            raise ValueError("seconds must be a positive integer")
        self._offset_seconds += seconds
        return self.now()


clock = Clock()
