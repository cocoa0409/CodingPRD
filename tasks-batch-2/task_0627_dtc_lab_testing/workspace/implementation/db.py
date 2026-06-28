"""In-memory data store (PRD §2.4).

Storage is in-memory only — Python dicts keyed by id. The store starts EMPTY on
every boot; no entity is ever seeded, preloaded, or hardcoded. Tests build all
state via the API surface. start.sh re-invocation wipes all state because this
module is re-imported in a fresh process.
"""
import itertools
import uuid

import clock

# One dict per entity type, keyed by id.
TABLES = [
    "test_offerings",
    "panel_bundles",
    "patients",
    "carts",
    "cart_lines",
    "orders",
    "order_lines",
    "physician_orders",
    "appointments",
    "home_kits",
    "specimens",
    "lab_results",
    "telehealth_referrals",
    "analyzer_runs",
    "payments",
]

store = {}
# Monotonic counter used only to deterministically tie-break entities created at
# the same logical-clock instant (created_at ties).
_seq = None


def reset():
    global store, _seq
    store = {t: {} for t in TABLES}
    _seq = itertools.count(1)
    clock.reset()


def _new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    if _seq is None:
        reset()
    return next(_seq)


def new_record(extra_fields=None):
    """Create a record with common fields id/created_at/updated_at/version."""
    ts = clock.now_iso()
    rec = {
        "id": _new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    if extra_fields:
        rec.update(extra_fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation (PRD §2.4, §2.6)."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 1) + 1


def insert(table, rec):
    store[table][rec["id"]] = rec
    return rec


def get(table, rec_id):
    if rec_id is None:
        return None
    return store[table].get(rec_id)


def all_rows(table):
    return list(store[table].values())


def sorted_rows(rows):
    """Default sort: created_at ASC, tie-break by creation sequence (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


# Initialize at import so the very first request has tables ready.
reset()
