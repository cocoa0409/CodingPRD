"""In-memory data store. Starts completely empty on every boot -- nothing is
seeded, preloaded or hardcoded. All rows are created through the API surface."""

import itertools
import threading
from datetime import datetime, timezone

# PRD 2.5: the logical clock begins at 2026-08-01T00:00:00Z on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

LOCK = threading.RLock()

# Collections that carry updated_at / version.
VERSIONED = (
    "facilities", "generators", "instruments", "profiles", "units",
    "manifests", "lines", "containers", "batches", "repair_orders", "findings",
)
# ProfileSample and InspectionEvent carry only id and created_at (PRD 2.4).
UNVERSIONED = ("samples", "inspections")

ALL_COLLECTIONS = VERSIONED + UNVERSIONED


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.current_utc = CLOCK_START
        self._seq = itertools.count(1)
        for name in ALL_COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)

    def collection(self, name):
        return getattr(self, name)


db = Store()


def now():
    """The current logical clock instant."""
    return db.current_utc


def insert(collection, row):
    row["_seq"] = db.next_seq()
    db.collection(collection)[row["id"]] = row
    return row


def rows(collection):
    return list(db.collection(collection).values())


def sorted_rows(collection, key=None):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    data = rows(collection)
    if key is None:
        key = lambda r: (r["created_at"], r["_seq"])
    return sorted(data, key=key)


def base_row(versioned=True):
    stamp = now()
    row = {"id": None, "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row
