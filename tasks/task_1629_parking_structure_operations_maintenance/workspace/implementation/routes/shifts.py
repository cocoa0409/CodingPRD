"""Attendant shift endpoints (PRD 3.5)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state, err_not_owner, err_shift_already_open
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_int, optional_int, parse_pagination, paginate,
    require_ref, get_shift, public_view,
)
from services.fees import refresh_shift_expected

bp = Blueprint("shifts", __name__)


@bp.post("/ops/shifts")
def open_shift():
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    opening_float = require_int(payload, "opening_float_cents", minimum=0)
    for s in db.shifts.values():
        if (s["facility_id"] == facility["id"]
                and s["attendant_user_id"] == actor.user_id
                and s["shift_status"] == "OPEN"):
            raise err_shift_already_open()
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "attendant_user_id": actor.user_id,
        "shift_status": "OPEN",
        "opening_float_cents": opening_float,
        "counted_cash_cents": None,
        "over_ring_cents": 0,
        "paid_out_cents": 0,
        "expected_cash_cents": opening_float,
        "comp_total_cents": 0,
        "opened_at": db.now_iso(),
        "closed_at": None,
    }
    db.stamp_new(ent)
    db.shifts[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/shifts/<shift_id>")
def get_shift_route(shift_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_shift(shift_id)))


@bp.get("/ops/shifts")
def list_shifts():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.shifts.values())
    facility_id = request.args.get("facility_id")
    attendant = request.args.get("attendant_user_id")
    shift_status = request.args.get("shift_status")
    if facility_id is not None:
        items = [s for s in items if s["facility_id"] == facility_id]
    if attendant is not None:
        items = [s for s in items if s["attendant_user_id"] == attendant]
    if shift_status is not None:
        items = [s for s in items if s["shift_status"] == shift_status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(s) for s in page], limit, offset, total)


@bp.post("/ops/shifts/<shift_id>/close")
def close_shift(shift_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant"])
    shift = get_shift(shift_id)
    # identity binding (stage 3): only the owning attendant may close
    if shift["attendant_user_id"] != actor.user_id:
        raise err_not_owner("only the shift's attendant may close it")
    payload = body()
    counted = require_int(payload, "counted_cash_cents", minimum=0)
    over_ring = optional_int(payload, "over_ring_cents", minimum=0)
    paid_out = optional_int(payload, "paid_out_cents", minimum=0)
    if shift["shift_status"] != "OPEN":
        raise err_invalid_state("only an OPEN shift may be closed")
    shift["counted_cash_cents"] = counted
    if over_ring is not None:
        shift["over_ring_cents"] = over_ring
    if paid_out is not None:
        shift["paid_out_cents"] = paid_out
    shift["shift_status"] = "CLOSED"
    shift["closed_at"] = db.now_iso()
    refresh_shift_expected(shift)
    db.touch(shift)
    return success_object(public_view(shift))
