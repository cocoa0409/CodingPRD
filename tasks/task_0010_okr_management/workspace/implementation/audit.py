"""Audit-log writer."""

from flask import g

import db
from clock import now, format_ts
from util import gen_id, actor_id, actor_role


def write_audit(*, entity_type: str, entity_id: str, action: str,
                before=None, after=None, actor_override=None, role_override=None):
    """Append an AuditLog row.

    actor_override/role_override are used for cascaded SYSTEM-initiated changes.
    """
    rid = getattr(g, "api_request_id", None)
    log = {
        "id": gen_id(),
        "created_at": format_ts(now()),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_user_id": actor_override or actor_id() or "SYSTEM",
        "actor_role": role_override or actor_role() or "SYSTEM",
        "before_value": before,
        "after_value": after,
        "api_request_id": rid,
    }
    db.audit_logs[log["id"]] = log
    return log
