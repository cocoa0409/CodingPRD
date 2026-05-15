"""Audit log helpers — only MATCH_INCIDENT and TRANSFER_OFFER domains are logged."""
from __future__ import annotations

from typing import Any

from .store import common_fields_append_only, get_store


def log_event(
    subject_type: str,
    subject_id: str,
    actor_user_id: str,
    actor_role: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = get_store()
    row = common_fields_append_only()
    row.update(
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "action": action,
            "payload": payload or {},
        }
    )
    store.audit_logs[row["id"]] = row
    return row
