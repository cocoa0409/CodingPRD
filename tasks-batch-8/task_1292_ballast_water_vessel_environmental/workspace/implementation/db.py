"""In-memory data store and logical clock.

Storage is process-local dicts keyed by id. Every server boot starts with a
completely empty store; nothing is seeded or preloaded. The logical clock
starts at 2026-08-01T00:00:00Z and is only ever moved by the
POST /_clock/set_current_utc endpoint — never by wall-clock time.
"""

import itertools
import threading
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.vessels = {}
        self.plans = {}
        self.voyages = {}
        self.ballast_events = {}
        self.determinations = {}
        self.reports = {}
        self.inspections = {}
        self.noncompliance = {}
        self.deficiencies = {}
        self.record_books = {}
        self.record_entries = {}
        self.emissions = {}
        self.drills = {}
        self.enforcement_cases = {}
        self._seq = itertools.count(1)
        self.clock = CLOCK_START
        self.lock = threading.RLock()

    def next_seq(self):
        return next(self._seq)


store = Store()


def now():
    """Current logical UTC time (never wall-clock)."""
    return store.clock
