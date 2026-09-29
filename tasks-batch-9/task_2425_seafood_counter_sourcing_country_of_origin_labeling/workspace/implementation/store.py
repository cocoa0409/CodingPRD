"""In-memory data store and logical clock.

The store starts EMPTY on every boot.  No entity is ever seeded, preloaded or
hardcoded here; every record is created through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any request sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z and it never falls back to real wall-clock time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "counters",
    "suppliers",
    "species",
    "lots",
    "case_labels",
    "ad_items",
    "readings",
    "excursions",
    "samples",
    "simp_documents",
    "certifications",
    "shrink_events",
    "violations",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """The logical clock instant."""
    return db.clock
