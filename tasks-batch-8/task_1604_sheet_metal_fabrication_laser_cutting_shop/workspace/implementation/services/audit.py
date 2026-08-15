"""Audit trail. Append-only AuditEvent rows (id + created_at only)."""
from db import store, new_id, wall_now, next_seq


def audit(entity_type, entity_id, event_type, actor_role, actor_id, detail=None):
    event = {
        "id": new_id(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "detail": detail or {},
        "created_at": wall_now(),
        "_seq": next_seq(),
    }
    store.audit_events.append(event)
    return event
