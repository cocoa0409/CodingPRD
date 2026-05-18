"""In-memory data store and logical clock."""

import threading
from datetime import datetime, timezone


def _truncate_ms(dt: datetime) -> datetime:
    """Truncate to millisecond precision so that serialize/parse
    round-trips are lossless (PRD §2.2 specifies milliseconds with the
    trailing 'Z' format)."""
    micro = (dt.microsecond // 1000) * 1000
    return dt.replace(microsecond=micro)


class Clock:
    """Monotonic logical clock that advances only forward."""

    def __init__(self):
        self._now = _truncate_ms(datetime.now(timezone.utc))
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance_to(self, target: datetime) -> datetime:
        with self._lock:
            target = _truncate_ms(target)
            if target > self._now:
                self._now = target
            return self._now


class DataStore:
    """Single-process in-memory data store with a global write lock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # Entity tables — id -> dict
        self.owners = {}
        self.hearing_officers = {}
        self.properties = {}
        self.assessments = {}
        self.exemption_applications = {}
        self.appeals = {}
        self.hearings = {}
        self.tax_bills = {}
        self.deferral_plans = {}
        self.payments = {}

    # Convenience for tests / sweeps
    def all(self, table_name: str):
        return getattr(self, table_name)


# Singleton instance for the module-level API
store = DataStore()
