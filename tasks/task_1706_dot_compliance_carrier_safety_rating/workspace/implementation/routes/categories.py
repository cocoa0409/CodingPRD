"""ViolationCategory endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_DUPLICATE_CATEGORY_CODE
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import stamp_new
from validate import get_body, req_str, req_int, req_enum, req_number, opt_int
from util import new_id

bp = Blueprint("categories", __name__)

ROLE = ["SafetyAdmin"]

CATEGORY_CODES = [
    "UNSAFE_DRIVING", "HOURS_OF_SERVICE", "DRIVER_FITNESS",
    "CONTROLLED_SUBSTANCES_ALCOHOL", "VEHICLE_MAINTENANCE", "HAZMAT",
    "CRASH_INDICATOR",
]


@bp.post("/safety/violation-categories")
def create_category():
    authorized(ROLE)
    body = get_body()
    category_code = req_enum(body, "category_code", CATEGORY_CODES)
    display_name = req_str(body, "display_name")
    intervention_threshold = req_int(body, "intervention_threshold", minimum=1, maximum=100)
    benchmark_measure = req_number(body, "benchmark_measure")
    if benchmark_measure <= 0:
        raise_error(ERR_INVALID_REQUEST, "benchmark_measure must be > 0")
    measure_window_months = opt_int(body, "measure_window_months", default=24, minimum=1)
    for c in db["violation_categories"].values():
        if c["category_code"] == category_code:
            raise_error(ERR_DUPLICATE_CATEGORY_CODE, "category_code already defined")
    category = stamp_new({
        "id": new_id(),
        "category_code": category_code,
        "display_name": display_name,
        "intervention_threshold": intervention_threshold,
        "benchmark_measure": benchmark_measure,
        "measure_window_months": measure_window_months,
    })
    db["violation_categories"][category["id"]] = category
    return success_object(public(category), 201)


@bp.get("/safety/violation-categories")
def list_categories():
    return list_response("violation_categories")


@bp.get("/safety/violation-categories/<rid>")
def get_category(rid):
    return get_one("violation_categories", rid)
