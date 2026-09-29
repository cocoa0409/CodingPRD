"""In-memory data store.

The store is EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Every row any caller sees was created through the declared API surface.
"""

import itertools
import uuid

import clock


class Database:
    def __init__(self):
        self.reset()

    def reset(self):
        self.state_rules = {}
        self.stores = {}
        self.customers = {}
        self.references = {}
        self.units = {}
        self.crews = {}
        self.agreements = {}
        self.payments = {}
        self.windows = {}
        self.delivery_orders = {}
        self.tickets = {}
        self.inspections = {}
        self.contacts = {}
        self.quotes = {}
        self.ledger = {}
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Database()

_fallback_touched = set()


def _touched():
    try:
        from flask import g, has_request_context

        if has_request_context():
            store = getattr(g, "touched_rows", None)
            if store is None:
                store = set()
                g.touched_rows = store
            return store
    except Exception:
        pass
    return _fallback_touched


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    """Server-minted identity and mutation bookkeeping fields (PRD 2.6)."""
    stamp = clock.now_str()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    _touched().add(id(row))
    return row


def touch(row):
    """Refresh updated_at and increment version, at most once per request."""
    if row is None or "version" not in row:
        return row
    row["updated_at"] = clock.now_str()
    seen = _touched()
    key = id(row)
    if key not in seen:
        seen.add(key)
        row["version"] += 1
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows, primary=None):
    """Primary key ascending, then created_at ascending, then insertion order."""
    def key(row):
        head = row.get(primary) or "" if primary else ""
        return (head, row.get("created_at") or "", row.get("_seq", 0))

    return sorted(rows, key=key)
