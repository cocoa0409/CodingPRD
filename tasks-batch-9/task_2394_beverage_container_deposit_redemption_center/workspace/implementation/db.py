"""In-memory storage. Plain Python dicts; nothing is seeded, nothing touches disk."""
import itertools
import uuid

from flask import g

import clock

_seq = itertools.count(1)

distributors = {}
products = {}
centers = {}
machines = {}
accounts = {}
visits = {}
lots = {}
bag_drops = {}
credit_entries = {}
batches = {}
ledger_entries = {}
periods = {}
retailers = {}

ALL_STORES = (
    distributors, products, centers, machines, accounts, visits, lots,
    bag_drops, credit_entries, batches, ledger_entries, periods, retailers,
)


def reset_all():
    for store in ALL_STORES:
        store.clear()


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def new_record(fields, versioned=True):
    """Build a record: id, created_at, then the entity fields, then updated_at/version."""
    now = clock.now_iso()
    rec = {"id": new_id(), "created_at": now}
    rec.update(fields)
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Bump version + updated_at, at most once per HTTP request per record."""
    if rec is None or "version" not in rec:
        return rec
    try:
        bumped = g._bumped
    except (AttributeError, RuntimeError):
        bumped = None
    key = id(rec)
    if bumped is None:
        try:
            g._bumped = bumped = set()
        except RuntimeError:
            bumped = set()
    if key not in bumped:
        bumped.add(key)
        rec["version"] = int(rec.get("version", 1)) + 1
    rec["updated_at"] = clock.now_iso()
    return rec


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(store, predicate=None):
    """All records in created_at (insertion) ascending order."""
    rows = [r for r in store.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: r["_seq"])
    return rows
