"""Audit log append-only writes."""

import db
from clock import now_iso


def write(actor_role: str, actor_id: str, entity_kind: str, entity_id: str,
          event_kind: str, payload: dict) -> dict:
    record = {
        "actor_role": actor_role,
        "actor_id": actor_id,
        "entity_kind": entity_kind,
        "entity_id": entity_id,
        "event_kind": event_kind,
        "payload": payload,
        "occurred_at": now_iso(),
    }
    db.append_only_record(record)
    db.audit_logs[record["id"]] = record
    return record
