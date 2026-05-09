"""Audit log helper."""
import copy
from db import store, init_append_only
from clock import clock


VALID_ACTIONS = {
    "SCHEDULE_CHANGE",
    "BUDGET_ADJUSTMENT",
    "RESERVE_DRAW",
    "CONTRACT_SIGNED",
    "EQUIPMENT_LOSS",
    "WRAP_CLOSE",
}


def log(production_id, actor_user_id, action, subject_entity, subject_id,
        before, after, extra=None):
    rec = {
        "production_id": production_id,
        "actor_user_id": actor_user_id,
        "action": action,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "before_json": copy.deepcopy(before) if before is not None else None,
        "after_json": copy.deepcopy(after) if after is not None else None,
        "occurred_at": clock.now_iso(),
    }
    if extra:
        rec.update(extra)
    init_append_only(rec)
    store.audit_logs[rec["id"]] = rec
    return rec
