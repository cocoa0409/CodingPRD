"""In-memory data store (PRD-bench: per-test-server isolation means every
boot starts from a completely fresh, empty store — nothing is seeded).

All entities live in plain dicts keyed by id. Each record carries the common
field set (id, created_at, updated_at, version) plus a private `_seq`
insertion counter used to break created_at ties deterministically (the
logical clock does not advance between requests unless a test sets it).
"""
import threading

from util import CLOCK, new_id

COLLECTIONS = [
    "programs",
    "districts",
    "poles",
    "audits",
    "crews",
    "routes",
    "stops",
    "work_orders",
    "rate_schedules",
    "accounts",
    "billing_lines",
    "tickets",
    "salvage_batches",
    "salvage_items",
    "reports",
    "exceptions",
]


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.seq = 0
        self.lock = threading.RLock()

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


store = Store()


def new_record(collection: str, fields: dict) -> dict:
    """Create a record with common fields and store it."""
    rec = dict(fields)
    rec["id"] = new_id()
    ts = CLOCK.now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    getattr(store, collection)[rec["id"]] = rec
    return rec


def touch(rec: dict):
    """One mutation of a resource: version += 1, updated_at refreshed."""
    rec["version"] += 1
    rec["updated_at"] = CLOCK.now_ts()


def public(rec: dict) -> dict:
    """Strip private keys for serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
