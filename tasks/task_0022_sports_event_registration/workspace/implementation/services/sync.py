"""Outbox SyncEvent emission."""
import db
from clock import now, iso


def emit(*, target_system: str, kind: str, payload: dict) -> dict:
    row = {
        "id": db.gen_id(),
        "target_system": target_system,
        "kind": kind,
        "payload": payload,
        "emitted_at": iso(now()),
    }
    db.stamp_create(row, common_fields=False)
    db.sync_events[row["id"]] = row
    return row
