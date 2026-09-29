"""In-memory data store.

The store is empty on every boot.  Nothing is seeded, preloaded or hardcoded:
every entity the API exposes is created by a client request.
"""

import uuid

import clock
from util import iso_instant

KINDS = (
    "client",
    "space",
    "policy_window",
    "booking",
    "hold",
    "license",
    "vendor",
    "jurisdiction",
    "service_order",
    "labor_call",
    "catering",
    "usage_record",
    "settlement",
    "line_item",
    "blackout",
)


class Store(dict):
    """A table of records keyed by id, with deterministic listing order."""

    def rows(self):
        return sorted(self.values(), key=lambda r: (r["created_at"], r["_seq"]))


class Database(object):
    def __init__(self):
        self._seq = 0
        for kind in KINDS:
            setattr(self, kind + "s", Store())
        # explicit, readable aliases for the irregular plurals
        self.tables = {kind: getattr(self, kind + "s") for kind in KINDS}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def insert(self, kind, fields, versioned=True):
        stamp = iso_instant(clock.now())
        rec = {
            "id": str(uuid.uuid4()),
            "_kind": kind,
            "_seq": self.next_seq(),
        }
        rec.update(fields)
        rec["created_at"] = stamp
        if versioned:
            rec["updated_at"] = stamp
            rec["version"] = 1
        self.tables[kind][rec["id"]] = rec
        return rec


db = Database()


def public(rec):
    """Strip the internal bookkeeping keys from a record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
