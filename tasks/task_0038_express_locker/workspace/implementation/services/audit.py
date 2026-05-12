"""AuditLog and CompartmentEvent helpers (append-only)."""

from clock import now, iso
from db import DB, new_id


def append_audit(actor_role: str, actor_id: str, action: str,
                 subject_entity: str, subject_id: str, payload: dict):
    rid = new_id()
    record = {
        "id": rid,
        "created_at": iso(now()),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "payload": payload or {},
    }
    DB.audit_logs.append(record)
    return record


def append_compartment_event(compartment_id: str, parcel_id, actor_role: str,
                             actor_id: str, event_type: str):
    rid = new_id()
    record = {
        "id": rid,
        "created_at": iso(now()),
        "compartment_id": compartment_id,
        "parcel_id": parcel_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "event_type": event_type,
    }
    DB.compartment_events.append(record)
    # bump compartment.last_open_at on successful opens
    if event_type in (
        "DEPOSIT_OPEN_OK",
        "PICKUP_OPEN_OK",
        "RECALL_OPEN_OK",
        "DISPOSAL_OPEN_OK",
    ):
        c = DB.compartments.get(compartment_id)
        if c:
            c["last_open_at"] = record["created_at"]
    return record
