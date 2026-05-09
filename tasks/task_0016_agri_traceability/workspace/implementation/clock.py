"""System clock with test-driven advancement.

Supports POST /_clock/advance which fast-forwards "now" so withdrawal-period
checks and recall-scope snapshots can be exercised deterministically.
"""

import time
from datetime import datetime, timezone


class Clock:
    def __init__(self) -> None:
        self._offset = 0.0  # seconds added to wall clock

    def now_epoch(self) -> float:
        return time.time() + self._offset

    def now_dt(self) -> datetime:
        return datetime.fromtimestamp(self.now_epoch(), tz=timezone.utc)

    def now_iso(self) -> str:
        dt = self.now_dt()
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"

    def set_to(self, target_epoch: float) -> None:
        wall = time.time()
        # Only allow forward movement.
        new_offset = target_epoch - wall
        if new_offset > self._offset:
            self._offset = new_offset


clock = Clock()
