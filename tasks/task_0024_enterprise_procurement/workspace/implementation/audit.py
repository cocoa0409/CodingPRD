"""Audit-log helper. Per PRD §2.11 only approval-chain decisions and contract
lifecycle events are audited (not requirement creation, quote creation, etc.).
"""

from __future__ import annotations

from db import db, new_id, stamp_create
from middleware import current_actor


def append_audit(
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict | None = None,
) -> dict:
    user_id, user_role = current_actor()
    row = {
        "actor_user_id": user_id,
        "actor_role": user_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload or {},
    }
    stamp_create(row, common=False)  # only id + created_at
    db.audit_log.append(row)
    return row
