"""Shift endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import (
    err,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_SHIFT_ALREADY_OPEN,
)
from middleware import get_identity, require_roles
from response import object_response, array_response
from services.common import (
    get_body,
    require_fields,
    require_int,
    require_str,
    parse_pagination,
    paginate,
    get_or_404,
    open_shift_for,
)
from services.shift_calc import recompute_shift
from services.serialize import view

bp = Blueprint("shifts", __name__)


@bp.post("/shifts")
def open_shift():
    user_id, role = get_identity()
    require_roles(role, {"Attendant"})
    body = get_body()
    require_fields(body, ["attendant_id", "opening_float_cents"])
    attendant_id = require_str(body["attendant_id"], "attendant_id")
    opening_float = require_int(body["opening_float_cents"], "opening_float_cents", minimum=0)
    with db.lock:
        # Only one OPEN shift per attendant (priority 17). The shift owner is
        # identified by attendant_id; enforce against any existing OPEN shift
        # for that attendant_id.
        if open_shift_for(attendant_id) is not None:
            raise err(ERR_SHIFT_ALREADY_OPEN, "Attendant already has an OPEN shift")
        shift = {
            "attendant_id": attendant_id,
            "opening_float_cents": opening_float,
            "status": "OPEN",
            "coin_collected_cents": 0,
            "cash_reload_cents": 0,
            "cash_refund_paid_cents": 0,
            "expected_drawer_cents": opening_float,
            "counted_drawer_cents": None,
            "variance_cents": None,
        }
        stamp_create(shift)
        db.shifts[shift["id"]] = shift
    return object_response(view(shift), status=201)


@bp.get("/shifts")
def list_shifts():
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    attendant_id = request.args.get("attendant_id")
    items = list(db.shifts.values())
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if attendant_id is not None:
        items = [s for s in items if s["attendant_id"] == attendant_id]
    window, total = paginate(items, limit, offset)
    return array_response([view(s) for s in window], limit, offset, total)


@bp.get("/shifts/<shift_id>")
def get_shift(shift_id):
    _, role = get_identity()
    require_roles(role, {"Manager", "Attendant"})
    shift = get_or_404(db.shifts, shift_id, "Shift")
    return object_response(view(shift))


@bp.post("/shifts/<shift_id>/begin-reconcile")
def begin_reconcile(shift_id):
    user_id, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        shift = get_or_404(db.shifts, shift_id, "Shift")
        # Ownership (priority 5): attendant acting must own the shift.
        if shift["attendant_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Attendant does not own this shift")
        if shift["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "Shift is not OPEN")
        # Recompute and freeze expected_drawer_cents.
        recompute_shift(shift)
        shift["status"] = "RECONCILING"
        touch(shift)
    return object_response(view(shift))


@bp.post("/shifts/<shift_id>/close")
def close_shift(shift_id):
    user_id, role = get_identity()
    require_roles(role, {"Attendant"})
    with db.lock:
        shift = get_or_404(db.shifts, shift_id, "Shift")
        body = get_body()
        require_fields(body, ["counted_drawer_cents"])
        counted = require_int(body["counted_drawer_cents"], "counted_drawer_cents")
        # Ownership (priority 5).
        if shift["attendant_id"] != user_id:
            raise err(ERR_FORBIDDEN, "Attendant does not own this shift")
        if shift["status"] != "RECONCILING":
            raise err(ERR_INVALID_STATE, "Shift is not RECONCILING")
        shift["counted_drawer_cents"] = counted
        shift["variance_cents"] = counted - shift["expected_drawer_cents"]
        shift["status"] = "CLOSED"
        touch(shift)
    return object_response(view(shift))
