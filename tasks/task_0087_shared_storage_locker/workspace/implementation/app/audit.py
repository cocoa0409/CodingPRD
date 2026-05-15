"""AuditEvent helpers (PRD §2.12)."""
from __future__ import annotations

from typing import Any, Optional

from .clock import now_iso_ms
from .store import common_fields_append_only, get_store


def emit_audit_event(
    event_kind: str,
    subject_type: str,
    subject_id: str,
    actor_role: str,
    actor_id: str,
    unlock_channel: Optional[str],
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create an AuditEvent. Append-only — never mutated."""
    store = get_store()
    row = common_fields_append_only()
    row.update(
        {
            "event_kind": event_kind,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "unlock_channel": unlock_channel,
            "detail": detail or {},
            "occurred_at": now_iso_ms(),
        }
    )
    store.audit_events[row["id"]] = row
    return row
