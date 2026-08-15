"""HOAAssociation endpoints (PRD 3.8): formation, control transfer, transition."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BOARD_NOT_SEATED,
    ERR_CONTROL_THRESHOLD_NOT_MET,
    ERR_HOA_INVALID_STATE,
    ERR_PARCEL_NOT_ACQUIRED,
)
from middleware import authorized, check_hoa_ownership
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, touch
from util import CLOCK, parse_dt
from validate import (
    check_body_fk_exists,
    get_body,
    opt_int,
    req_datetime,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("hoas", __name__)


@bp.post("/hoa-associations")
def create_hoa():
    authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence
    check_body_fk_exists("parcels", body, "parcel_id")
    # Priority 4: shape
    rec = new_record("hoas", {
        "parcel_id": req_str(body, "parcel_id"),
        "hoa_name": req_str(body, "hoa_name"),
        "control_transfer_pct_bp": opt_int(body, "control_transfer_pct_bp", 7500, non_negative=True),
        "statutory_control_end": req_datetime(body, "statutory_control_end"),
        "board_seated_count": None,
        "status": "FORMATION_PENDING",
    })
    return success_object(public(rec), status=201)


@bp.get("/hoa-associations")
def list_hoas():
    return list_response("hoas", {
        "parcel_id": request.args.get("parcel_id"),
        "status": request.args.get("status"),
    })


@bp.get("/hoa-associations/<rid>")
def get_hoa(rid):
    return get_one("hoas", rid)


@bp.post("/hoa-associations/<rid>/form")
def form_hoa(rid):
    authorized(["DeveloperOperator"])
    hoa = require_path("hoas", rid)
    if hoa["status"] != "FORMATION_PENDING":
        raise_error(ERR_HOA_INVALID_STATE, "form requires FORMATION_PENDING")
    # Priority 10 (referential)
    parcel = db["parcels"].get(hoa["parcel_id"])
    if parcel is None or parcel["status"] != "ACQUIRED":
        raise_error(ERR_PARCEL_NOT_ACQUIRED, "HOA formation requires parcel ACQUIRED")
    hoa["status"] = "DECLARANT_CONTROL"
    touch(hoa)
    return success_object(public(hoa))


def _transfer_due(hoa, parcel):
    """hoa_control_transfer_check (PRD 3.8): ratio path (inclusive, integer
    cross-multiplication, requires total > 0) OR statutory path (exclusive)."""
    total = parcel["total_lots_planned"]
    closed = parcel["lots_closed_count"]
    ratio_due = total > 0 and closed * 10000 >= total * hoa["control_transfer_pct_bp"]
    statutory_due = CLOCK.now() > parse_dt(hoa["statutory_control_end"])
    return ratio_due or statutory_due


@bp.post("/hoa-associations/<rid>/evaluate-control")
def evaluate_control(rid):
    caller = authorized(["DeveloperOperator", "HOAManager"])
    hoa = db["hoas"].get(rid)
    # Priority 2 (ownership) — evaluated when the target resolves
    check_hoa_ownership(caller, hoa)
    # Priority 3 (existence)
    if hoa is None:
        require_path("hoas", rid)
    # Priority 6 (state)
    if hoa["status"] != "DECLARANT_CONTROL":
        raise_error(ERR_HOA_INVALID_STATE, "evaluate-control requires DECLARANT_CONTROL")
    # Priority 9 (constraint): either transfer path must hold
    parcel = db["parcels"][hoa["parcel_id"]]
    if not _transfer_due(hoa, parcel):
        raise_error(ERR_CONTROL_THRESHOLD_NOT_MET,
                    "neither the closed-lot ratio nor the statutory sunset is met")
    hoa["status"] = "TRANSITIONING"
    touch(hoa)
    return success_object(public(hoa))


@bp.post("/hoa-associations/<rid>/complete-transition")
def complete_transition(rid):
    caller = authorized(["HOAManager"])
    hoa = db["hoas"].get(rid)
    # Priority 2 (ownership): the association's own manager only
    check_hoa_ownership(caller, hoa)
    # Priority 3 (existence)
    if hoa is None:
        require_path("hoas", rid)
    # Priority 4 (shape)
    body = get_body()
    seated = req_int(body, "seated_board_count")
    # Priority 6 (state)
    if hoa["status"] != "TRANSITIONING":
        raise_error(ERR_HOA_INVALID_STATE, "complete-transition requires TRANSITIONING")
    # Priority 9 (constraint)
    if seated < 3:
        raise_error(ERR_BOARD_NOT_SEATED, "seated_board_count must be at least 3")
    hoa["board_seated_count"] = seated
    hoa["status"] = "HOMEOWNER_CONTROL"
    touch(hoa)
    return success_object(public(hoa))
