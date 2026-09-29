"""In-memory data store.

Every collection starts empty on boot. Nothing is ever seeded, preloaded or
hardcoded; every row is created by a declared endpoint.
"""
import uuid

from flask import g

import util

COLLECTIONS = (
    "providers",
    "courses",
    "credit_allocations",
    "course_applications",
    "attorneys",
    "compliance_cycles",
    "affirmations",
    "credit_records",
    "attendance_reports",
    "reciprocity_claims",
    "provider_audits",
    "complaints",
    "fee_assessments",
    "reporting_sweeps",
)

# name -> {id: row}
store = {name: {} for name in COLLECTIONS}

_counter = {"seq": 0}

# entities that carry only id + created_at (PRD 2.5)
IMMUTABLE_COLLECTIONS = {"credit_allocations", "affirmations", "reporting_sweeps"}


def reset():
    for name in COLLECTIONS:
        store[name] = {}
    _counter["seq"] = 0
    util.reset_clock()


def next_seq():
    _counter["seq"] += 1
    return _counter["seq"]


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields):
    row = dict(fields)
    row["id"] = row.get("id") or new_id()
    row["created_at"] = util.now_iso()
    if collection not in IMMUTABLE_COLLECTIONS:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    row["_collection"] = collection
    store[collection][row["id"]] = row
    # A row born inside this request stays at version 1 however many times the
    # same request rewrites it afterwards (PRD 2.5).
    _register_touched(row["id"])
    return row


def _register_touched(row_id):
    try:
        seen = g._touched_rows
    except Exception:
        try:
            seen = g._touched_rows = set()
        except Exception:
            return
    if seen is None:
        try:
            seen = g._touched_rows = set()
        except Exception:
            return
    seen.add(row_id)


def get(collection, row_id):
    if row_id is None:
        return None
    return store[collection].get(row_id)


def all_rows(collection):
    return list(store[collection].values())


def touch(row):
    """Record a mutation: refresh updated_at and bump version exactly once
    per request for this row (PRD 2.5)."""
    if row is None or "version" not in row:
        return row
    row["updated_at"] = util.now_iso()
    try:
        seen = g._touched_rows
    except Exception:
        seen = None
    if seen is None:
        try:
            seen = g._touched_rows = set()
        except Exception:
            seen = None
    key = row.get("id")
    if seen is None:
        row["version"] += 1
        return row
    if key not in seen:
        seen.add(key)
        row["version"] += 1
    return row


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_all(rows):
    return [serialize(r) for r in rows]


def sort_key_created(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)
