"""AuditLog append-only writer."""

from db import db
from util import new_id


def append_audit(
    actor_role: str,
    actor_user_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    prior_state=None,
    new_state=None,
):
    row = {
        "id": new_id(),
        "created_at": db.current_utc_iso(),
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "prior_state": prior_state,
        "new_state": new_state,
    }
    db.audit_logs.append(row)
    return row
