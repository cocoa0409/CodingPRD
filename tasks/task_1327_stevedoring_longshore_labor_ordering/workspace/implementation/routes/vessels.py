"""VesselCall endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
import services
from db import all_of, get, new_resource, pub, save, touch
from middleware import (
    ANY_ROLE, list_response, req_datetime, req_int, req_num, req_str,
    require_roles,
)
from response import get_body, ok

bp = Blueprint("vessels", __name__)


@bp.post("/api/vessel-calls")
def create_vessel():
    require_roles("StevedoreAdmin")
    body = get_body()
    vessel_name = req_str(body, "vessel_name")
    voyage_number = req_str(body, "voyage_number")
    shipping_line = req_str(body, "shipping_line")
    eta_raw, _eta = req_datetime(body, "eta_utc")
    planned_moves = req_int(body, "planned_moves", min_value=0)
    planned_tons = req_num(body, "planned_tons", min_value=0)
    contracted_mph_target = req_num(body, "contracted_mph_target", gt=0)
    credit_limit_cents = req_int(body, "credit_limit_cents", min_value=1)
    if planned_moves == 0 and planned_tons == 0:
        raise errors.cargo_plan_required()
    rec = new_resource("vessel_calls")
    rec.update({
        "vessel_name": vessel_name,
        "voyage_number": voyage_number,
        "shipping_line": shipping_line,
        "eta_utc": eta_raw,
        "planned_moves": planned_moves,
        "planned_tons": planned_tons,
        "contracted_mph_target": contracted_mph_target,
        "credit_limit_cents": credit_limit_cents,
        "status": "SCHEDULED",
        "work_posture": "NORMAL",
        "actual_moves": 0,
        "actual_tons": 0,
    })
    save("vessel_calls", rec)
    return ok(pub(rec), 201)


@bp.get("/api/vessel-calls")
def list_vessels():
    require_roles(*ANY_ROLE)
    return list_response("vessel_calls", {"status": request.args.get("status")})


@bp.get("/api/vessel-calls/<vid>")
def get_vessel(vid):
    require_roles(*ANY_ROLE)
    v = get("vessel_calls", vid)
    if v is None:
        raise errors.not_found("Vessel call not found")
    return ok(pub(v))


def _get_vessel(vid):
    v = get("vessel_calls", vid)
    if v is None:
        raise errors.not_found("Vessel call not found")
    return v


@bp.post("/api/vessel-calls/<vid>/berth")
def berth_vessel(vid):
    require_roles("StevedoreSuperintendent")
    v = _get_vessel(vid)
    if v["status"] != "SCHEDULED":
        raise errors.invalid_state("Only a SCHEDULED vessel call can be berthed")
    v["status"] = "BERTHED"
    touch(v)
    return ok(pub(v))


@bp.post("/api/vessel-calls/<vid>/complete")
def complete_vessel(vid):
    require_roles("StevedoreSuperintendent")
    v = _get_vessel(vid)
    if v["status"] != "WORKING":
        raise errors.invalid_state("Only a WORKING vessel call can be completed")
    for s in services.shifts_of_vessel(v["id"]):
        if s["status"] != "CLOSED":
            raise errors.invalid_state("Every shift window of the vessel must be CLOSED")
    v["status"] = "COMPLETED"
    touch(v)
    return ok(pub(v))


@bp.post("/api/vessel-calls/<vid>/cancel")
def cancel_vessel(vid):
    require_roles("StevedoreSuperintendent")
    v = _get_vessel(vid)
    if v["status"] not in ("SCHEDULED", "BERTHED"):
        raise errors.invalid_state("Only a SCHEDULED or BERTHED vessel call can be cancelled")
    for g in services.gangs_of_vessel(v["id"]):
        if g["status"] not in services.GANG_TERMINAL:
            raise errors.invalid_state("A non-terminal gang order exists on this vessel")
    v["status"] = "CANCELLED"
    touch(v)
    return ok(pub(v))
