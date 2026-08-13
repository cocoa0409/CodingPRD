"""ShiftWindow endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
import services
from db import get, new_resource, pub, save, touch
from middleware import (
    ANY_ROLE, list_response, req_date, req_datetime, req_enum, req_field,
    require_roles,
)
from response import get_body, ok

bp = Blueprint("shifts", __name__)

PERIODS = ("DAY", "NIGHT", "GRAVEYARD")
MAX_SHIFT_MINUTES = 960


@bp.post("/api/shift-windows")
def create_shift():
    require_roles("StevedoreSuperintendent")
    body = get_body()
    # existence (priority 3) before schema (priority 4)
    vessel_call_id = req_field(body, "vessel_call_id")
    if get("vessel_calls", vessel_call_id) is None:
        raise errors.not_found("Vessel call not found")
    shift_date = req_date(body, "shift_date")
    period = req_enum(body, "period", PERIODS)
    start_raw, start = req_datetime(body, "start_utc")
    end_raw, end = req_datetime(body, "end_utc")
    duration_minutes = (end - start).total_seconds() / 60
    if end <= start or duration_minutes > MAX_SHIFT_MINUTES:
        raise errors.shift_window_invalid()
    rec = new_resource("shift_windows")
    rec.update({
        "vessel_call_id": vessel_call_id,
        "shift_date": shift_date,
        "period": period,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "status": "PLANNED",
        "_start": start,
        "_end": end,
    })
    save("shift_windows", rec)
    return ok(pub(rec), 201)


@bp.get("/api/shift-windows")
def list_shifts():
    require_roles(*ANY_ROLE)
    return list_response("shift_windows", {
        "vessel_call_id": request.args.get("vessel_call_id"),
        "status": request.args.get("status"),
    })


def _get_shift(sid):
    s = get("shift_windows", sid)
    if s is None:
        raise errors.not_found("Shift window not found")
    return s


@bp.get("/api/shift-windows/<sid>")
def get_shift(sid):
    require_roles(*ANY_ROLE)
    return ok(pub(_get_shift(sid)))


@bp.post("/api/shift-windows/<sid>/open-for-orders")
def open_for_orders(sid):
    require_roles("StevedoreSuperintendent")
    s = _get_shift(sid)
    if s["status"] != "PLANNED":
        raise errors.invalid_state("Only a PLANNED shift can be opened for orders")
    vessel = services.shift_vessel(s)
    if vessel["status"] not in ("BERTHED", "WORKING"):
        raise errors.invalid_state("Vessel must be BERTHED or WORKING to open a shift for orders")
    s["status"] = "OPEN_FOR_ORDERS"
    touch(s)
    return ok(pub(s))


@bp.post("/api/shift-windows/<sid>/start")
def start_shift(sid):
    require_roles("StevedoreSuperintendent")
    s = _get_shift(sid)
    if s["status"] != "OPEN_FOR_ORDERS":
        raise errors.invalid_state("Only an OPEN_FOR_ORDERS shift can be started")
    s["status"] = "IN_PROGRESS"
    touch(s)
    # first IN_PROGRESS shift advances the vessel BERTHED -> WORKING
    vessel = services.shift_vessel(s)
    if vessel["status"] == "BERTHED":
        vessel["status"] = "WORKING"
        touch(vessel)
    return ok(pub(s))
