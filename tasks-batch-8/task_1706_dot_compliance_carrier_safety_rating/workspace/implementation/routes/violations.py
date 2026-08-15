"""InspectionViolation endpoints (PRD 3.3): record with time weighting."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_SEVERITY_WEIGHT,
    ERR_INSPECTION_FINALIZED, ERR_DRIVER_NOT_ACTIVE, ERR_FUTURE_OCCURRENCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import (
    stamp_new, recompute_inspection_total, recompute_driver_risk,
)
from validate import get_body, req_str, opt_str, req_datetime, require_ref
from util import new_id, parse_datetime, CLOCK

bp = Blueprint("violations", __name__)


@bp.post("/safety/inspection-violations")
def create_violation():
    authorized(["SafetyManager"])
    body = get_body()
    # Stage 3: shape
    inspection_id = req_str(body, "inspection_id")
    category_id = req_str(body, "category_id")
    violation_code = req_str(body, "violation_code")
    sw = body.get("severity_weight")
    if sw is None or isinstance(sw, bool) or not isinstance(sw, int):
        raise_error(ERR_INVALID_REQUEST, "missing or invalid integer field: severity_weight")
    if sw < 1 or sw > 10:
        raise_error(ERR_INVALID_SEVERITY_WEIGHT, "severity_weight must be between 1 and 10")
    occurred_at = req_datetime(body, "occurred_at")
    driver_id = opt_str(body, "driver_id")
    # Stage 4: body FK existence in declared input order
    insp = require_ref("roadside_inspections", inspection_id, "inspection_id")
    require_ref("violation_categories", category_id, "category_id")
    if driver_id is not None:
        driver = require_ref("drivers", driver_id, "driver_id")
    else:
        driver = db["drivers"].get(insp["driver_id"])
    # Stage 5: state — inspection not FINALIZED; cited driver ACTIVE
    if insp["review_status"] == "FINALIZED":
        raise_error(ERR_INSPECTION_FINALIZED, "inspection is FINALIZED")
    if driver is None or driver["employment_status"] != "ACTIVE":
        raise_error(ERR_DRIVER_NOT_ACTIVE, "cited driver must be ACTIVE")
    # Stage 8: temporal
    occurred = parse_datetime(occurred_at)
    if occurred > CLOCK.now():
        raise_error(ERR_FUTURE_OCCURRENCE, "occurred_at is in the future")
    multiplier = calc.time_weight(occurred, CLOCK.now())
    violation = stamp_new({
        "id": new_id(),
        "inspection_id": inspection_id,
        "category_id": category_id,
        "driver_id": driver["id"],
        "violation_code": violation_code,
        "severity_weight": sw,
        "occurred_at": occurred_at,
        "time_weight_multiplier": multiplier,
        "weighted_points": sw * multiplier,
        "status": "ACTIVE",
    })
    db["inspection_violations"][violation["id"]] = violation
    recompute_inspection_total(insp)
    recompute_driver_risk(driver)
    return success_object(public(violation), 201)


@bp.get("/safety/inspection-violations")
def list_violations():
    return list_response("inspection_violations", filters={
        "inspection_id": request.args.get("inspection_id"),
        "category_id": request.args.get("category_id"),
        "driver_id": request.args.get("driver_id"),
        "status": request.args.get("status"),
    })


@bp.get("/safety/inspection-violations/<rid>")
def get_violation(rid):
    return get_one("inspection_violations", rid)
