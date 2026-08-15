"""Driver endpoints (PRD 3.2): roster create/list/get, terminate, reinstate."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_DRIVER_NOT_ACTIVE, ERR_DRIVER_NOT_SUSPENDED,
    ERR_REINSTATE_REQUIREMENTS_UNMET,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import stamp_new, touch, OPEN_COACHING_STATES
from validate import get_body, req_str, req_datetime, require_path_resource, require_ref
from util import new_id

bp = Blueprint("drivers", __name__)

ROLE = ["SafetyManager"]


@bp.post("/safety/drivers")
def create_driver():
    authorized(ROLE)
    body = get_body()
    carrier_id = req_str(body, "carrier_id")
    cdl_number = req_str(body, "cdl_number")
    full_name = req_str(body, "full_name")
    hire_date = req_datetime(body, "hire_date")
    require_ref("carriers", carrier_id, "carrier_id")
    driver = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "cdl_number": cdl_number,
        "full_name": full_name,
        "hire_date": hire_date,
        "employment_status": "ACTIVE",
        "risk_score": 0,
        "risk_tier": "LOW",
        "coaching_strikes": 0,
    })
    db["drivers"][driver["id"]] = driver
    return success_object(public(driver), 201)


@bp.get("/safety/drivers")
def list_drivers():
    return list_response("drivers", filters={
        "carrier_id": request.args.get("carrier_id"),
        "employment_status": request.args.get("employment_status"),
        "risk_tier": request.args.get("risk_tier"),
    })


@bp.get("/safety/drivers/<rid>")
def get_driver(rid):
    return get_one("drivers", rid)


@bp.post("/safety/drivers/<rid>/terminate")
def terminate_driver(rid):
    authorized(ROLE)
    driver = require_path_resource("drivers", rid)
    if driver["employment_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_DRIVER_NOT_ACTIVE, "driver is not ACTIVE or SUSPENDED")
    driver["employment_status"] = "TERMINATED"
    touch(driver)
    # Cascade: cancel every open coaching assignment (no reinstatement evaluation).
    for c in db["coaching_assignments"].values():
        if c["driver_id"] == driver["id"] and c["status"] in OPEN_COACHING_STATES:
            c["status"] = "CANCELLED"
            touch(c)
    return success_object(public(driver))


@bp.post("/safety/drivers/<rid>/reinstate")
def reinstate_driver(rid):
    authorized(ROLE)
    driver = require_path_resource("drivers", rid)
    if driver["employment_status"] != "SUSPENDED":
        raise_error(ERR_DRIVER_NOT_SUSPENDED, "reinstate requires employment_status SUSPENDED")
    if calc.suspension_hold_count(driver) != 0:
        raise_error(ERR_REINSTATE_REQUIREMENTS_UNMET, "suspension holds remain")
    driver["employment_status"] = "ACTIVE"
    touch(driver)
    return success_object(public(driver))
