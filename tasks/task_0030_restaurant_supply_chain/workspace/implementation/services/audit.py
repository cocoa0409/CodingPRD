"""Audit log helpers — every state-changing operation appends one row here."""

import clock
import db


def append(*, target_type, target_id, action, payload=None, external_systems=None):
    from flask import g

    actor_role = getattr(g, "user_role", None) or "system"
    actor_user_id = getattr(g, "user_id", None) or "system"

    entry = {
        "id": db.new_id(),
        "target_type": target_type,
        "target_id": target_id,
        "action": action,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "payload": payload if payload is not None else {},
        "external_systems": list(external_systems) if external_systems else [],
        "created_at": clock.now(),
    }
    db.audit_log_entries.append(entry)
    return entry
