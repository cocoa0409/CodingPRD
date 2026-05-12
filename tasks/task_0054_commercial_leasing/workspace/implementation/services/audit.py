"""Audit event recording."""
from clock import now, iso
import db


def record(*, subject_kind: str, subject_id: str, action: str,
           actor_role: str, actor_id: str, payload: dict) -> dict:
    ev = {
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload": payload,
        "occurred_at": iso(now()),
    }
    db.stamp_create(ev, common_fields=False)
    db.audit_events[ev["id"]] = ev
    return ev
