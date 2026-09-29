"""In-memory data store.

The store is EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded.  Tests build every precondition through the declared API surface.
"""

import threading
from datetime import datetime, timezone

# PRD §2.6: at startup the logical clock reads exactly 2026-08-01T00:00:00Z and
# the server never falls back to real wall-clock time for date-dependent rules.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

lock = threading.RLock()


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.officials = {}
        self.students = {}
        self.terms = {}
        self.programs = {}
        self.catalog_versions = {}
        self.agreements = {}
        self.certifications = {}
        self.tuition_reports = {}
        self.awards = {}
        self.change_reports = {}
        self.debts = {}
        self.charges = {}
        self.audit_entries = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
