"""Append-only audit trail. AuditEvent carries id, created_at and a global
sequence_no starting at 1 — no updated_at and no version (PRD 2.5)."""
from flask import g

from db import db
from util import new_id

EVENT_TYPES = (
    "LICENSE_STATUS_CHANGED",
    "SPONSORSHIP_CHANGED",
    "CE_CREDIT_VOIDED",
    "PLAN_APPROVED",
    "PLAN_REJECTED",
    "PROHIBITED_VARIABLE_BLOCKED",
    "APPLICATION_TAKEN",
    "EXCEPTION_DECIDED",
    "COMP_ACCRUED",
    "COMP_RECONCILED",
    "COMP_CLAWED_BACK",
    "AD_DECIDED",
    "INVESTIGATION_OPENED",
    "INVESTIGATION_FINDING",
    "MONITORING_ESCALATED",
)


def append(subject_type, subject_ref, event_type, detail, system=False):
    if system:
        actor_role = "SYSTEM"
        actor_user_id = None
    else:
        actor_role = getattr(g, "role", "SYSTEM")
        actor_user_id = getattr(g, "user_id", None)
        if actor_role == "SYSTEM":
            actor_user_id = None
    row = {
        "id": new_id(),
        "subject_type": subject_type,
        "subject_ref": subject_ref,
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "detail": detail if isinstance(detail, dict) else {},
        "sequence_no": db.next_audit_seq(),
        "created_at": db.clock,
        "_seq": db.next_insert_seq(),
    }
    db.audit_events[row["id"]] = row
    return row
