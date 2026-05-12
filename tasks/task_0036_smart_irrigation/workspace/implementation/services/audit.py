"""Audit log helpers."""

from flask import g

from db import DB, new_id
from services.common import stamp_create_appendonly


def append_audit(action_type: str, subject_type: str, subject_id: str, payload: dict):
    rec = stamp_create_appendonly({
        "id": new_id(),
        "actor_role": getattr(g, "role", None),
        "actor_id": getattr(g, "user_id", None),
        "action_type": action_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload or {},
    })
    DB.audit_logs.append(rec)
    return rec
