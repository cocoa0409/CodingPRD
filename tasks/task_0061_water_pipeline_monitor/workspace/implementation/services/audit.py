"""Audit log + sync event writers (PRD §2.9)."""
from clock import iso, server_now
from db import audit_logs, gen_id, next_seq, next_sync_seq, sync_events


def write_audit(
    *,
    network_id: str,
    actor_role: str,
    actor_id: str,
    action: str,
    resource_kind: str,
    resource_id: str,
    detail: dict,
) -> dict:
    row = {
        "id": gen_id(),
        "network_id": network_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "detail": detail or {},
        "recorded_at": iso(server_now()),
        "created_at": iso(server_now()),
        "_seq": next_seq(),
    }
    audit_logs[row["id"]] = row
    return row


def emit_sync(
    *,
    network_id: str,
    target_system: str,
    event_type: str,
    resource_kind: str,
    resource_id: str,
    payload: dict,
) -> dict:
    row = {
        "id": gen_id(),
        "network_id": network_id,
        "target_system": target_system,
        "event_type": event_type,
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "payload": payload or {},
        "emitted_at": iso(server_now()),
        "sequence_no": next_sync_seq(network_id, target_system),
        "created_at": iso(server_now()),
        "_seq": next_seq(),
    }
    sync_events[row["id"]] = row
    return row
