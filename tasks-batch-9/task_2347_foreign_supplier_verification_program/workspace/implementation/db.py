"""In-memory data store and the logical compliance clock.

The store is EMPTY on every boot. Nothing is seeded, preloaded or hardcoded.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD section 2.4 — on startup the logical clock reads exactly this instant and
# must never fall back to the host's wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = {
    "importer": "importers",
    "qi": "qis",
    "supplier": "suppliers",
    "food": "foods",
    "pair": "pairs",
    "analysis": "analyses",
    "hazard": "hazards",
    "activity": "activities",
    "record": "records",
    "action": "actions",
    "entry": "entries",
}


def wall_now():
    return datetime.now(timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.importers = {}
        self.qis = {}
        self.suppliers = {}
        self.foods = {}
        self.pairs = {}
        self.analyses = {}
        self.hazards = {}
        self.activities = {}
        self.records = {}
        self.actions = {}
        self.entries = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        self.touched = set()

    def collection(self, kind):
        return getattr(self, COLLECTIONS[kind])

    def new_row(self, kind, versioned=True):
        ts = wall_now()
        row = {
            "id": str(uuid.uuid4()),
            "_kind": kind,
            "_seq": next(self._seq),
            "created_at": ts,
        }
        if versioned:
            row["updated_at"] = ts
            row["version"] = 1
        return row

    def insert(self, row):
        self.collection(row["_kind"])[row["id"]] = row
        self.touched.add((row["_kind"], row["id"]))
        return row

    def touch(self, row):
        """Record a mutation: bump version and refresh updated_at."""
        if "version" in row:
            row["version"] = row["version"] + 1
            row["updated_at"] = wall_now()
        self.touched.add((row["_kind"], row["id"]))
        return row


store = Store()
