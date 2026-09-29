"""In-memory data store and the logical clock (PRD §2.4, §2.6).

The store is empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "projects",
    "planning_studies",
    "alternatives",
    "routes",
    "route_segments",
    "public_comments",
    "applications",
    "hearing_sessions",
    "interventions",
    "certificates",
    "certificate_conditions",
    "landowners",
    "easement_tracts",
    "construction_activities",
    "nonconformances",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self._clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    # ---- logical clock -------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, instant):
        self._clock = instant

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields):
    """Create a row with the four common properties (§2.4)."""
    now = store.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(fields)
    collection[row["id"]] = row
    return row


def touch(row):
    """Record a mutation: bump version by exactly 1, refresh updated_at."""
    row["version"] = row["version"] + 1
    row["updated_at"] = store.now()
    return row


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
