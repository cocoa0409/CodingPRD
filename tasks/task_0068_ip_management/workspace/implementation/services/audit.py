"""AuditEntry creation & emission."""
import db


def emit(subject_entity: str, subject_id: str, actor_role: str, actor_id: str,
         event_type: str, from_state=None, to_state=None, payload=None):
    entry = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "event_type": event_type,
        "from_state": from_state,
        "to_state": to_state,
        "payload": payload or {},
    }
    db.audit_entries.append(entry)
    return entry
