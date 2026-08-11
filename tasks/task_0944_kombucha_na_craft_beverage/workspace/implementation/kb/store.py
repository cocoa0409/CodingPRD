"""In-memory store.

Nothing is persisted and nothing is seeded: the process starts with every
collection empty and a logical clock reading exactly 2026-05-01T00:00:00Z.
"""

import uuid
from datetime import datetime

from .util import UTC

COLLECTIONS = (
    "recipes",
    "label_approvals",
    "scoby_cultures",
    "vessels",
    "ingredient_lots",
    "batches",
    "batch_ingredient_uses",
    "qa_readings",
    "packaging_runs",
    "finished_lots",
    "kegs",
    "accounts",
    "shipments",
    "shipment_lines",
    "subscriptions",
    "subscription_allocations",
    "taproom_fills",
    "recall_notices",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = datetime(2026, 5, 1, 0, 0, 0, 0, tzinfo=UTC)
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(with_common=True):
    """id / created_at (/ updated_at / version) plus the ordering sequence."""
    record = {"id": new_id(), "created_at": db.clock}
    if with_common:
        record["updated_at"] = db.clock
        record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and advance the concurrency token by exactly one."""
    record["updated_at"] = db.clock
    record["version"] = record.get("version", 1) + 1
    return record


def collection_sorted(mapping, predicate=None):
    """Records in created_at ascending order (insertion order as tie-break)."""
    rows = [r for r in mapping.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
