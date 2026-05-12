"""Audit event service."""
import db
from clock import iso, now


def record(subject_type: str, subject_id: str, actor_role: str, actor_user_id: str,
           action: str, from_state, to_state, payload_json: dict) -> dict:
    ev = {
        "id": db.gen_id(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "action": action,
        "from_state": from_state,
        "to_state": to_state,
        "payload_json": payload_json or {},
        "created_at": iso(now()),
        "_seq": db.next_seq(),
    }
    db.audit_events[ev["id"]] = ev
    return ev
