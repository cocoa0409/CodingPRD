"""AuditEvent writer (PRD §3.8).

An AuditEvent is an immutable event-log record carrying only id + created_at
(no updated_at, no version). It records the application_id it concerns, the
acting actor_user_id / actor_role (from the request context), a machine event
type, and a human-readable detail.
"""
from __future__ import annotations

import db
from middleware import current_role, current_user_id
from routes._helpers import stamp_create


def write_audit(application_id: str, event_type: str, detail: str) -> dict:
    record = {
        "application_id": application_id,
        "actor_user_id": current_user_id(),
        "actor_role": current_role(),
        "event_type": event_type,
        "detail": detail,
    }
    stamp_create(record, full=False)
    db.audit_events[record["id"]] = record
    return record
