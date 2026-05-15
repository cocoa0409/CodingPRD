"""Audit log helpers."""

from flask import g

from db import DB, new_id
from services.common import init_append_only, now_iso


def append_audit(event_type: str, entity_type: str, entity_id: str,
                 from_value, to_value) -> dict:
    actor_role = getattr(g, "user_role", None)
    actor_id = getattr(g, "user_id", None)
    row = {
        "id": new_id(),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "from_value": None if from_value is None else str(from_value),
        "to_value": None if to_value is None else str(to_value),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "occurred_at": now_iso(),
    }
    init_append_only(row)
    DB["audit_logs"][row["id"]] = row
    return row
