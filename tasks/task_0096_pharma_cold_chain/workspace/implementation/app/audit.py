"""Audit log + external sync event writers (append-only)."""
from __future__ import annotations

from typing import Any

from .auth import current_actor
from .store import common_fields_append_only, get_store


def write_audit(
    warehouse_id: str,
    action: str,
    target_id: str,
    at_minutes: int,
) -> dict[str, Any]:
    """Append an AuditLogEntry row (PRD §2.13).

    Returns the new entry.
    """
    actor_user_id, actor_role = current_actor()
    row = common_fields_append_only()
    row.update(
        {
            "warehouse_id": warehouse_id,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "action": action,
            "target_id": target_id,
            "at_minutes": at_minutes,
        }
    )
    get_store().audit_entries[row["id"]] = row
    return row


def emit_sync_event(
    warehouse_id: str,
    target_system: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Append an ExternalSyncEvent row."""
    row = common_fields_append_only()
    row.update(
        {
            "warehouse_id": warehouse_id,
            "target_system": target_system,
            "event_type": event_type,
            "payload": payload,
        }
    )
    get_store().external_events[row["id"]] = row
    return row
