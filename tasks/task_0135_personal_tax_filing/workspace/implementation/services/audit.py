"""AuditLog append helper (PRD §2.11)."""
from __future__ import annotations

from db import store
from utils import iso_now, new_uuid


def append_audit(
    actor_role: str,
    actor_id: str,
    action: str,
    target_entity: str,
    target_id: str,
    payload: dict | None = None,
) -> dict:
    """Append a read-only audit log row. Caller must hold store.lock."""
    now = store.now()
    entry = {
        "id": new_uuid(),
        "created_at": iso_now(now),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload": payload or {},
    }
    store.audit_logs.append(entry)
    return entry
