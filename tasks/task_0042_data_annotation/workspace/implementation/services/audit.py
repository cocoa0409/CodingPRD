"""Audit log + ExternalEvent helpers."""

from flask import g, has_request_context

import db


def _actor_id_role(system: bool):
    if system or not has_request_context():
        return "system", "system"
    return getattr(g, "user_id", "system"), getattr(g, "role", "system")


def write_audit(
    *,
    subject_kind: str,
    subject_id: str,
    event_type: str,
    from_value,
    to_value,
    system: bool = False,
):
    actor_id, actor_role = _actor_id_role(system)
    return db.insert(
        "audit_logs",
        {
            "actor_id": actor_id,
            "actor_role": actor_role,
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "event_type": event_type,
            "from_value": None if from_value is None else str(from_value),
            "to_value": None if to_value is None else str(to_value),
        },
        with_version=False,
    )


def queue_event(target_system: str, event_type: str, payload_ref_id: str):
    return db.insert(
        "external_events",
        {
            "target_system": target_system,
            "event_type": event_type,
            "payload_ref_id": payload_ref_id,
            "dispatch_status": "PENDING",
        },
        with_version=False,
    )
