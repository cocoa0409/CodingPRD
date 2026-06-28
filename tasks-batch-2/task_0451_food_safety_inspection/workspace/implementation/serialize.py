"""Entity -> public JSON projection. Strips internal fields (those starting
with '_') and computes read-time derived fields (e.g. Permit.status).
"""
from db import store


def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize(record, entity=None):
    out = _public(record)
    if entity == "Permit":
        out["status"] = _permit_status(record)
    return out


def _permit_status(permit):
    """Permit status derived on every read (PRD §3.3)."""
    if permit.get("_void"):
        return "VOID"
    if store.clock_index > permit["expires_index"]:
        return "EXPIRED"
    return "ACTIVE"


def serialize_list(records, entity=None):
    return [serialize(r, entity) for r in records]
