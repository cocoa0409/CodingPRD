"""The immutable audit trail of PRD section 2.11.

Every POST endpoint appends exactly one AuditEntry, successful or refused.
Cascaded side effects never add entries of their own.
"""

from flask import g, request

from . import constants as K
from .store import db, new_row


def audit_slot():
    slot = getattr(g, "audit_slot", None)
    if slot is None:
        slot = {
            "subject_entity": "System",
            "subject_id": None,
            "client_id": None,
        }
        g.audit_slot = slot
    return slot


def set_subject(subject_id):
    audit_slot()["subject_id"] = subject_id


def set_client(client_id):
    audit_slot()["client_id"] = client_id


def set_subject_entity(entity):
    audit_slot()["subject_entity"] = entity


def append_audit(outcome, error_id):
    slot = audit_slot()
    subject_entity = slot["subject_entity"]
    new_row(
        "audit_entries",
        {
            "client_id": slot["client_id"],
            "actor_role": request.headers.get("X-User-Role"),
            "actor_user_id": request.headers.get("X-User-ID"),
            "operation": "{} {}".format(request.method, request.path),
            "subject_entity": subject_entity,
            "subject_id": slot["subject_id"],
            "outcome": outcome,
            "error_id": error_id,
            "disclosure_category": K.DISCLOSURE_CATEGORY_BY_SUBJECT[subject_entity],
            "recorded_at": db.now,
        },
        versioned=False,
    )
