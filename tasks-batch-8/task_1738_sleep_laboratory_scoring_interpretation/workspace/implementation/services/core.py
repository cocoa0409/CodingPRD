"""Core record lifecycle: creation, mutation stamps, shared lookups."""
from db import db, next_seq
from util import CLOCK, new_id


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = CLOCK.now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Every mutation (including cascade-driven) refreshes updated_at and bumps version."""
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] = rec.get("version", 1) + 1


def find_one(collection, **conditions):
    for rec in db[collection].values():
        if all(rec.get(k) == v for k, v in conditions.items()):
            return rec
    return None


def find_all(collection, **conditions):
    return [rec for rec in db[collection].values()
            if all(rec.get(k) == v for k, v in conditions.items())]
