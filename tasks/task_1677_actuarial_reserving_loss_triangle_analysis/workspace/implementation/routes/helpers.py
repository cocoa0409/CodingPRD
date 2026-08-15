"""Shared route helpers."""
from db import next_seq
from util import new_id, now_ts


def new_common_record(fields):
    """Instantiate a common-fields record (id/created_at/updated_at/version)."""
    ts = now_ts()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def new_event_record(fields):
    """Instantiate an append-only event record (id/created_at only)."""
    rec = {
        "id": new_id(),
        "created_at": now_ts(),
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


def sorted_by_creation(records):
    return sorted(records, key=lambda r: r.get("_seq", 0))


def strip_internal(rec):
    out = dict(rec)
    out.pop("_seq", None)
    return out
