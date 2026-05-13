"""Audit log helpers."""
from flask import g, has_request_context

import db
from clock import iso, now


VALID_EVENT_TYPES = {
    "LOAN_CREATED", "LOAN_RENEWED", "LOAN_RECALLED", "LOAN_RETURNED",
    "FINE_ACCRUED", "FINE_WAIVED", "FINE_PAID",
    "RESERVATION_CREATED", "RESERVATION_FULFILLED",
}


def append(event_type: str, subject_type: str, subject_id: str,
           payload: dict, *, actor_role: str = None, actor_id: str = None):
    """Append an immutable AuditLog entry."""
    # Resolve actor from request context if not explicitly provided.
    if actor_role is None and actor_id is None and has_request_context():
        actor_role = getattr(g, "user_role", None)
        actor_id = getattr(g, "user_id", None)
    if actor_role == "System":
        actor_id = None

    entry = {
        "id": db.gen_id(),
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload": payload or {},
        "occurred_at": iso(now()),
        "created_at": iso(now()),
        "_seq": db.next_seq(),
    }
    db.audit_logs[entry["id"]] = entry
    return entry
