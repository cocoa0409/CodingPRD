"""AuditLogEntry helpers."""
from db import store
from services.utils import stamp_create


def append_audit(action_type: str, subject_type: str, subject_id: str,
                 actor_role: str, actor_id: str, payload: dict):
    entry = {
        "action_type": action_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role or "",
        "actor_id": actor_id or "",
        "payload": payload or {},
    }
    # AuditLogEntry: append-only (no version / updated_at)
    entry["id"] = store.new_id()
    entry["created_at"] = store.now_iso()
    store.audit_log[entry["id"]] = entry
    return entry
