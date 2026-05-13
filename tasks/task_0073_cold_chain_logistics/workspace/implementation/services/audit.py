"""Audit log writing helper."""

from clock import clock
from db import db, new_id


def log(subject_type: str, subject_id: str, action: str, actor_role: str, actor_id: str):
    entry = {
        "id": new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "occurred_at": clock.now_iso(),
        "created_at": clock.now_iso(),
    }
    db.audit.put(entry)
    return entry
