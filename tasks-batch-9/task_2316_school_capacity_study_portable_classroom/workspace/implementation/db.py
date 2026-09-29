"""In-memory data store.

Storage is plain Python dictionaries keyed by id.  The store is EMPTY on every
boot; no entity is ever seeded, preloaded or hardcoded at startup.  Every row
in it was created by a client through the declared API surface.
"""

import itertools
import uuid

from clock import clock

_seq_counter = itertools.count(1)


class Store:
    def __init__(self):
        self.schools = {}
        self.policies = {}
        self.rooms = {}
        self.set_asides = {}
        self.projections = {}
        self.budgets = {}
        self.crews = {}
        self.studies = {}
        self.units = {}
        self.sites = {}
        self.requests = {}
        self.permits = {}
        self.schedules = {}
        self.disposals = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def new_record(data, versioned=True):
    """Build a row with its system/common fields (PRD 2.4)."""
    rec = {"id": new_id()}
    rec.update(data)
    rec["created_at"] = clock.iso()
    if versioned:
        rec["updated_at"] = clock.iso()
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """A real mutation: refresh updated_at and increment version (PRD 2.10)."""
    if rec is None:
        return rec
    if "updated_at" in rec:
        rec["updated_at"] = clock.iso()
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    return rec


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]


def created_order(records):
    """Deterministic created_at ascending order (PRD 2.10)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def all_of(table):
    return created_order(list(table.values()))
