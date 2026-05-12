"""Audit log and escrow ledger writers."""

from clock import CLOCK
from db import DB, new_id


def append_audit(
    subject_type: str,
    subject_id: str,
    event_type: str,
    payload: dict,
    actor_role: str,
    actor_id: str,
):
    entry = {
        "id": new_id(),
        "created_at": CLOCK.now(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "payload": payload or {},
        "actor_role": actor_role,
        "actor_id": actor_id,
    }
    DB.audit_log.append(entry)
    return entry


def append_escrow(
    project_id: str,
    order_id,
    entry_type: str,
    amount_cents: int,
    external_ref=None,
):
    entry = {
        "id": new_id(),
        "created_at": CLOCK.now(),
        "project_id": project_id,
        "order_id": order_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "external_ref": external_ref,
    }
    DB.escrow_ledger.append(entry)
    return entry
