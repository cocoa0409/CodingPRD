"""AccidentRecord endpoints (PRD 3.7): register, preventability review."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_FUTURE_OCCURRENCE, ERR_DRIVER_CARRIER_MISMATCH,
    ERR_PREVENTABILITY_ALREADY_DETERMINED, ERR_SOD_PREVENTABILITY_SAME_USER,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import stamp_new, touch, recompute_driver_risk
from validate import (
    get_body, req_str, req_int, req_bool, opt_bool, req_enum, req_datetime,
    require_path_resource, require_ref,
)
from util import new_id, parse_datetime, CLOCK

bp = Blueprint("accidents", __name__)

DETERMINATIONS = ["PREVENTABLE", "NOT_PREVENTABLE"]


@bp.post("/safety/accident-records")
def create_accident():
    caller = authorized(["SafetyManager"])
    body = get_body()
    # Stage 3: shape
    carrier_id = req_str(body, "carrier_id")
    driver_id = req_str(body, "driver_id")
    occurred_at = req_datetime(body, "occurred_at")
    fatalities = req_int(body, "fatalities", minimum=0)
    injuries = req_int(body, "injuries", minimum=0)
    tow_away = req_bool(body, "tow_away")
    hazmat_release = opt_bool(body, "hazmat_release", default=False)
    # Stage 4: body FK existence in declared input order
    require_ref("carriers", carrier_id, "carrier_id")
    driver = require_ref("drivers", driver_id, "driver_id")
    # Stage 8: temporal
    if parse_datetime(occurred_at) > CLOCK.now():
        raise_error(ERR_FUTURE_OCCURRENCE, "occurred_at is in the future")
    # Stage 9: driver-carrier membership
    if driver["carrier_id"] != carrier_id:
        raise_error(ERR_DRIVER_CARRIER_MISMATCH, "driver does not belong to the carrier")
    accident = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "driver_id": driver_id,
        "occurred_at": occurred_at,
        "fatalities": fatalities,
        "injuries": injuries,
        "tow_away": tow_away,
        "hazmat_release": hazmat_release,
        "dot_reportable": calc.dot_reportable(fatalities, injuries, tow_away),
        "crash_points": calc.crash_points(fatalities, injuries, tow_away),
        "registered_by_user_id": caller.user_id,
        "preventability_status": "PENDING_REVIEW",
        "preventability_determined_by": None,
    })
    db["accident_records"][accident["id"]] = accident
    return success_object(public(accident), 201)


@bp.get("/safety/accident-records")
def list_accidents():
    return list_response("accident_records", filters={
        "carrier_id": request.args.get("carrier_id"),
        "driver_id": request.args.get("driver_id"),
        "preventability_status": request.args.get("preventability_status"),
    })


@bp.get("/safety/accident-records/<rid>")
def get_accident(rid):
    return get_one("accident_records", rid)


@bp.post("/safety/accident-records/<rid>/determine-preventability")
def determine_preventability(rid):
    caller = authorized(["SafetyDirector"])
    body = get_body()
    determination = req_enum(body, "determination", DETERMINATIONS)
    accident = require_path_resource("accident_records", rid)
    # Stage 5: state
    if accident["preventability_status"] != "PENDING_REVIEW":
        raise_error(ERR_PREVENTABILITY_ALREADY_DETERMINED,
                    "preventability has already been determined")
    # Stage 7: segregation of duties
    if caller.user_id == accident["registered_by_user_id"]:
        raise_error(ERR_SOD_PREVENTABILITY_SAME_USER,
                    "preventability determiner must differ from the accident registrar")
    accident["preventability_status"] = determination
    accident["preventability_determined_by"] = caller.user_id
    touch(accident)
    if determination == "PREVENTABLE":
        driver = db["drivers"].get(accident["driver_id"])
        if driver is not None:
            recompute_driver_risk(driver)
    return success_object(public(accident))
