"""Logical clock — an in-memory mutable instant that drives all time gates.

The clock starts at process boot time and is advanced via
POST /_clock/advance. All business rules call now() through this module
so tests can drive deterministic time.

The clock auto-ticks by 1 millisecond at the start of each non-clock
mutating request (see `tick_for_request`), so successive operations
receive a strictly-monotonic `created_at` / `registered_at` — PRD §3.4's
`registered_at`-ascending priority key uses this monotonicity to break
ties between siblings created in immediate succession without relying
on the random `Candidate.id` lexicographic fallback.
"""

from datetime import datetime, timedelta, timezone
import threading


class LogicalClock:
    def __init__(self):
        self._now = datetime.now(timezone.utc)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, instant: datetime) -> None:
        with self._lock:
            # Ensure UTC awareness.
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            else:
                instant = instant.astimezone(timezone.utc)
            self._now = instant

    def tick(self, delta: timedelta) -> None:
        with self._lock:
            self._now = self._now + delta


clock = LogicalClock()


def now():
    return clock.now()


def set_now(instant: datetime):
    clock.set(instant)


def tick_for_request():
    """Advance the clock by 1ms — called once at the start of each
    non-clock-control request so successive operations receive distinct
    instants for PRD §3.4 ordering.
    """
    clock.tick(timedelta(milliseconds=1))
