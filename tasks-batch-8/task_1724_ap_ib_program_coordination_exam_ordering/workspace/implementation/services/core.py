"""Record lifecycle: creation stamps and mutation touch (PRD 2.5)."""
from db import db, next_seq
from util import new_id, now_ts


def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1
