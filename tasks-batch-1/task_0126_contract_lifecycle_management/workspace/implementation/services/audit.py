"""Audit event helper (PRD §3.8).

AuditEvent is a write-once record: id + created_at only (no updated_at, no
version) per PRD §2.4.
"""

from db import db, new_id
from util import format_iso_millis


def append_audit(contract_id, event_type, actor_user_id=None, detail=None):
    event = {
        "id": new_id(),
        "contract_id": contract_id,
        "event_type": event_type,
        "actor_user_id": actor_user_id,
        "detail": detail,
        "created_at": format_iso_millis(db.clock),
    }
    db.audit_events[event["id"]] = event
    return event
