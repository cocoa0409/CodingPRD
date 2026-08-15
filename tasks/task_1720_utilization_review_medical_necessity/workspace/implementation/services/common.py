"""Common system-managed fields and entity helpers."""
import db
from db import new_id, now_iso


def init_common():
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity):
    """Refresh updated_at and bump version on any mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def append_audit(case_id, event_type, actor_role, actor_id, payload_summary):
    """AuditEvent: append-only; carries id and created_at only (no updated_at/version)."""
    evt = {
        "id": new_id(),
        "created_at": now_iso(),
        "case_id": case_id,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload_summary": payload_summary,
    }
    db.audit_events[evt["id"]] = evt
    return evt
