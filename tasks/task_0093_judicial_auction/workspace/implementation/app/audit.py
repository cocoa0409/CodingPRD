"""Audit-event emission helpers — PRD §2.10."""
from __future__ import annotations

from typing import Any

from .auth import current_actor
from .store import common_fields_append_only, get_store


def emit_audit(
    kind: str,
    subject_entity: str,
    subject_id: str,
    payload: dict[str, Any] | None = None,
    actor_role: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    store = get_store()
    cf = common_fields_append_only()

    if actor_role is None or actor_id is None:
        uid, urole = current_actor()
        if actor_role is None:
            actor_role = urole or "system"
        if actor_id is None:
            actor_id = uid or "system"

    event = {
        **cf,
        "kind": kind,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "payload": payload or {},
    }
    store.audit_events[event["id"]] = event
    return event


def emit_system_audit(
    kind: str,
    subject_entity: str,
    subject_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return emit_audit(
        kind=kind,
        subject_entity=subject_entity,
        subject_id=subject_id,
        payload=payload,
        actor_role="system",
        actor_id="system",
    )
