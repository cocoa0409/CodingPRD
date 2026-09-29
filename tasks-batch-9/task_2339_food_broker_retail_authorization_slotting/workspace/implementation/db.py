"""In-memory data store.

Storage is process-local Python dictionaries keyed by id.  The store starts
completely empty on every boot: nothing is seeded, preloaded or hardcoded.
Every entity a caller needs is created through the declared API surface.
"""

import uuid

import clock
from errors import ApiError

COLLECTIONS = (
    "retailers",
    "principals",
    "agreements",
    "conflict_rules",
    "items",
    "reviews",
    "presentations",
    "deals",
    "authorizations",
    "snapshots",
    "promotions",
    "deductions",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    """Common audit fields (PRD section 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": clock.iso_now(),
    }
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


# --------------------------------------------------------------------------
# mutation helpers
# --------------------------------------------------------------------------

def _touched_set():
    from flask import g
    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def touch(rec):
    """Refresh updated_at and advance version by exactly one per request."""
    if rec is None or "version" not in rec:
        return
    rec["updated_at"] = clock.iso_now()
    touched = _touched_set()
    if rec["id"] not in touched:
        rec["version"] += 1
        touched.add(rec["id"])


def assign(rec, **fields):
    """Apply fields; touch the record when at least one value actually changed."""
    changed = False
    for key, value in fields.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

_NOT_FOUND = {
    "retailers": "ERR_RETAILER_NOT_FOUND",
    "principals": "ERR_PRINCIPAL_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "conflict_rules": "ERR_CONFLICT_RULE_NOT_FOUND",
    "items": "ERR_ITEM_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
    "presentations": "ERR_PRESENTATION_NOT_FOUND",
    "deals": "ERR_DEAL_NOT_FOUND",
    "authorizations": "ERR_AUTHORIZATION_NOT_FOUND",
    "snapshots": "ERR_SNAPSHOT_NOT_FOUND",
    "promotions": "ERR_PROMOTION_NOT_FOUND",
    "deductions": "ERR_DEDUCTION_NOT_FOUND",
}


def get(collection, identifier, error_id=None):
    table = getattr(db, collection)
    if not isinstance(identifier, str) or identifier not in table:
        raise ApiError(error_id or _NOT_FOUND[collection])
    return table[identifier]


def find(collection, identifier):
    table = getattr(db, collection)
    if not isinstance(identifier, str):
        return None
    return table.get(identifier)


def insert(collection, rec):
    getattr(db, collection)[rec["id"]] = rec
    return rec


def ordered(collection):
    """All records of a collection in created_at ascending order."""
    return sorted(getattr(db, collection).values(), key=lambda r: (r["created_at"], r["_seq"]))


def public(rec):
    """Strip internal bookkeeping keys."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}
