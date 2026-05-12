"""Audit log helpers (append-only events)."""
from db import audit_logs, gen_id, next_seq
from clock import now, iso


def emit(event_type: str, actor_role: str, actor_id: str,
         subject_entity: str, subject_id: str, payload: dict) -> dict:
    """Append a new audit log entry. Returns the row."""
    ts = iso(now())
    row = {
        "id": gen_id(),
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "payload": payload or {},
        "occurred_at": ts,
        "created_at": ts,
        "_seq": next_seq(),
    }
    audit_logs[row["id"]] = row
    return row
