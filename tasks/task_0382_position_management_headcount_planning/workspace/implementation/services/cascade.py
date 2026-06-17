"""Cascade engine: freeze / lift / clock-driven posture transitions and the
abolish teardown (PRD §2.10, §3.5, §3.8). Every touched record bumps its own
version and updated_at."""
from db import db
from . import calc
from .common import bump


def _positions_of(cost_center_id):
    return [p for p in db.positions.values() if p["cost_center_id"] == cost_center_id]


def _open_requisitions_of(position_id):
    return [r for r in db.requisitions.values()
            if r["position_id"] == position_id and r["status"] == "OPEN"]


def _suspended_requisitions_of(position_id):
    return [r for r in db.requisitions.values()
            if r["position_id"] == position_id and r["status"] == "SUSPENDED"]


def freeze_cost_center(cost_center_id):
    """Cascade a flip to FROZEN: each FUNDED position -> FROZEN, and each such
    freeze suspends that position's OPEN requisitions (PRD §3.5)."""
    for p in _positions_of(cost_center_id):
        if p["lifecycle_status"] == "FUNDED":
            p["lifecycle_status"] = "FROZEN"
            bump(p)
            for r in _open_requisitions_of(p["id"]):
                r["status"] = "SUSPENDED"
                bump(r)


def unfreeze_cost_center(cost_center_id):
    """Cascade a flip to OPEN: each FROZEN position -> FUNDED, and each un-freeze
    re-opens that position's SUSPENDED requisitions (PRD §3.5)."""
    for p in _positions_of(cost_center_id):
        if p["lifecycle_status"] == "FROZEN":
            p["lifecycle_status"] = "FUNDED"
            bump(p)
            for r in _suspended_requisitions_of(p["id"]):
                r["status"] = "OPEN"
                bump(r)


def reconcile_posture(cost_center_id, previous_posture):
    """Given the posture computed before and after a change, fire the matching
    cascade. Returns the new posture."""
    new_posture = calc.cost_center_posture(cost_center_id)
    if previous_posture == new_posture:
        return new_posture
    if new_posture == "FROZEN":
        freeze_cost_center(cost_center_id)
    else:
        unfreeze_cost_center(cost_center_id)
    return new_posture


def recompute_all_postures(previous_map):
    """After a clock advance, recompute every cost center's posture and fire
    freeze/un-freeze cascades for windows that just opened or closed
    (PRD §3.5). previous_map maps cost_center_id -> posture before the change."""
    for cc_id in list(db.cost_centers.keys()):
        prev = previous_map.get(cc_id, "OPEN")
        reconcile_posture(cc_id, prev)


def snapshot_postures():
    """Capture current posture of every cost center (pre-change baseline)."""
    return {cc_id: calc.cost_center_posture(cc_id) for cc_id in db.cost_centers}
