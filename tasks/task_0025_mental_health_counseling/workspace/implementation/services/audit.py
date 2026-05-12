"""Audit log helpers."""
import db


def append(*, actor_role: str, actor_user_id, action: str,
           target_entity: str, target_id, payload_summary=None):
    entry = {
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload_summary": payload_summary or {},
    }
    db.stamp_create(entry, common_fields=False)
    db.audit_log[entry["id"]] = entry
    return entry
