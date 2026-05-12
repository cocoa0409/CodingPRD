"""Audit log helpers — every audited mutation appends one row here.

Subject types per PRD §2.10: DOCUMENT_DRAFT, EVIDENCE, CUSTODY_EVENT.
"""

from flask import g

import clock
import db


def append(*, subject_type, subject_id, action, payload_snapshot=None):
    actor_role = getattr(g, "user_role", None) or "system"
    actor_id = getattr(g, "user_id", None) or "system"

    now = clock.now()
    entry = {
        "id": db.new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "payload_snapshot": payload_snapshot if payload_snapshot is not None else {},
        "occurred_at": now,
        "created_at": now,
    }
    db.audit_logs.append(entry)
    return entry


def append_system(*, subject_type, subject_id, action, payload_snapshot=None):
    """Append an audit row attributed to the system actor (no Flask request context)."""
    now = clock.now()
    entry = {
        "id": db.new_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": "system",
        "actor_id": "system",
        "action": action,
        "payload_snapshot": payload_snapshot if payload_snapshot is not None else {},
        "occurred_at": now,
        "created_at": now,
    }
    db.audit_logs.append(entry)
    return entry
