"""Audit log helpers — append-only polymorphic log."""

from flask import g

from db import db, light_fields_create


def append_audit(target_type: str, target_id: str, action: str, payload: dict):
    """Append an immutable AuditLog row.

    Snapshots actor_role and actor_id from request headers via Flask g.
    """
    entry = {
        "id": db.new_id(),
        **light_fields_create(),
        "target_type": target_type,
        "target_id": target_id,
        "actor_role": getattr(g, "user_role", None),
        "actor_id": getattr(g, "user_id", None),
        "action": action,
        "payload": payload,
    }
    db.audit_logs.append(entry)
    return entry
