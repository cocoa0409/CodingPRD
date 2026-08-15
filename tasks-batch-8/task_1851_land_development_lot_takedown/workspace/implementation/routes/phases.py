"""Phase endpoints (PRD 3.2): phasing, plat approval loop, lot recordation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_PHASE_INVALID_STATE,
    ERR_PHASE_WINDOW_OVERLAP,
    ERR_PARCEL_NOT_ACQUIRED,
    ERR_BOND_NOT_POSTED_FOR_PHASE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record, phases_of_parcel, lots_of_phase, recompute_parcel, touch
from util import CLOCK, parse_dt
from validate import (
    check_body_fk_exists,
    get_body,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("phases", __name__)

LOT_TYPES = {"STANDARD", "PREMIUM", "ESTATE"}
DECISIONS = {"APPROVE", "REJECT"}
BOND_POSTED_STATES = {"POSTED", "PARTIALLY_REDUCED", "WORK_ACCEPTED"}


@bp.post("/phases")
def create_phase():
    authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence
    check_body_fk_exists("parcels", body, "parcel_id")
    # Priority 4: shape
    parcel_id = req_str(body, "parcel_id")
    phase_name = req_str(body, "phase_name")
    sequence_number = req_int(body, "sequence_number", minimum=1)
    planned_lot_count = req_int(body, "planned_lot_count", minimum=1)
    win_start = req_datetime(body, "selling_window_start")
    win_end = req_datetime(body, "selling_window_end")
    if parse_dt(win_end) <= parse_dt(win_start):
        raise_error(ERR_INVALID_WINDOW, "selling_window_end must be strictly after selling_window_start")
    # Priority 9: half-open window overlap vs sibling phases (adjacency allowed)
    for sib in phases_of_parcel(parcel_id):
        if parse_dt(win_start) < parse_dt(sib["selling_window_end"]) \
                and parse_dt(sib["selling_window_start"]) < parse_dt(win_end):
            raise_error(ERR_PHASE_WINDOW_OVERLAP,
                        "selling window overlaps a sibling phase's window")
    rec = new_record("phases", {
        "parcel_id": parcel_id,
        "phase_name": phase_name,
        "sequence_number": sequence_number,
        "planned_lot_count": planned_lot_count,
        "selling_window_start": win_start,
        "selling_window_end": win_end,
        "plat_lot_count": None,
        "lot_type": None,
        "plat_revision": 0,
        "plat_rejection_reason": None,
        "recorded_at": None,
        "recorded_lot_count": 0,
        "status": "PLANNED",
    })
    return success_object(public(rec), status=201)


@bp.get("/phases")
def list_phases():
    return list_response("phases", {
        "parcel_id": request.args.get("parcel_id"),
        "status": request.args.get("status"),
    })


@bp.get("/phases/<rid>")
def get_phase(rid):
    return get_one("phases", rid)


@bp.post("/phases/<rid>/submit-plat")
def submit_plat(rid):
    authorized(["DeveloperOperator"])
    phase = require_path("phases", rid)
    body = get_body()
    plat_lot_count = req_int(body, "plat_lot_count", minimum=1)
    lot_type = req_enum(body, "lot_type", LOT_TYPES)
    if phase["status"] not in ("PLANNED", "PLAT_REJECTED"):
        raise_error(ERR_PHASE_INVALID_STATE, "submit-plat requires PLANNED or PLAT_REJECTED")
    if phase["status"] == "PLANNED":
        phase["plat_revision"] = 1
    else:
        # Revision loop: rejected plats are resubmitted, not recreated
        phase["plat_revision"] += 1
        phase["plat_rejection_reason"] = None
    phase["plat_lot_count"] = plat_lot_count
    phase["lot_type"] = lot_type
    phase["status"] = "PLAT_SUBMITTED"
    touch(phase)
    return success_object(public(phase))


@bp.post("/phases/<rid>/review-plat")
def review_plat(rid):
    authorized(["MunicipalClerk"])
    phase = require_path("phases", rid)
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    rejection_reason = None
    if decision == "REJECT":
        rejection_reason = body.get("rejection_reason")
        if not isinstance(rejection_reason, str) or rejection_reason.strip() == "":
            raise_error(ERR_INVALID_REQUEST, "rejection_reason is required when decision is REJECT")
    if phase["status"] != "PLAT_SUBMITTED":
        raise_error(ERR_PHASE_INVALID_STATE, "review-plat requires PLAT_SUBMITTED")
    if decision == "APPROVE":
        phase["status"] = "PLAT_APPROVED"
    else:
        phase["status"] = "PLAT_REJECTED"
        phase["plat_rejection_reason"] = rejection_reason
    touch(phase)
    return success_object(public(phase))


@bp.post("/phases/<rid>/record-plat")
def record_plat(rid):
    authorized(["MunicipalClerk"])
    phase = require_path("phases", rid)
    if phase["status"] != "PLAT_APPROVED":
        raise_error(ERR_PHASE_INVALID_STATE, "record-plat requires PLAT_APPROVED")
    # Recordation creates lot inventory: lot_number 1..plat_lot_count, type
    # copied from the recorded plat, PLATTED + ENCUMBERED.
    for i in range(1, phase["plat_lot_count"] + 1):
        new_record("lots", {
            "phase_id": phase["id"],
            "lot_number": i,
            "lot_type": phase["lot_type"],
            "sales_status": "PLATTED",
            "lien_status": "ENCUMBERED",
            "reserved_agreement_id": None,
        })
    phase["recorded_at"] = CLOCK.now_iso()
    phase["recorded_lot_count"] = len(lots_of_phase(phase["id"]))
    phase["status"] = "PLAT_RECORDED"
    touch(phase)
    parcel = db["parcels"].get(phase["parcel_id"])
    if parcel is not None:
        recompute_parcel(parcel, bump="always")
    return success_object(public(phase))


@bp.post("/phases/<rid>/activate")
def activate_phase(rid):
    authorized(["DeveloperOperator"])
    phase = require_path("phases", rid)
    if phase["status"] != "PLAT_RECORDED":
        raise_error(ERR_PHASE_INVALID_STATE, "activate requires PLAT_RECORDED")
    # Priority 10 (referential): parcel ACQUIRED, then bond posted for this phase
    parcel = db["parcels"].get(phase["parcel_id"])
    if parcel is None or parcel["status"] != "ACQUIRED":
        raise_error(ERR_PARCEL_NOT_ACQUIRED, "phase activation requires the parcel to be ACQUIRED")
    bond_ok = any(
        b["phase_id"] == phase["id"] and b["status"] in BOND_POSTED_STATES
        for b in db["bonds"].values()
    )
    if not bond_ok:
        raise_error(ERR_BOND_NOT_POSTED_FOR_PHASE,
                    "no bond in POSTED/PARTIALLY_REDUCED/WORK_ACCEPTED for this phase")
    phase["status"] = "ACTIVE"
    touch(phase)
    return success_object(public(phase))
