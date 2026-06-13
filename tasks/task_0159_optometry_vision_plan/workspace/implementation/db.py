"""In-memory data store.

Storage is purely in-memory: Python dicts keyed by id. Every collection starts
empty on boot. NOTHING is seeded, preloaded, or hardcoded at startup; all
entities are created by tests via declared endpoints.
"""
import uuid

import clock


class Store:
    """Holds all entity collections as id->record dicts."""

    def __init__(self):
        self.patients = {}
        self.providers = {}
        self.encounters = {}
        self.prescriptions = {}
        self.eligibilities = {}
        self.benefit_pools = {}
        self.lab_orders = {}
        self.claims = {}
        self.recall_reminders = {}
        # monotonically increasing sequence for stable creation ordering
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global store instance. Constructed fresh on every process boot.
db = Store()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def stamp_create(record, versioned=True):
    """Populate common system fields on creation.

    created_at, updated_at (ms ISO), version (starts at 1) when versioned.
    Always assigns a stable creation sequence used for ascending sort.
    """
    ts = clock.now_iso()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version by one (a mutation)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
