"""In-memory data store.

Storage is pure Python dicts keyed by id. Nothing is ever seeded: every boot
starts completely empty and every entity is built by the API surface.
"""
import itertools
import uuid

import clock

# collections that carry `updated_at` + `version` (PRD §2.4)
VERSIONED = [
    "programs",
    "milestones",
    "permits",
    "systems",
    "hiring_plans",
    "hires",
    "training_sessions",
    "budget_lines",
    "ose_orders",
    "reservation_blocks",
    "punch_items",
]
# append-only join / evidence rows: only `id` and `created_at`
APPEND_ONLY = ["dependencies", "test_runs"]

COLLECTIONS = VERSIONED + APPEND_ONLY


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})


db = Store()
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp():
    return clock.fmt_instant(clock.wall_now())


# ---------------------------------------------------------------------------
# Snapshot / commit: "recomputation of a derived field counts as a mutation of
# the record that owns the field" (PRD §2.4).  A single request bumps a given
# record's version at most once, no matter how many recomputation passes wrote
# to it.
# ---------------------------------------------------------------------------

_snapshots = {}


def begin(request_key):
    snap = {}
    for name in VERSIONED:
        coll = getattr(db, name)
        for rid, rec in coll.items():
            snap[(name, rid)] = dict(rec)
    _snapshots[request_key] = snap


def finish(request_key, force_ids=()):
    snap = _snapshots.pop(request_key, None)
    if snap is None:
        return
    force = set(force_ids or ())
    ts = stamp()
    for name in VERSIONED:
        coll = getattr(db, name)
        for rid, rec in coll.items():
            old = snap.get((name, rid))
            if old is None:
                continue  # created during this request: version stays 1
            if rid in force or _differs(old, rec):
                rec["version"] = rec.get("version", 1) + 1
                rec["updated_at"] = ts


def discard(request_key):
    _snapshots.pop(request_key, None)


def _differs(old, new):
    keys = set(old) | set(new)
    for key in keys:
        if key.startswith("_") or key in ("version", "updated_at"):
            continue
        if old.get(key) != new.get(key):
            return True
    return False


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------

def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
