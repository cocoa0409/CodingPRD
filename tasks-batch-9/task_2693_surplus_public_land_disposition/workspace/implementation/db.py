"""In-memory store.  Every byte of state lives in this process and vanishes
with it: no file, no cache, no external persistence.  The store starts empty on
every boot — nothing is seeded, preloaded or hardcoded.
"""

import itertools
import uuid

import clockmod

COLLECTION_NAMES = (
    "agencies",
    "parcels",
    "declarations",
    "notices",
    "preference_offers",
    "negotiation_rounds",
    "appraisers",
    "appraisals",
    "appraisal_challenges",
    "environmental_reviews",
    "title_items",
    "offerings",
    "bidders",
    "bids",
    "conveyances",
    "funds",
    "proceeds_allocations",
)

stores = {name: {} for name in COLLECTION_NAMES}
_seq = itertools.count(1)


def reset():
    """Drop every row.  Used only by the process boot path."""
    global _seq
    for name in COLLECTION_NAMES:
        stores[name].clear()
    _seq = itertools.count(1)
    clockmod.reset()


def new_id():
    return str(uuid.uuid4())


def insert(collection, record):
    """Insert a full resource row: id, created_at, updated_at, version."""
    now = clockmod.now()
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = next(_seq)
    stores[collection][record["id"]] = record
    return record


def insert_event(collection, record):
    """Insert an immutable event row: id and created_at only (PRD 2.4)."""
    record["id"] = new_id()
    record["created_at"] = clockmod.now()
    record["_seq"] = next(_seq)
    stores[collection][record["id"]] = record
    return record


def touch(record):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4, 2.11)."""
    record["updated_at"] = clockmod.now()
    record["version"] = record.get("version", 0) + 1
    return record


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return stores[collection].get(row_id)


def all_rows(collection):
    """Every row, in created_at ascending order (insertion order breaks ties)."""
    rows = list(stores[collection].values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def where(collection, **criteria):
    rows = all_rows(collection)
    for key, value in criteria.items():
        rows = [r for r in rows if r.get(key) == value]
    return rows


def set_raw(record, field, raw_text):
    """Remember the exact instant string a client supplied for a field."""
    record.setdefault("_raw", {})[field] = raw_text
