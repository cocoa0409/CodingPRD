"""In-memory data store.

Storage is process-local Python dictionaries keyed by id.  Nothing is seeded,
preloaded or hardcoded: the store starts completely empty on every boot and all
state is created by clients through the declared endpoints.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# PRD §2.4 — before any client sets it the logical clock reads exactly this.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "flock_programs",
    "incubation_profiles",
    "incubation_units",
    "breeder_flocks",
    "egg_lots",
    "setter_loads",
    "setter_load_items",
    "environment_readings",
    "hatcher_loads",
    "chick_batches",
    "grower_farms",
    "placement_orders",
    "delivery_assignments",
    "lab_tests",
    "corrective_actions",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)
        for name in TABLES:
            setattr(self, name, {})

    # -- identity / audit helpers -----------------------------------------
    def next_seq(self):
        return next(self._seq)

    def new_record(self, **fields):
        rec = {
            "id": str(uuid.uuid4()),
            "created_at": self.clock,
            "updated_at": self.clock,
            "version": 1,
            "_seq": self.next_seq(),
        }
        rec.update(fields)
        return rec

    def touch(self, rec):
        """PRD §2.5 — every mutated record gets its own updated_at + version bump."""
        rec["updated_at"] = self.clock
        rec["version"] = rec["version"] + 1
        return rec

    def sorted_rows(self, table):
        rows = list(getattr(self, table).values())
        rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
        return rows


store = Store()
