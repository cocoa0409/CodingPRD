"""In-memory store. Nothing is seeded: every table starts empty on every boot."""

import itertools
import uuid

import timeutil

TABLE_NAMES = [
    "plans",
    "members",
    "cycles",
    "styles",
    "units",
    "boxes",
    "box_items",
    "swap_requests",
    "shipments",
    "labels",
    "assessments",
    "jobs",
    "submissions",
    "trade_in_items",
    "credit_entries",
    "charge_entries",
    "buyout_orders",
    "capsules",
    "capsule_allocations",
    "pause_requests",
    "claims",
]

db = {name: {} for name in TABLE_NAMES}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(table, row):
    row.setdefault("id", new_id())
    stamp = timeutil.now()
    row.setdefault("created_at", stamp)
    row.setdefault("updated_at", stamp)
    row.setdefault("version", 1)
    row["_seq"] = next(_seq)
    db[table][row["id"]] = row
    return row


def touch(row):
    """One declared mutation step on one row: bump version, refresh updated_at.

    Always called BEFORE the response is serialized, so a mutation response
    always carries the post-mutation version (PRD 2.4).
    """
    row["updated_at"] = timeutil.now()
    row["version"] = row.get("version", 1) + 1
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db[table].get(row_id)


def all_rows(table):
    return sorted(db[table].values(), key=order_key)


def order_key(row):
    return (row["created_at"], row["_seq"])


def find(table, **filters):
    out = []
    for row in all_rows(table):
        ok = True
        for key, value in filters.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def where(table, predicate):
    return [row for row in all_rows(table) if predicate(row)]
