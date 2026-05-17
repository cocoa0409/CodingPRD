"""Simulated clock used everywhere instead of real wall time.

The clock is initialized to a fixed start instant so reproducibility across
tests is preserved. It only advances when an operator hits POST /telemed/_clock/advance.
Reads and state-machine preconditions consult this clock.
"""
from datetime import datetime, timezone
from threading import RLock


class _SimulatedClock:
    def __init__(self) -> None:
        self._lock = RLock()
        # Default starting instant — tests will advance this forward as needed.
        self._now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, when: datetime) -> None:
        with self._lock:
            # Only advance forward; the spec is "advance the simulated clock."
            if when > self._now:
                self._now = when

    def reset(self) -> None:
        """Test-only: hard reset to the default starting instant."""
        with self._lock:
            self._now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


clock = _SimulatedClock()
