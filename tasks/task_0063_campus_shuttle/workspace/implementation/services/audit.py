"""Audit log append helper per PRD §2.11."""
from __future__ import annotations

import db


def append_audit(event_type: str, subject_type: str, subject_id: str,
                 actor_role: str, actor_id: str, payload: dict | None = None) -> dict:
    """Append an AuditLog row. Returns the created entry."""
    entry = {
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload": payload or {},
    }
    db.stamp_create(entry, common_fields=False)
    db.audit_logs[entry["id"]] = entry
    return entry
