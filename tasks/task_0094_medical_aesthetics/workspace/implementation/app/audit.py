"""Audit log + SyncEvent emission helpers."""
from __future__ import annotations

from typing import Any

from .auth import current_actor
from .store import get_store, common_fields_append_only


def write_audit(action: str, subject_type: str, subject_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    actor_id, actor_role = current_actor()
    entry = common_fields_append_only()
    entry.update(
        {
            "actor_role": actor_role,
            "actor_id": actor_id,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload or {},
        }
    )
    get_store().audit_entries[entry["id"]] = entry
    return entry


def emit_sync_event(topic: str, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    evt = common_fields_append_only()
    # SyncEvent has emitted_at per scaffold; created_at is also kept (server timestamp)
    evt.update(
        {
            "topic": topic,
            "kind": kind,
            "payload": payload or {},
            "emitted_at": evt["created_at"],
        }
    )
    get_store().sync_events[evt["id"]] = evt
    return evt


def write_payment_event(installment_plan_id: str, kind: str, amount_cents: int, external_ref: str | None = None) -> dict[str, Any]:
    evt = common_fields_append_only()
    evt.update(
        {
            "installment_plan_id": installment_plan_id,
            "kind": kind,
            "amount_cents": amount_cents,
            "external_ref": external_ref or "",
            "recorded_at": evt["created_at"],
        }
    )
    get_store().payment_events[evt["id"]] = evt
    return evt
