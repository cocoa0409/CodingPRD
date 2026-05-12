"""Audit log helpers."""
import db
from flask import g


def append_audit(project_id: str, subject_type: str, subject_id: str,
                 event_kind: str, payload: dict) -> dict:
    entry = {
        "id": db.gen_id(),
        "created_at": db.now_iso(),
        "project_id": project_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_user_id": getattr(g, "user_id", None),
        "actor_role": getattr(g, "user_role", None),
        "event_kind": event_kind,
        "payload": payload,
    }
    db.audit_entries[entry["id"]] = entry
    return entry
