"""Server clock — can be advanced in test harness."""

from datetime import datetime, timezone
from threading import Lock


class ServerClock:
    def __init__(self):
        # PRD §2.10 specifies that the clock can be advanced but never
        # rewound. PRD does not pin the initial-clock state. We anchor the
        # clock at a deterministic instant in the distant past so any
        # subsequent advance_to call from the test harness moves it forward
        # rather than silently failing with ERR_CLOCK_REGRESS against a
        # wall-clock start.
        self._now = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self._lock = Lock()

    def now(self):
        with self._lock:
            return self._now

    def advance_to(self, target: datetime):
        """Returns True if advanced, False if target <= current (regress)."""
        with self._lock:
            if target <= self._now:
                return False
            self._now = target
            return True

    def reset(self):
        """Test-only helper: reset clock to its initial anchor."""
        with self._lock:
            self._now = datetime(2000, 1, 1, tzinfo=timezone.utc)

    def now_iso(self):
        n = self.now()
        s = n.strftime("%Y-%m-%dT%H:%M:%S")
        millis = f"{n.microsecond // 1000:03d}"
        return f"{s}.{millis}Z"


clock = ServerClock()


def now_iso() -> str:
    return clock.now_iso()


def now_dt() -> datetime:
    return clock.now()
