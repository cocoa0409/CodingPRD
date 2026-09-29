"""In-memory data store and the logical clock.

The store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded. Every row is created by an API call.
"""

import uuid
from datetime import datetime

from flask import g, has_request_context

from util import UTC

TABLES = [
    "customers",
    "sites",
    "chemical_products",
    "machine_models",
    "technicians",
    "service_agreements",
    "machine_placements",
    "dispensers",
    "telemetry_readings",
    "telemetry_alerts",
    "service_tickets",
    "service_visits",
    "calibration_records",
    "chemical_deliveries",
    "usage_variance_reviews",
    "investigation_cases",
]

# PRD 2.4: the logical clock starts at exactly this instant on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
CLOCK_START_STR = "2026-08-01T00:00:00Z"


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.t = dict((name, {}) for name in TABLES)
        self.clock = CLOCK_START
        self.clock_str = CLOCK_START_STR
        self._seq = 0
        self._req = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_request_id(self):
        self._req += 1
        return "req_%s" % uuid.uuid4().hex[:16]


db = Store()


def now():
    """The current logical instant."""
    return db.clock


def insert(table, fields, common=True):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["_seq"] = db.next_seq()
    row["_table"] = table
    row["created_at"] = db.clock
    if common:
        row["updated_at"] = db.clock
        row["version"] = 1
    db.t[table][row["id"]] = row
    return row


def touch(row):
    """Record a mutation: bump the version and the update instant."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = db.clock
    return row


def mark(row):
    """Flag a row as mutated by the current request.

    A single request may touch the same row through several code paths (a
    health change, a counter recompute and a cascade link); the row still
    counts as one mutation, so the version bump is deferred and applied once
    when the response is rendered.
    """
    if row is None:
        return None
    if not has_request_context():
        return touch(row)
    dirty = getattr(g, "dirty_rows", None)
    if dirty is None:
        dirty = []
        g.dirty_rows = dirty
    if row.get("_dirty"):
        return row
    row["_dirty"] = True
    dirty.append(row)
    return row


def commit():
    """Apply the deferred version bumps of the current request."""
    if not has_request_context():
        return
    dirty = getattr(g, "dirty_rows", None)
    if not dirty:
        return
    g.dirty_rows = []
    for row in dirty:
        row.pop("_dirty", None)
        touch(row)


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db.t[table].get(row_id)


def rows(table):
    """All rows of a table in created_at ascending (insertion) order."""
    return sorted(db.t[table].values(), key=order_key)


def order_key(row):
    return (row["created_at"], row["_seq"])


def find(table, **kwargs):
    out = []
    for row in rows(table):
        ok = True
        for key, value in kwargs.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out
