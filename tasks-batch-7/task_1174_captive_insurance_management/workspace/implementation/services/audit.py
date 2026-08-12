"""Append-only audit log writer (PRD 2.6)."""
from __future__ import annotations

import uuid

import db
from clock import now_iso


def log(captive_id, action_type, entity_type, entity_id, actor_role, actor_id,
        action_description, previous_state, new_state):
    entry = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "captive_id": captive_id,
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action_description": action_description,
        "previous_state": previous_state,
        "new_state": new_state,
        "timestamp": now_iso(),
    }
    db.audit_logs[entry["id"]] = entry
    return entry
