"""Append-only audit trail helper."""
from __future__ import annotations

from typing import Optional

from .clock import format_datetime_ms, get_clock
from .store import get_store, new_id


def append_audit(
    *,
    subject_employee_id: str,
    subject_entity: str,
    subject_entity_id: str,
    action: str,
    actor_role: str,
    actor_user_id: Optional[str],
) -> dict:
    store = get_store()
    clock = get_clock()
    seq = store.next_seq()
    now = clock.get()
    row = {
        "id": new_id(),
        "subject_employee_id": subject_employee_id,
        "subject_entity": subject_entity,
        "subject_entity_id": subject_entity_id,
        "action": action,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "occurred_at": format_datetime_ms(now),
        "created_at": format_datetime_ms(now),
        "_seq": seq,
    }
    store.audit_events[row["id"]] = row
    return row
