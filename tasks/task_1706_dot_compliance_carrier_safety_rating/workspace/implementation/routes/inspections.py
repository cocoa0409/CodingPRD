"""RoadsideInspection endpoints (PRD 3.3): import, review workflow, finalize."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_FUTURE_OCCURRENCE, ERR_DUPLICATE_REPORT_NUMBER,
    ERR_DRIVER_CARRIER_MISMATCH, ERR_INSPECTION_NOT_REVIEWABLE,
    ERR_OPEN_CHALLENGES_BLOCK_FINALIZE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import stamp_new, touch, OPEN_CHALLENGE_STATES
from validate import get_body, req_str, req_int, req_datetime, require_path_resource, require_ref
from util import new_id, parse_datetime, CLOCK

bp = Blueprint("inspections", __name__)


@bp.post("/safety/roadside-inspections")
def create_inspection():
    authorized(["SafetyManager"])
    body = get_body()
    # Stage 3: shape
    carrier_id = req_str(body, "carrier_id")
    driver_id = req_str(body, "driver_id")
    report_number = req_str(body, "report_number")
    inspection_date = req_datetime(body, "inspection_date")
    inspection_level = req_int(body, "inspection_level", minimum=1, maximum=3)
    state_code = req_str(body, "state_code")
    # Stage 4: body FK existence in declared input order
    require_ref("carriers", carrier_id, "carrier_id")
    driver = require_ref("drivers", driver_id, "driver_id")
    # Stage 8: temporal
    if parse_datetime(inspection_date) > CLOCK.now():
        raise_error(ERR_FUTURE_OCCURRENCE, "inspection_date is in the future")
    # Stage 9: uniqueness, then driver-carrier membership
    for i in db["roadside_inspections"].values():
        if i["carrier_id"] == carrier_id and i["report_number"] == report_number:
            raise_error(ERR_DUPLICATE_REPORT_NUMBER, "report_number already exists for the carrier")
    if driver["carrier_id"] != carrier_id:
        raise_error(ERR_DRIVER_CARRIER_MISMATCH, "driver does not belong to the carrier")
    insp = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "driver_id": driver_id,
        "report_number": report_number,
        "inspection_date": inspection_date,
        "inspection_level": inspection_level,
        "state_code": state_code,
        "review_status": "IMPORTED",
        "total_weighted_points": 0,
    })
    db["roadside_inspections"][insp["id"]] = insp
    return success_object(public(insp), 201)


@bp.get("/safety/roadside-inspections")
def list_inspections():
    return list_response("roadside_inspections", filters={
        "carrier_id": request.args.get("carrier_id"),
        "driver_id": request.args.get("driver_id"),
        "review_status": request.args.get("review_status"),
    })


@bp.get("/safety/roadside-inspections/<rid>")
def get_inspection(rid):
    return get_one("roadside_inspections", rid)


@bp.post("/safety/roadside-inspections/<rid>/begin-review")
def begin_review(rid):
    authorized(["ComplianceAnalyst"])
    insp = require_path_resource("roadside_inspections", rid)
    if insp["review_status"] != "IMPORTED":
        raise_error(ERR_INSPECTION_NOT_REVIEWABLE, "begin-review requires IMPORTED")
    insp["review_status"] = "UNDER_REVIEW"
    touch(insp)
    return success_object(public(insp))


@bp.post("/safety/roadside-inspections/<rid>/finalize")
def finalize(rid):
    authorized(["ComplianceAnalyst"])
    insp = require_path_resource("roadside_inspections", rid)
    if insp["review_status"] != "UNDER_REVIEW":
        raise_error(ERR_INSPECTION_NOT_REVIEWABLE, "finalize requires UNDER_REVIEW")
    # Stage 10: open challenges on any violation of this inspection block finalize
    violation_ids = {
        v["id"] for v in db["inspection_violations"].values()
        if v["inspection_id"] == insp["id"]
    }
    for ch in db["dataqs_challenges"].values():
        if ch["violation_id"] in violation_ids and ch["status"] in OPEN_CHALLENGE_STATES:
            raise_error(ERR_OPEN_CHALLENGES_BLOCK_FINALIZE,
                        "an open DataQs challenge exists on this inspection")
    insp["review_status"] = "FINALIZED"
    touch(insp)
    return success_object(public(insp))
