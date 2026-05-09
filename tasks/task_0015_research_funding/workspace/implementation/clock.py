"""System clock — supports test-driven advancement."""

import time
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._offset = 0.0  # seconds added to wall clock

    def now_epoch(self) -> float:
        return time.time() + self._offset

    def now_iso(self) -> str:
        ts = self.now_epoch()
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # ISO 8601 UTC with three fractional digits
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}Z"

    def set_to(self, target_epoch: float) -> None:
        wall = time.time()
        self._offset = target_epoch - wall

    def current_year(self) -> str:
        ts = self.now_epoch()
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y")


clock = Clock()
