"""Append-only audit trail."""

import uuid

import db
from clock import CLOCK, format_iso


def append(plan_id, actor_role, actor_id, action, subject_type, subject_id, detail=None):
    evt = {
        "id": str(uuid.uuid4()),
        "created_at": format_iso(CLOCK.now()),
        "plan_id": plan_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "detail": detail if detail is not None else {},
    }
    db.audit_events[evt["id"]] = evt
    return evt
