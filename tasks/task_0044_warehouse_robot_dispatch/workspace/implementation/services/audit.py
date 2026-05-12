"""Audit event helpers."""
from __future__ import annotations

from db import db, new_id


def write_audit(fleet: dict, event_kind: str, subject_kind: str, subject_id: str,
                from_state, to_state, actor_role: str):
    ev_id = new_id()
    now = fleet["clock_now"]
    ev = {
        "id": ev_id,
        "created_at": now,
        "fleet_id": fleet["id"],
        "event_kind": event_kind,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "from_state": from_state,
        "to_state": to_state,
        "actor_role": actor_role,
        "occurred_at": now,
    }
    db.audit_events[ev_id] = ev
    return ev
