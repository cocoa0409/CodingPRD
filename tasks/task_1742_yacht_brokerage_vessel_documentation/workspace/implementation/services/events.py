"""Domain event emission (append-only audit log)."""
from db import db, new_id, utc_now_iso


def emit(aggregate_type, aggregate_id, event_type, actor_role, actor_id, payload=None):
    ev = {
        "id": new_id(),
        "created_at": utc_now_iso(),
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload": payload or {},
    }
    db.domain_events[ev["id"]] = ev
    return ev
