"""Audit log helper (PRD §2.9)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.store import store
from app.utils import logical_now_iso, new_id


def append_audit(
    *,
    actor_role: str,
    actor_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry = {
        "id": new_id(),
        "created_at": logical_now_iso(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": event_type,
        "before": before or {},
        "after": after or {},
        "ts": logical_now_iso(),
    }
    store.audit_logs.append(entry)
    return entry
