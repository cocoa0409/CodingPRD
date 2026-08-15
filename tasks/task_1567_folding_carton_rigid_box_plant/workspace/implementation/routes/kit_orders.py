"""KitOrder endpoints (PRD §3.7): allocation against finished cartons."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_KIT_QTY_EXCEEDS_REMAINING,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    req_int,
    req_list,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("kit_orders", __name__)


def _available_cartons(job):
    good = job["good_sheets_actual"] * (job["locked_ups"] or 0)
    return good - job["allocated_cartons"]


@bp.post("/plant/kit-orders")
def create_kit_order():
    authenticate(("KittingLead",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")

    job_id = req_str(data, "job_id")
    kit_name = req_str(data, "kit_name")
    components = req_list(data, "components")
    kits_planned = req_int(data, "kits_planned", 1)
    if len(components) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "components must be non-empty")
    for entry in components:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Each component must be an object")
        req_str(entry, "description")
        req_int(entry, "units_per_kit", 1)

    job = db.jobs[job_id]
    if job["status"] != "FINISHED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Kit orders require a FINISHED job")

    consumed_per_kit = sum(c["units_per_kit"] for c in components)
    allocated = consumed_per_kit * kits_planned
    if allocated > _available_cartons(job):
        raise ApiError(ERR_KIT_QTY_EXCEEDS_REMAINING, 409,
                       "Allocation exceeds the job's available finished cartons")

    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "kit_name": kit_name,
        "components": [{"description": c["description"],
                        "units_per_kit": c["units_per_kit"]} for c in components],
        "kits_planned": kits_planned,
        "consumed_per_kit": consumed_per_kit,
        "allocated_cartons": allocated,
        "kits_completed": 0,
        "consumed_cartons": 0,
        "labor_minutes_actual": None,
        "status": "PLANNED",
    })
    db.kit_orders[rec["id"]] = rec

    job["allocated_cartons"] += allocated
    touch(job)
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/kit-orders")
def list_kit_orders():
    authenticate(ALL_ROLES)
    return list_response(
        db.kit_orders.values(),
        ser_plain,
        [("job_id", "job_id", "str"), ("status", "status", "str")],
    )


@bp.get("/plant/kit-orders/<kitId>")
def get_kit_order(kitId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.kit_orders, kitId)))


@bp.post("/plant/kit-orders/<kitId>/start")
def start_kit_order(kitId):
    authenticate(("KittingLead",))
    rec = get_or_404(db.kit_orders, kitId)
    if rec["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a PLANNED kit order can be started")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return ok_object(ser_plain(rec))


def _return_unused_allocation(rec):
    job = db.jobs[rec["job_id"]]
    returned = (rec["kits_planned"] - rec["kits_completed"]) * rec["consumed_per_kit"]
    job["allocated_cartons"] -= returned
    touch(job)


@bp.post("/plant/kit-orders/<kitId>/complete")
def complete_kit_order(kitId):
    authenticate(("KittingLead",))
    rec = get_or_404(db.kit_orders, kitId)
    data = get_body()
    kits_completed = req_int(data, "kits_completed", 0)
    labor_minutes_actual = req_int(data, "labor_minutes_actual", 0)
    if kits_completed > rec["kits_planned"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "kits_completed must not exceed kits_planned")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only an IN_PROGRESS kit order can be completed")

    rec["kits_completed"] = kits_completed
    rec["consumed_cartons"] = kits_completed * rec["consumed_per_kit"]
    rec["labor_minutes_actual"] = labor_minutes_actual
    rec["status"] = "COMPLETED"
    touch(rec)
    _return_unused_allocation(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/kit-orders/<kitId>/cancel")
def cancel_kit_order(kitId):
    authenticate(("KittingLead",))
    rec = get_or_404(db.kit_orders, kitId)
    if rec["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a PLANNED or IN_PROGRESS kit order can be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    _return_unused_allocation(rec)
    return ok_object(ser_plain(rec))
