"""Bed holds (PRD 3.4): manual placement (OCC-guarded, superseding), listing,
single read with lazy expiry, and manual release."""

from datetime import timedelta

from flask import Blueprint, g

from core import domain as D
from core import schema as S
from core.envelope import object_response, paginate, filter_exact
from core.errors import fail
from core.store import db, new_row, bump

bp = Blueprint("holds", __name__)


@bp.post("/transfer-cases/<id>/bed-holds")
def create_bed_hold(id):
    b = S.body()
    bed_id = S.need_str(b, "bed_id")
    expected_version = S.need_int(b, "expected_transfer_case_version")
    case = D.get_case(id)
    if case is None:
        fail("ERR_CASE_NOT_FOUND", "TransferCase id does not exist.", 404)
    bed = D.get_bed(bed_id)
    if bed is None:
        fail("ERR_BED_NOT_FOUND", "Bed id does not exist.", 404)
    if g.user_id != case["receiving_facility_id"]:
        fail("ERR_NOT_FACILITY_MANAGER",
             "BedManager X-User-ID does not equal the case's receiving facility id.", 403)
    if expected_version != case["version"]:
        fail("ERR_STALE_VERSION",
             "expected_transfer_case_version does not match the case's current version.", 412)
    if case["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The case is not ACCEPTED.", 409)
    if bed["status"] != "AVAILABLE":
        fail("ERR_BED_NOT_AVAILABLE", "The bed is not AVAILABLE.", 409)
    if case["requires_isolation"] and not bed["isolation_capable"]:
        fail("ERR_ISOLATION_REQUIRED",
             "The case requires an isolation-capable bed.", 422)
    if bed["facility_id"] != case["receiving_facility_id"]:
        fail("ERR_BED_FACILITY_MISMATCH",
             "The bed does not belong to the case's receiving facility.", 422)
    if bed["unit_type"] != case["required_unit_type"]:
        fail("ERR_BED_UNIT_MISMATCH",
             "The bed's unit_type differs from the case's required_unit_type.", 422)
    # Supersede any prior ACTIVE hold of the case.
    prior = db.bed_holds.get(case["active_bed_hold_id"]) if case["active_bed_hold_id"] else None
    if prior is not None and prior["status"] == "ACTIVE":
        prior["status"] = "RELEASED"
        prior["release_reason"] = "SUPERSEDED"
        bump(prior)
        prior_bed = D.get_bed(prior["bed_id"])
        if prior_bed is not None and prior_bed["status"] == "HELD":
            prior_bed["status"] = "AVAILABLE"
            bump(prior_bed)
    bed["status"] = "HELD"
    bump(bed)
    hold = new_row("bed_holds", {
        "bed_id": bed["id"],
        "transfer_case_id": case["id"],
        "status": "ACTIVE",
        "hold_started_at": db.now,
        "hold_expires_at": db.now + timedelta(minutes=D.HOLD_MINUTES[case["acuity_level"]]),
        "release_reason": None,
    })
    case["active_bed_hold_id"] = hold["id"]
    bump(case)
    D.evaluate_saturation(case["receiving_facility_id"])
    return object_response(D.serialize_bed_hold(hold), 201)


@bp.get("/bed-holds")
def list_bed_holds():
    rows = db.ordered("bed_holds")
    rows = filter_exact(rows, "bed_id")
    rows = filter_exact(rows, "transfer_case_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, D.serialize_bed_hold)


@bp.get("/bed-holds/<id>")
def get_bed_hold(id):
    hold = db.bed_holds.get(id)
    if hold is None:
        fail("ERR_HOLD_NOT_FOUND", "BedHold id does not exist.", 404)
    return object_response(D.serialize_bed_hold(hold), 200)


@bp.post("/bed-holds/<id>/release")
def release_bed_hold(id):
    hold = db.bed_holds.get(id)
    if hold is None:
        fail("ERR_HOLD_NOT_FOUND", "BedHold id does not exist.", 404)
    if g.user_id != D.hold_facility_id(hold):
        fail("ERR_NOT_FACILITY_MANAGER",
             "BedManager X-User-ID does not equal the held bed's facility id.", 403)
    if hold["status"] != "ACTIVE":
        fail("ERR_HOLD_NOT_ACTIVE", "The bed hold is not ACTIVE.", 409)
    case = D.get_case(hold["transfer_case_id"])
    if case is None or case["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "The hold's case is not ACCEPTED.", 409)
    hold["status"] = "RELEASED"
    hold["release_reason"] = "MANUAL"
    bump(hold)
    bed = D.get_bed(hold["bed_id"])
    if bed is not None and bed["status"] == "HELD":
        bed["status"] = "AVAILABLE"
        bump(bed)
    if case["active_bed_hold_id"] == hold["id"]:
        case["active_bed_hold_id"] = None
        bump(case)
    D.evaluate_saturation(D.hold_facility_id(hold))
    return object_response(D.serialize_bed_hold(hold), 200)
