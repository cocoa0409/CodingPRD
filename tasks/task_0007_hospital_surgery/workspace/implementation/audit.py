from flask import g

from db import db, _now_iso


def write_audit(entity_type: str, entity_id: str, action: str, payload: dict):
    actor_role = getattr(g, "user_role", "system")
    actor_user_id = getattr(g, "user_id", "system")
    entry = {
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "payload": payload or {},
        "occurred_at_minute": db.current_minute,
        "id": db.new_id(),
        "created_at": _now_iso(),
        "_seq": db.next_seq(),
    }
    db.audit_entries[entry["id"]] = entry
    return entry
