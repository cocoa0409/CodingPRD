"""Server clock abstraction so tests can advance time via /_clock/advance."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


class ServerClock:
    def __init__(self) -> None:
        self._lock = Lock()
        self._now: datetime = datetime.now(timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            self._now = target
            return self._now

    def reset(self) -> None:
        with self._lock:
            self._now = datetime.now(timezone.utc)


clock = ServerClock()
