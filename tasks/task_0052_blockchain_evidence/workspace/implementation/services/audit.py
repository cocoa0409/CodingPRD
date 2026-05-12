"""Audit log helper."""
from flask import g

import db


def append(event_type: str, target_entity: str, target_id: str,
           detail: dict, actor_role: str = None, actor_id: str = None) -> dict:
    """Append an AuditLog row.

    If actor_role / actor_id are None, falls back to Flask g (request context).
    Pass actor_role="system" explicitly for system-driven cascades.
    """
    if actor_role is None:
        actor_role = getattr(g, "user_role", "system") or "system"
    if actor_id is None:
        actor_id = getattr(g, "user_id", None)
    row = {
        "actor_role": actor_role,
        "actor_id": actor_id,
        "event_type": event_type,
        "target_entity": target_entity,
        "target_id": target_id,
        "detail": detail or {},
    }
    db.stamp_create(row, common_fields=False)
    db.audit_logs[row["id"]] = row
    return row
