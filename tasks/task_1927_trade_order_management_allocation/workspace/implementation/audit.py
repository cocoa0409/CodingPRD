"""Append-only audit trail (PRD §2.10)."""
import db
from util import new_id, wall_now_iso


def record(entity_type, entity_id, action, actor_role, actor_user_id, detail=""):
    ev = {
        "id": new_id(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "detail": detail,
        "created_at": wall_now_iso(),
        "_seq": db.next_seq(),
    }
    db.store["audit_events"][ev["id"]] = ev
    return ev


def record_request(entity_type, entity_id, action, detail=""):
    """Audit event attributed to the current request's headers."""
    from middleware import actor

    role, user_id = actor()
    return record(entity_type, entity_id, action, role, user_id, detail)


def record_system(entity_type, entity_id, action, detail=""):
    """Audit event for automatic transitions (actor literally 'system')."""
    return record(entity_type, entity_id, action, "system", "system", detail)
