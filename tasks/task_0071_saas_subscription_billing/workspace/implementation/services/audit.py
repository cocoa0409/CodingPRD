"""Audit log and sync event emission helpers."""
from flask import g

from db import store, new_id, now_iso


def write_audit(tenant_id: str, action: str, target_entity_type: str,
                target_entity_id: str, before, after):
    log_id = new_id()
    entry = {
        "id": log_id,
        "created_at": now_iso(),
        "tenant_id": tenant_id,
        "actor_role": getattr(g, "actor_role", None),
        "actor_id": getattr(g, "actor_id", None),
        "action": action,
        "target_entity_type": target_entity_type,
        "target_entity_id": target_entity_id,
        "before_snapshot": before if before is not None else {},
        "after_snapshot": after if after is not None else {},
    }
    store.audit_logs[log_id] = entry
    return entry


def emit_sync_event(tenant_id: str, target_system: str, event_type: str, payload):
    ev_id = new_id()
    ev = {
        "id": ev_id,
        "created_at": now_iso(),
        "tenant_id": tenant_id,
        "target_system": target_system,
        "event_type": event_type,
        "payload": payload if payload is not None else {},
        "delivery_status": "DELIVERED",
    }
    store.sync_events[ev_id] = ev
    return ev
