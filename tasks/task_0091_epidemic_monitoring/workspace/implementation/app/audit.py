"""Audit-log append helpers. PRD §2.10."""
from __future__ import annotations

from typing import Any

from .auth import current_actor
from .clock import now_iso_ms
from .store import common_fields_append_only, get_store


def append_audit(
    entity_type: str,
    entity_id: str,
    from_state: str | None,
    to_state: str,
    actor_role: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Append a row to the AuditLog. Row is append-only (no version, no updated_at)."""
    store = get_store()
    if actor_role is None or actor_id is None:
        a_id, a_role = current_actor()
        if actor_role is None:
            actor_role = a_role or "system"
        if actor_id is None:
            actor_id = a_id or "system"
    base = common_fields_append_only()
    row = {
        **base,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "from_state": from_state if from_state is not None else "",
        "to_state": to_state,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "at": now_iso_ms(),
    }
    store.audit_logs[row["id"]] = row
    return row
