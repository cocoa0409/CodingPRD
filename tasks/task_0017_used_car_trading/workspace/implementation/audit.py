"""Audit log helpers."""

from flask import g, has_request_context

from clock import iso, now
from db import DB_INSTANCE, new_uuid


def log(target_entity: str, target_id: str, event_type: str,
        from_value=None, to_value=None, actor_role=None, actor_id=None):
    """Append an AuditLog row.

    `event_type` is one of STATE_TRANSITION, OWNERSHIP_CHANGE,
    FINANCIAL_HOLD, FINANCIAL_RELEASE, EXTERNAL_SYNC.
    """
    if actor_role is None or actor_id is None:
        if has_request_context() and hasattr(g, "role"):
            actor_role = actor_role or g.role
            actor_id = actor_id or g.user_id
        else:
            actor_role = actor_role or "system"
            actor_id = actor_id or "system"

    row = {
        "id": new_uuid(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "target_entity": target_entity,
        "target_id": target_id,
        "event_type": event_type,
        "from_value": str(from_value) if from_value is not None else None,
        "to_value": str(to_value) if to_value is not None else None,
        "occurred_at": iso(now()),
        "created_at": iso(now()),
    }
    DB_INSTANCE.audit_logs.append(row)
    return row
