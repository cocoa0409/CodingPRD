"""In-memory data store and the server-held logical plant clock (PRD 2.4).

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded here. Every entity is created by an API call.
"""
import itertools
import uuid
from datetime import datetime, timezone

from flask import g

# Before any call to POST /_clock/set_current_utc the logical clock reads
# exactly this instant, and the server never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "customer_accounts",
    "model_specs",
    "approved_parts",
    "test_benches",
    "loaner_units",
    "intake_shipments",
    "equipment_units",
    "component_inspections",
    "shell_tests",
    "repair_orders",
    "certification_labels",
    "destruction_records",
    "loaner_assignments",
)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self.clock_raw = None
        self._seq = itertools.count(1)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The current logical-clock instant."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """id / created_at (/ updated_at / version) common fields (PRD 2.4)."""
    record = {
        "id": new_id(),
        "created_at": db.clock,
        "_seq": db.next_seq(),
        "_raw": {},
    }
    if versioned:
        record["updated_at"] = db.clock
        record["version"] = 1
    mark_fresh(record)
    return record


def _touched():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def mark_fresh(record):
    """A row created during this request must not also be version-bumped by it."""
    _touched().add(id(record))


def touch(record):
    """Stamp updated_at and advance version by exactly one for this mutation.

    PRD 2.4: `version` "increases by exactly one on every mutation that changes
    the row", so a single request that writes several fields of the same row
    (a cascade hop touching counters and status together) advances it once.
    """
    if record is None:
        return record
    seen = _touched()
    if id(record) in seen:
        return record
    seen.add(id(record))
    if "version" in record:
        record["version"] = record.get("version", 1) + 1
    if "updated_at" in record:
        record["updated_at"] = db.clock
    return record


def ordered(values):
    """created_at ascending, with insertion order as the deterministic tie-break."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))


def raw_set(record, field, value):
    """Remember the caller's literal datetime string so reads echo it verbatim."""
    record["_raw"][field] = value
