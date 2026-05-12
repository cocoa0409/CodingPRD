"""Audit log helper."""
from flask import g

import db


def audit(subject_type: str, subject_id: str, action: str, payload=None,
          actor_id: str = None, actor_role: str = None) -> dict:
    row = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role if actor_role is not None else getattr(g, "user_role", "system"),
        "actor_id": actor_id if actor_id is not None else getattr(g, "user_id", "system"),
        "action": action,
        "payload": payload or {},
    }
    db.stamp_create(row, common_fields=False)
    db.audit_logs[row["id"]] = row
    return row
