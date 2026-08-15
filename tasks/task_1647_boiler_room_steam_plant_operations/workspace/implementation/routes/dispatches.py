"""LoadDispatch endpoints: creation with half-open overlap semantics (PRD 2.11),
list/get, and cancellation."""
from flask import Blueprint, request

import resolve
import store
from auth import authenticate, authorize
from errors import (
    raise_err,
    ERR_DISPATCH_WINDOW_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFERENCED_NOT_FOUND,
)
from services import (
    compute_lead,
    dispatch_json,
    dispatches_of,
    require_active_operator,
)
from util import (
    body_json,
    list_response,
    new_record,
    req_dt,
    req_int,
    req_str_list,
    success_object,
    touch,
)

bp = Blueprint("dispatches", __name__)

WRITERS = ["PlantManager", "Operator"]
READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/load-dispatches")
def create_dispatch(plantId):
    _, role = authenticate()
    authorize(role, WRITERS)
    plant = resolve.plant(plantId)
    body = body_json()
    start = req_dt(body, "window_start_at")
    end = req_dt(body, "window_end_at")
    target = req_int(body, "target_steam_lb_hr")
    assigned = req_str_list(body, "assigned_boiler_ids")
    # referential integrity(11): every assigned boiler must exist in this plant
    for bid in assigned:
        b = store.boilers.get(bid)
        if b is None or b["plant_id"] != plant["id"]:
            raise_err(ERR_REFERENCED_NOT_FOUND,
                      "assigned_boiler_ids element does not reference an existing boiler")
    # window conflict(12): half-open [start, end); touching does NOT conflict
    for d in dispatches_of(plant["id"]):
        if d["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if not any(bid in d["assigned_boiler_ids"] for bid in assigned):
            continue
        if start < d["window_end_at"] and d["window_start_at"] < end:
            raise_err(ERR_DISPATCH_WINDOW_CONFLICT,
                      "A boiler is already assigned to an overlapping dispatch window")
    # window shape(14): end must be strictly after start
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "window_end_at must be strictly after window_start_at")
    rec = new_record()
    rec.update({
        "plant_id": plant["id"],
        "window_start_at": start,
        "window_end_at": end,
        "target_steam_lb_hr": target,
        "assigned_boiler_ids": assigned,
        "expected_lead_boiler_id": compute_lead(plant),
        "status": "SCHEDULED",
    })
    store.dispatches[rec["id"]] = rec
    return success_object(dispatch_json(rec), 201)


@bp.get("/plants/<plantId>/load-dispatches/<dispatchId>")
def get_dispatch(plantId, dispatchId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    rec = resolve.dispatch(plant, dispatchId)
    return success_object(dispatch_json(rec))


@bp.get("/plants/<plantId>/load-dispatches")
def list_dispatches(plantId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    recs = dispatches_of(plant["id"])
    status = request.args.get("status")
    if status is not None:
        recs = [d for d in recs if d["status"] == status]
    return list_response(recs, dispatch_json)


@bp.post("/plants/<plantId>/load-dispatches/<dispatchId>/cancel")
def cancel_dispatch(plantId, dispatchId):
    uid, role = authenticate()
    authorize(role, WRITERS)
    plant = resolve.plant(plantId)
    rec = resolve.dispatch(plant, dispatchId)
    # state(4): COMPLETED and CANCELLED are terminal
    if rec["status"] not in ("SCHEDULED", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED or ACTIVE dispatch can be cancelled")
    if role == "Operator":
        # license(8): operator-initiated state transition
        require_active_operator(uid)
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(dispatch_json(rec))
