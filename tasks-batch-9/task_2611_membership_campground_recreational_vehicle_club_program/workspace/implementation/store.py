"""In-memory data store.

Every collection is a plain dict keyed by the row's uuid `id`. The store starts
completely empty on every boot: no entity is ever seeded, preloaded or hardcoded.
"""

import itertools
import uuid

import clock

COLLECTIONS = (
    "membership_tiers",
    "members",
    "memberships",
    "parks",
    "reservations",
    "affiliate_agreements",
    "dues_invoices",
    "transfer_requests",
    "amenity_inspections",
    "satisfaction_surveys",
    "capital_projects",
    "occupancy_exceptions",
    "maintenance_windows",
)

_seq = itertools.count(1)

db = {name: {} for name in COLLECTIONS}


def reset():
    global _seq
    for name in COLLECTIONS:
        db[name] = {}
    _seq = itertools.count(1)
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_row(versioned=True):
    """Common audit columns (PRD 2.4)."""
    stamp = clock.now_iso()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = clock.now_iso()
    return row


def insert(collection, row):
    db[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db[collection].get(row_id)


def all_rows(collection):
    return list(db[collection].values())


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(rows):
    return sorted(rows, key=sort_key)
