"""Audit-event helpers.

AuditEvent rows are stored append-only in DB['audit_events']. Each row carries
created_at, event_type, subject_type, subject_id, actor_role, actor_id, payload.
"""

from db import DB, new_id
from services.time_util import now_iso


def emit_audit(event_type, subject_type, subject_id, actor_role, actor_id, payload=None):
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role or "system",
        "actor_id": actor_id or "system",
        "payload": payload or {},
    }
    DB["audit_events"].append(row)
    return row
