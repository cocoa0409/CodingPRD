"""Audit event helpers."""
from clock import format_iso, get_now
from db import db, new_id


def emit_audit(action_kind: str, actor_kind: str, actor_id: str,
               subject_kind: str, subject_id: str, payload: dict = None):
    """Append an AuditEvent row. AuditEvent has id and created_at only — append-only."""
    now = format_iso(get_now())
    ev = {
        "id": new_id(),
        "created_at": now,
        "occurred_at": now,
        "action_kind": action_kind,
        "actor_kind": actor_kind,
        "actor_id": actor_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "payload": payload or {},
    }
    db.audit_events[ev["id"]] = ev
    return ev


def actor_kind_for_role(role: str) -> str:
    mapping = {
        "Client": "CLIENT",
        "Designer": "DESIGNER",
        "Reviewer": "REVIEWER",
        "PlatformOps": "PLATFORM",
    }
    return mapping.get(role, "SYSTEM")
