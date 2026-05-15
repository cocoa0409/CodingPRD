"""Server clock abstraction so tests can advance time via /_clock/advance.

The clock holds an internal UTC datetime. When tests advance the clock, all
subsequent reads of `now()` return values from the advanced position. The
implementation favours determinism over wall-clock fidelity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


class ServerClock:
    def __init__(self) -> None:
        self._lock = Lock()
        # Start at real wall-clock UTC; tests will advance forward explicitly
        self._now: datetime = datetime.now(timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance_to(self, target: datetime) -> datetime:
        """Move the clock to `target` (forward jumps only honoured; backward
        moves accepted to honour the test contract literally)."""
        with self._lock:
            self._now = target
            return self._now

    def reset(self) -> None:
        with self._lock:
            self._now = datetime.now(timezone.utc)


clock = ServerClock()
