"""Audit log writes."""
import copy

from db import store, new_id, now_iso


def write_audit(actor_user_id: str, actor_role: str, subject_entity_type: str,
                subject_entity_id: str, action: str, payload_snapshot: dict):
    entry = {
        "id": new_id(),
        "created_at": now_iso(),
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "subject_entity_type": subject_entity_type,
        "subject_entity_id": subject_entity_id,
        "action": action,
        "payload_snapshot": copy.deepcopy(payload_snapshot or {}),
    }
    store.audit_log.append(entry)
    return entry
