"""Vacation slot endpoints: create under a period, grant by seniority order, close."""
from flask import request, Blueprint

from db import db, mint, touch, ser
from errors import (
    ApiError,
    invalid_state,
    validation,
    ERR_INSUFFICIENT_VACATION_BALANCE,
    ERR_VACATION_SLOT_FULL,
)
from helpers import (
    body_json,
    req_date,
    req_int,
    req_field,
    get_period_or_404,
    get_vacation_slot_or_404,
    ref_operator_or_404,
    paginated,
    VACATION_WEEK_HOURS,
)
from middleware import authenticate, require_roles, READ_SO_OP_UR
from response import ok_obj

bp = Blueprint("vacation", __name__)

SO = ["SchedulingOfficer"]


@bp.post("/api/sign-up-periods/<pid>/vacation-slots")
def create_vacation_slot(pid):
    auth = authenticate()
    require_roles(auth, SO)
    get_period_or_404(pid)
    body = body_json()
    week_start_date = req_date(body, "week_start_date")
    capacity = req_int(body, "capacity", 1)
    slot = mint()
    slot.update(
        {
            "sign_up_period_id": pid,
            "week_start_date": week_start_date,
            "capacity": capacity,
            "allocated_count": 0,
            "operator_id": None,
            "status": "OPEN",
        }
    )
    db.vacation_slots[slot["id"]] = slot
    return ok_obj(ser(slot), 201)


@bp.get("/api/sign-up-periods/<pid>/vacation-slots")
def list_vacation_slots(pid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_period_or_404(pid)
    items = [v for v in db.vacation_slots.values() if v["sign_up_period_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paginated(items)


@bp.post("/api/vacation-slots/<vid>/grant")
def grant_vacation(vid):
    auth = authenticate()
    require_roles(auth, SO)
    slot = get_vacation_slot_or_404(vid)
    body = body_json()
    operator_id = req_field(body, "operator_id")
    if not isinstance(operator_id, str):
        raise validation("operator_id must be a string")
    op = ref_operator_or_404(operator_id)
    if slot["status"] == "CLOSED":
        raise invalid_state("A CLOSED vacation slot accepts no grants")
    # Checks in PRD order: balance first, then remaining capacity
    if op["vacation_hours_balance"] < VACATION_WEEK_HOURS:
        raise ApiError(
            ERR_INSUFFICIENT_VACATION_BALANCE,
            "operator vacation_hours_balance is below 40 hours",
            422,
        )
    if slot["allocated_count"] >= slot["capacity"]:
        raise ApiError(
            ERR_VACATION_SLOT_FULL,
            "vacation slot allocated_count already equals capacity",
            409,
        )
    slot["allocated_count"] += 1
    slot["operator_id"] = op["id"]
    if slot["allocated_count"] == slot["capacity"]:
        slot["status"] = "FULLY_ALLOCATED"
    touch(slot)
    op["vacation_hours_balance"] -= VACATION_WEEK_HOURS
    touch(op)
    return ok_obj(ser(slot))


@bp.post("/api/vacation-slots/<vid>/close")
def close_vacation(vid):
    auth = authenticate()
    require_roles(auth, SO)
    slot = get_vacation_slot_or_404(vid)
    if slot["status"] not in ("OPEN", "FULLY_ALLOCATED"):
        raise invalid_state("Only an OPEN or FULLY_ALLOCATED vacation slot may be closed")
    slot["status"] = "CLOSED"
    touch(slot)
    return ok_obj(ser(slot))
