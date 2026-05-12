"""AuditEntry creation."""
from flask import request

from db import db, new_id


def append_audit(site_id, action, target_id, from_value, to_value):
    role = request.headers.get("X-User-Role", "")
    user_id = request.headers.get("X-User-ID", "")
    clock = db.site_clock(site_id)
    entry = {
        "id": new_id(),
        "created_at": clock,
        "site_id": site_id,
        "actor_role": role,
        "actor_user_id": user_id,
        "action": action,
        "target_id": target_id,
        "from_value": from_value if from_value is not None else "",
        "to_value": to_value if to_value is not None else "",
        "occurred_at": clock,
    }
    db.audit_entries.append(entry)
    return entry
