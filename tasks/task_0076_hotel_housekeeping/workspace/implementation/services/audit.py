"""Append-only RoomStatusEvent and AuditLog writers."""

from flask import g, has_request_context

from db import DB
from services.common import stamp_subordinate


VALID_CHANGE_REASONS = {
    "PMS_SYNC", "TASK_COMPLETED", "INSPECTION_PASS",
    "MAINTENANCE_ISOLATE", "MAINTENANCE_VERIFY",
    "MANUAL_CORRECTION", "INITIAL",
}


VALID_ACTION_TYPES = {
    "ROOM_STATUS_CHANGE",
    "MINIBAR_CONSUMPTION_POST",
    "MINIBAR_CONSUMPTION_DISPUTE",
    "MINIBAR_CONSUMPTION_WAIVE",
    "MANUAL_CORRECTION",
    "EVENT_INGESTED",
}


def actor_id_from_request(default="system"):
    if has_request_context():
        try:
            return getattr(g, "user_id", default)
        except RuntimeError:
            return default
    return default


def actor_role_from_request():
    if has_request_context():
        try:
            return getattr(g, "user_role", None)
        except RuntimeError:
            return None
    return None


def append_room_status_event(*, room_id, previous_status, new_status,
                              change_reason, actor_id,
                              correction_note=None):
    evt = {
        "room_id": room_id,
        "previous_status": previous_status,
        "new_status": new_status,
        "change_reason": change_reason,
        "actor_id": actor_id,
        "correction_note": correction_note,
    }
    stamp_subordinate(evt)
    DB["room_status_events"][evt["id"]] = evt
    return evt


def append_audit(*, actor_id=None, actor_role=None,
                 action_type, subject_entity, subject_id, detail=None):
    if actor_id is None:
        actor_id = actor_id_from_request("system")
    if actor_role is None:
        actor_role = actor_role_from_request()
    entry = {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action_type": action_type,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "detail": detail or {},
    }
    stamp_subordinate(entry)
    DB["audit_logs"][entry["id"]] = entry
    return entry
