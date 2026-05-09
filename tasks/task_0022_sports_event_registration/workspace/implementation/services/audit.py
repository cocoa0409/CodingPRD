"""Audit log writing."""
import db


def write_audit(*, kind: str, subject_kind: str, subject_id: str,
                actor_user_id: str, actor_role: str,
                from_value: dict, to_value: dict) -> dict:
    row = {
        "id": db.gen_id(),
        "kind": kind,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "from_value": from_value,
        "to_value": to_value,
    }
    db.stamp_create(row, common_fields=False)
    db.audit_logs[row["id"]] = row
    return row
