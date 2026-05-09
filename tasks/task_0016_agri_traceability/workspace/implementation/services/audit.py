"""Audit log writer."""

from flask import g

from common import stamp_create_immutable
from db import db


def record_audit(
    entity_type: str,
    entity_id: str,
    action: str,
    after_state: str,
    before_state=None,
    change_summary=None,
    actor_user_id=None,
    actor_role=None,
):
    """Append an AuditLog row.

    Per scaffold: actor_user_id/actor_role come from the request unless explicitly
    supplied (system-driven cascades use 'system' role).
    """
    if actor_user_id is None:
        actor_user_id = getattr(g, "user_id", "system")
    if actor_role is None:
        actor_role = getattr(g, "user_role", "system")
    log = {
        "id": db.new_id(),
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "before_state": before_state,
        "after_state": after_state,
        "change_summary": change_summary or {},
    }
    stamp_create_immutable(log)
    db.audit_logs.append(log)
    return log
