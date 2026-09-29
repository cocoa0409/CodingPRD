"""In-memory data store.  Starts completely empty on every boot.

No seeding, no preloading, no persistence to disk of any kind.
"""
import itertools
import uuid

import clock

COLLECTIONS = (
    "associations",
    "owners",
    "units",
    "ledger_entries",
    "budgets",
    "billing_runs",
    "special_assessments",
    "votes",
    "board_meetings",
    "common_elements",
    "vendor_contracts",
    "work_orders",
    "insurance_claims",
    "violation_cases",
    "resale_certificates",
)

store = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def reset():
    for name in COLLECTIONS:
        store[name] = {}
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic creation sequence, used as a stable tiebreaker for equal created_at."""
    return next(_seq)


def insert(collection, row):
    store[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return store[collection].get(row_id)


def all_rows(collection):
    return list(store[collection].values())


def sorted_rows(collection, predicate=None):
    rows = [r for r in store[collection].values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def _bumped_set():
    """Per-request set of rows whose version has already advanced.

    PRD 2.8: a cascade may touch the same row through several hops, but "each of
    those rows advances its own version by 1" -- exactly one bump per request.
    """
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        seen = g.get("_bumped_rows")
        if seen is None:
            seen = set()
            g._bumped_rows = seen
        return seen
    except Exception:
        return None


def touch(row):
    """Refresh updated_at and bump version by exactly 1 (versioned entities only)."""
    if "updated_at" in row:
        row["updated_at"] = clock.now()
    if "version" in row:
        seen = _bumped_set()
        if seen is None:
            row["version"] += 1
        elif row["id"] not in seen:
            seen.add(row["id"])
            row["version"] += 1
    return row


def force_touch(row):
    """Bump the version unconditionally, ignoring the per-request dedupe."""
    if "updated_at" in row:
        row["updated_at"] = clock.now()
    if "version" in row:
        row["version"] += 1
        seen = _bumped_set()
        if seen is not None:
            seen.add(row["id"])
    return row


def base_fields(versioned=True):
    now = clock.now()
    row = {"id": new_id(), "created_at": now, "_seq": next_seq()}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    return row
