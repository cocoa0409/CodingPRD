import threading
from datetime import datetime, timezone, timedelta


class LogicalClock:
    def __init__(self):
        self._offset = timedelta(0)
        self._lock = threading.Lock()

    def now(self):
        with self._lock:
            return datetime.now(timezone.utc) + self._offset

    def advance(self, seconds):
        with self._lock:
            self._offset += timedelta(seconds=seconds)
        return self.now()

    def format_timestamp(self, dt=None):
        if dt is None:
            dt = self.now()
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


logical_clock = LogicalClock()
