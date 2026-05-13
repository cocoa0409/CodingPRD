"""Audit log writer — emits an AuditLog row per state-changing action."""

from __future__ import annotations

from copy import deepcopy

import db


def log(*,
        subject_kind: str,
        subject_id: str,
        action: str,
        actor_role: str | None,
        actor_id: str | None,
        from_state: str | None = None,
        to_state: str | None = None,
        payload_snapshot: dict | None = None) -> dict:
    payload = {
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "action": action,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "from_state": from_state,
        "to_state": to_state,
        "payload_snapshot": deepcopy(payload_snapshot) if payload_snapshot else {},
    }
    return db.create_entity("audit_logs", payload)
