"""AuditLog append-only event logging."""

from clock import clock
from db import db


def append_log(subject_type: str, subject_id: str, action: str,
               actor_role: str, actor_id: str,
               before_snapshot: dict, after_snapshot: dict):
    log_id = db.new_id()
    occurred_at = clock.now_iso()
    entry = {
        "id": log_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "before_snapshot": before_snapshot or {},
        "after_snapshot": after_snapshot or {},
        "occurred_at": occurred_at,
        "created_at": occurred_at,
    }
    db.audit_logs.append(entry)
    return entry


def serialize_log(entry):
    return {
        "id": entry["id"],
        "subject_type": entry["subject_type"],
        "subject_id": entry["subject_id"],
        "action": entry["action"],
        "actor_role": entry["actor_role"],
        "actor_id": entry["actor_id"],
        "before_snapshot": entry.get("before_snapshot") or {},
        "after_snapshot": entry.get("after_snapshot") or {},
        "occurred_at": entry["occurred_at"],
        "created_at": entry["created_at"],
    }
