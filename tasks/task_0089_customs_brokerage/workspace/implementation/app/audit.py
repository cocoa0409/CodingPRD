"""AuditLog helpers (PRD §2.8)."""
from __future__ import annotations

from typing import Any, Optional

from .store import common_fields_append_only, get_store


def emit_audit(
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor_role: str,
    actor_id: str,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create an AuditLog row. Append-only — never mutated."""
    store = get_store()
    row = common_fields_append_only()
    row.update(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "payload": payload or {},
        }
    )
    store.audit_log[row["id"]] = row
    return row
