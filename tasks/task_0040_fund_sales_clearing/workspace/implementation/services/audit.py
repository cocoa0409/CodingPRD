"""AuditLog writer."""
import db
from db import audit_logs, stamp_create


def write(actor_user_id: str, actor_role: str, action: str, subject_entity: str,
          subject_id: str, from_state, to_state, payload_json: dict = None):
    row = {
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "from_state": from_state,
        "to_state": to_state,
        "payload_json": payload_json or {},
    }
    stamp_create(row, common_fields=False)
    audit_logs[row["id"]] = row
    return row
