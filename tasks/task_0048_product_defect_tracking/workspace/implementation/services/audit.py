"""Audit entry append helpers."""

from __future__ import annotations

import db


def append_audit(*, defect_id, event_type, actor_id, from_value=None, to_value=None,
                 at_minute: int, external_payload=None):
    return db.insert("audit_entries", {
        "defect_id": defect_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "from_value": from_value,
        "to_value": to_value,
        "at_minute": at_minute,
        "external_payload": external_payload,
    })
