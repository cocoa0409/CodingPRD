"""In-memory data store and the server's logical UTC clock.

The store is created empty on every boot. No entity data is ever seeded,
preloaded or hardcoded here: every record is created through the declared
API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any clock-setting call the logical clock reads exactly
# 2026-08-01T00:00:00Z and must never fall back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "ports",
    "fuel_grades",
    "index_quotes",
    "customers",
    "delivery_assets",
    "nominations",
    "delivery_orders",
    "bunker_delivery_notes",
    "quality_claims",
    "lab_analyses",
    "invoices",
    "spill_incidents",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for table in TABLES:
            setattr(self, table, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical clock instant."""
    return store.clock


def _touched_set():
    from flask import g

    touched = getattr(g, "_touched_ids", None)
    if touched is None:
        touched = set()
        g._touched_ids = touched
    return touched


def new_record(common_fields=True):
    """Allocate a record skeleton with the system-managed audit fields."""
    rec = {
        "id": new_id(),
        "created_at": store.clock,
        "_seq": store.next_seq(),
    }
    if common_fields:
        rec["updated_at"] = store.clock
        rec["version"] = 1
    # A record created during this request must not also be "touched".
    _touched_set().add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at and increment version, at most once per request."""
    if rec is None:
        return
    touched = _touched_set()
    if rec["id"] in touched:
        return
    touched.add(rec["id"])
    rec["updated_at"] = store.clock
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def sorted_rows(table, predicate=None):
    """All rows of a table ordered by created_at ascending (PRD 2.3)."""
    rows = [r for r in table.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
