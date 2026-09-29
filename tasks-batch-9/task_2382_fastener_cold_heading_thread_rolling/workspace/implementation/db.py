"""In-memory data store.

Nothing is ever seeded here: every collection starts empty on every boot and
all state is created through the declared API surface.
"""

import itertools
from datetime import datetime

from util import UTC, iso, new_id

# The logical clock starts at exactly this instant on every boot (PRD 2.4).
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "part_specs",
    "steel_heats",
    "wire_lots",
    "heading_tools",
    "furnaces",
    "production_lots",
    "secondary_operations",
    "heat_treat_runs",
    "plating_runs",
    "lot_tests",
    "certification_documents",
    "pack_units",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # (part_spec_id, version) -> immutable snapshot of the spec at that version
        self.part_spec_snapshots = {}
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)

    # -- clock ------------------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return iso(self.clock)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_record(fields):
    """Build a record with the common system fields (PRD 2.5)."""
    stamp = db.now_iso()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    record.update(fields)
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Register a mutation: refresh updated_at and bump version by exactly 1."""
    record["updated_at"] = db.now_iso()
    record["version"] = record["version"] + 1
    return record


def order_key(record):
    """Deterministic ascending created_at ordering."""
    return (record.get("created_at") or "", record.get("_seq") or 0)


def sorted_records(records):
    return sorted(records, key=order_key)


def public(record):
    """Strip internal bookkeeping keys before serialisation."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}
