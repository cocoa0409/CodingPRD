"""Append-only compliance trail (PRD section 2.11)."""

from db import db, make_row, now

SYSTEM_ACTOR = ("System", "system")


def append_event(prescription_id, event_type, subject_type, subject_id, actor, detail=None):
    actor_role, actor_user_id = actor
    row = make_row(
        {
            "prescription_id": prescription_id,
            "event_type": event_type,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "actor_role": actor_role,
            "actor_user_id": actor_user_id,
            "detail": detail,
            "occurred_at": now(),
        },
        common=False,
    )
    row["created_at"] = now()
    db.compliance_events[row["id"]] = row
    return row
