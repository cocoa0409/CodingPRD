"""AuditLog and ApprovalRecord helpers."""

from __future__ import annotations

from db import STORE
from utils import CLOCK, new_uuid


def write_audit_log(*, event_type: str, subject_type: str, subject_id: str,
                    actor_id: str | None = None, payload: dict | None = None) -> dict:
    """Insert an AuditLog row and return it.

    AuditLog is write-once: only id + created_at.
    """
    row = {
        "id": new_uuid(),
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_id": actor_id if actor_id is not None else "system",
        "payload": payload or {},
        "created_at": CLOCK.now_iso(),
    }
    STORE.audit_logs[row["id"]] = row
    return row


def write_approval_record(*, subject_type: str, subject_id: str, actor_id: str,
                          actor_role: str, action: str, comment: str | None,
                          from_status: str, to_status: str) -> dict:
    """Insert an ApprovalRecord row and return it."""
    row = {
        "id": new_uuid(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action": action,
        "comment": comment,
        "from_status": from_status,
        "to_status": to_status,
        "created_at": CLOCK.now_iso(),
    }
    STORE.approval_records[row["id"]] = row
    # Also emit a corresponding APPROVAL_ACTION audit-log entry
    write_audit_log(
        event_type="APPROVAL_ACTION",
        subject_type=subject_type,
        subject_id=subject_id,
        actor_id=actor_id,
        payload={
            "actor_role": actor_role,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "comment": comment,
        },
    )
    return row


def emit_external_sync(*, subject_type: str, subject_id: str, target: str,
                       event: str, actor_id: str | None = None,
                       extra_payload: dict | None = None) -> dict:
    payload = {"target": target, "event": event}
    if extra_payload:
        payload.update(extra_payload)
    return write_audit_log(
        event_type="EXTERNAL_SYNC",
        subject_type=subject_type,
        subject_id=subject_id,
        actor_id=actor_id,
        payload=payload,
    )
