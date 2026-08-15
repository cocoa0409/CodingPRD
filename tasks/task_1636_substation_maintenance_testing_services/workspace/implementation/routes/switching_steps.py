"""SwitchingStep endpoints."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_state_transition, err_segregation_of_duties,
    err_duplicate_key, err_step_order_violation,
)
from services.common import (
    body, require_string, require_int, parse_pagination, paginate,
    get_outage_window, get_switching_step,
)

bp = Blueprint("switching_steps", __name__)


def step_view(s):
    return {
        "id": s["id"],
        "outage_window_id": s["outage_window_id"],
        "sequence_no": s["sequence_no"],
        "description": s["description"],
        "status": s["status"],
        "executed_by": s.get("executed_by"),
        "executed_at": s.get("executed_at"),
        "verified_by": s.get("verified_by"),
        "verified_at": s.get("verified_at"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.post("/outage-windows/<id>/switching-steps")
def create_switching_step(id):
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    w = get_outage_window(id)
    if w["status"] not in ("REQUESTED", "APPROVED"):
        raise err_state_transition("Steps can only be added while window is REQUESTED or APPROVED")
    payload = body()
    sequence_no = require_int(payload, "sequence_no")
    if sequence_no < 1:
        raise err_validation("sequence_no must be >= 1")
    description = require_string(payload, "description")
    # Uniqueness within window
    for s in db.switching_steps.values():
        if s["outage_window_id"] == id and s["sequence_no"] == sequence_no:
            raise err_duplicate_key("sequence_no already exists in this window")
    ent = {
        "id": db.new_id(),
        "outage_window_id": id,
        "sequence_no": sequence_no,
        "description": description,
        "status": "PENDING",
        "executed_by": None,
        "executed_at": None,
        "verified_by": None,
        "verified_at": None,
    }
    db.stamp_new(ent)
    db.switching_steps[ent["id"]] = ent
    return success_object(step_view(ent), status=201)


@bp.get("/outage-windows/<id>/switching-steps")
def list_switching_steps(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    w = get_outage_window(id)
    limit, offset = parse_pagination()
    items = [s for s in db.switching_steps.values() if s["outage_window_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list([step_view(s) for s in page], limit, offset, total)


@bp.post("/switching-steps/<id>/execute")
def execute_step(id):
    actor = get_actor()
    require_roles(actor, ["SwitchingSupervisor"])
    step = get_switching_step(id)
    if step["status"] != "PENDING":
        raise err_state_transition("Step is not PENDING")
    # Parent window must be SWITCHING
    w = get_outage_window(step["outage_window_id"])
    if w["status"] != "SWITCHING":
        raise err_state_transition("Parent window is not SWITCHING")
    # All lower-sequence siblings must be VERIFIED
    for s in db.switching_steps.values():
        if s["outage_window_id"] == step["outage_window_id"] and s["sequence_no"] < step["sequence_no"]:
            if s["status"] != "VERIFIED":
                raise err_step_order_violation()
    step["status"] = "EXECUTED"
    step["executed_by"] = actor.user_id
    step["executed_at"] = db.now_iso()
    db.touch(step)
    return success_object(step_view(step))


@bp.post("/switching-steps/<id>/verify")
def verify_step(id):
    actor = get_actor()
    require_roles(actor, ["SwitchingSupervisor"])
    step = get_switching_step(id)
    if step["status"] != "EXECUTED":
        raise err_state_transition("Step is not EXECUTED")
    # Segregation of duties
    if actor.user_id == step.get("executed_by"):
        raise err_segregation_of_duties("Verifier must differ from executor")
    step["status"] = "VERIFIED"
    step["verified_by"] = actor.user_id
    step["verified_at"] = db.now_iso()
    db.touch(step)
    return success_object(step_view(step))
