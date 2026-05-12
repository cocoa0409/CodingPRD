"""Audit and external-sync event emission helpers (per PRD §2.8)."""
from flask import g, has_request_context

import db


def emit_audit(event_type: str, target_entity: str, target_id: str,
               payload: dict, actor_role: str = None, actor_id: str = None) -> dict:
    if actor_role is None:
        actor_role = getattr(g, "user_role", "system") if has_request_context() else "system"
    if actor_id is None:
        actor_id = getattr(g, "user_id", "system") if has_request_context() else "system"
    evt = {
        "event_type": event_type,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload": payload,
    }
    db.stamp_create(evt, common_fields=False)
    db.audit_events[evt["id"]] = evt
    return evt


def emit_external_sync(kind: str, scholarship_id: str,
                       application_id=None, payload=None) -> dict:
    evt = {
        "kind": kind,
        "application_id": application_id,
        "scholarship_id": scholarship_id,
        "payload": payload if payload is not None else {},
    }
    db.stamp_create(evt, common_fields=False)
    db.external_sync_events[evt["id"]] = evt
    return evt
