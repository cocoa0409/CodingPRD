"""Audit log helpers."""
from flask import g

import db


def write_audit(*, action: str, subject_kind: str, subject_id: str,
                before: dict, after: dict, reason: str) -> dict:
    """Append an AuditLog row using the current request's actor info."""
    log = {
        "actor_role": getattr(g, "user_role", None),
        "actor_id": getattr(g, "user_id", None),
        "action": action,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "before": before or {},
        "after": after or {},
        "reason": reason,
    }
    db.stamp_create(log, common_fields=False)
    db.audit_logs[log["id"]] = log
    return log
