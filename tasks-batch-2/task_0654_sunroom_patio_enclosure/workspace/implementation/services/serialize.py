"""Serialize internal entities to API-facing JSON (PRD §2.4 fields/timestamps)."""
from db import iso

# datetime-typed fields per entity that must be ISO-formatted on output.
_DATETIME_FIELDS = {
    "created_at", "updated_at", "expires_at", "promised_ready_at",
    "ready_at", "starts_at", "scheduled_start", "scheduled_end",
}


def _serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in _DATETIME_FIELDS:
            out[k] = iso(v) if v is not None else None
        else:
            out[k] = v
    return out


def homeowner(e):
    return _serialize(e)


def project(e):
    return _serialize(e)


def measurement(e):
    return _serialize(e)


def quote(e):
    return _serialize(e)


def financing(e):
    return _serialize(e)


def permit(e):
    return _serialize(e)


def engineering(e):
    return _serialize(e)


def manufacture(e):
    return _serialize(e)


def crew(e):
    return _serialize(e)


def install_job(e):
    return _serialize(e)


def inspection(e):
    return _serialize(e)


def warranty(e):
    return _serialize(e)
