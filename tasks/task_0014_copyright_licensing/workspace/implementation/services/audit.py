"""Audit log + rights-chain helpers."""
import copy

from clock import format_iso, get_now
from common import stamp_new
from db import db, new_id


VALID_CHANGE_TYPES = {
    "LICENSE_CHANGED",
    "CONTRACT_AMENDED",
    "DISPUTE_LOGGED",
    "ROYALTY_REVERSED",
    "RIGHTS_CONFLICT_DETECTED",
}


def append_audit(actor_id: str, subject_entity: str, subject_id: str,
                 change_type: str, before, after):
    row = {
        "id": new_id(),
        "created_at": format_iso(get_now()),
        "actor_id": actor_id or "system",
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "change_type": change_type,
        "before": copy.deepcopy(before) if before is not None else None,
        "after": copy.deepcopy(after) if after is not None else None,
    }
    db.audit_logs[row["id"]] = row
    return row


def append_rights_chain(work_id: str, event_type: str, actor_id: str,
                        ref_entity: str, ref_id: str, payload: dict):
    row = {
        "id": new_id(),
        "created_at": format_iso(get_now()),
        "work_id": work_id,
        "event_type": event_type,
        "actor_id": actor_id or "system",
        "ref_entity": ref_entity,
        "ref_id": ref_id,
        "payload": copy.deepcopy(payload) if payload is not None else {},
    }
    db.rights_chain_events[row["id"]] = row
    return row
