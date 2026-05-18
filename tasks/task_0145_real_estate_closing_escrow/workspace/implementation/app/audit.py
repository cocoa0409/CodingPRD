"""Append-only AuditEvent helpers."""
from __future__ import annotations

from typing import Any

from app import store
from app.util import canonical_payload_hash, new_uuid, now_ts


def append_audit(
    *,
    escrow_file_id: str,
    subject_kind: str,
    subject_id: str,
    actor_user_id: str,
    actor_role: str,
    action: str,
    payload_body: Any = None,
    payload_hash: str | None = None,
) -> None:
    ev_id = new_uuid()
    ev = {
        "id": ev_id,
        "escrow_file_id": escrow_file_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "payload_hash": payload_hash if payload_hash is not None else canonical_payload_hash(payload_body),
        "created_at": now_ts(),
    }
    store.audit_events[ev_id] = ev
