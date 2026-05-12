"""AuditLog append helper."""

from db import db, new_id
from clock import now_iso


def append_audit(actor_role, actor_id, action, target_entity, target_id, payload_snapshot=None):
    log_id = new_id()
    row = {
        "id": log_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload_snapshot": payload_snapshot or {},
        "created_at": now_iso(),
    }
    db.audit_logs[log_id] = row
    return row
