"""Append-only federal audit trail.

Every mutation appends AuditEvent rows attributed to the triggering call's
role and id (never a synthetic system actor). before_json/after_json are JSON
snapshots of the mutated row's public representation.
"""

import json

from flask import g

from db import _new_id, now, store


def record(action, entity_type, entity_id, student_id, before_pub, after_pub):
    row = {
        "id": _new_id(),
        "created_at": now(),
        "actor_role": getattr(g, "user_role", None),
        "actor_id": getattr(g, "user_id", None),
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "student_id": student_id,
        "before_json": json.dumps(before_pub) if before_pub is not None else None,
        "after_json": json.dumps(after_pub) if after_pub is not None else None,
        "occurred_at": now(),
        "_seq": store.next_seq(),
    }
    store.audit_events[row["id"]] = row
    return row
