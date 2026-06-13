"""Entity construction, common-field management, and serialization.

Primary resources (common_fields:true) carry id, created_at, updated_at, version(=1 at create).
RecipientVerification and LedgerEntry are lean: only id + created_at.
"""
import clock
from db import db


def _stamp_create(obj):
    now = db.now()
    obj["id"] = db.new_id()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def _stamp_lean(obj):
    obj["id"] = db.new_id()
    obj["created_at"] = db.now()
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    """Mark a primary resource mutated: bump updated_at + version."""
    obj["updated_at"] = db.now()
    obj["version"] = obj.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serialization: emit public fields with timestamps formatted, internal keys
# (those starting with "_") dropped.
# ---------------------------------------------------------------------------
_DATETIME_FIELDS = {"created_at", "updated_at", "expires_at", "settled_at"}


def serialize(obj):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if k in _DATETIME_FIELDS:
            out[k] = clock.format_iso8601(v) if v is not None else None
        else:
            out[k] = v
    return out


def serialize_list(objs):
    return [serialize(o) for o in objs]


def sort_by_created(objs):
    """created_at ASC; ties broken by insertion sequence to keep deterministic order."""
    return sorted(objs, key=lambda o: (o["created_at"], o["_seq"]))
