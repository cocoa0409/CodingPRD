"""AuditLogEntry append helpers per PRD §2.9."""
from __future__ import annotations

import db


def append_audit(*, subject_type: str, subject_id: str, actor_role: str,
                 actor_id: str, action_code: str, delta: dict | None = None) -> dict:
    row = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action_code": action_code,
        "delta": delta if delta is not None else {},
    }
    db.stamp_create(row, common_fields=False)
    db.audit_logs[row["id"]] = row
    return row
