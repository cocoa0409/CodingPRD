"""Server clock abstraction.

Tests advance time via POST /scf/_clock/advance. All reads of `now()` reflect
the current logical clock; on first init we sit at the real wall-clock UTC.
"""
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
