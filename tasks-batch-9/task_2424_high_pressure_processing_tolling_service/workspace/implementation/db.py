"""In-memory data store.

The store is EMPTY on every boot.  Nothing is seeded, preloaded or hardcoded;
every entity is created by a client through the declared API surface.
"""
import itertools
import uuid

from flask import g

import clock


class _Store(object):
    def __init__(self):
        self.customers = {}
        self.product_families = {}
        self.vessels = {}
        self.cold_rooms = {}
        self.qualifications = {}
        self.validation_runs = {}
        self.contracts = {}
        self.lots = {}
        self.cycles = {}
        self.loads = {}
        self.cycle_logs = {}
        self.deviations = {}
        self.chargeback_lines = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = _Store()


def new_id():
    return str(uuid.uuid4())


def insert(store, fields):
    """Create a row carrying the full common-field set (PRD 2.4)."""
    ts = clock.now()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    store[row["id"]] = row
    return row


def insert_event(store, fields):
    """Create an append-only event row: only id and created_at (PRD 2.4)."""
    row = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
    }
    row.update(fields)
    store[row["id"]] = row
    return row


def _touched():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def touch(row):
    """Refresh updated_at and increment version exactly once per request.

    PRD 2.9: "Each row touched in such a chain has its own updated_at refreshed
    and its own version incremented by one, including rows the caller never
    named."  One increment per row per request.
    """
    if row is None or "version" not in row:
        return row
    seen = _touched()
    row["updated_at"] = clock.now()
    if row["id"] not in seen:
        seen.add(row["id"])
        row["version"] += 1
    return row


def sort_key(row):
    """created_at ascending, insertion order as the stable tie-break."""
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)
