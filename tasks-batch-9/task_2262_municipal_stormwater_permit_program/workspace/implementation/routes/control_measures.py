"""Minimum control measures: registration, progress reporting and retirement."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, new_row, touch
from errors import ApiError
from middleware import body, get_bool, get_enum, get_int, get_number, get_str, require
from routes.common import find, one, settle, snapshot
from services import calc, derive

bp = Blueprint("control_measures", __name__)


@bp.post("/control-measures")
def create_control_measure():
    require([mw.MANAGER])
    payload = body()
    term_id = get_str(payload, "permit_term_id")
    code = get_enum(payload, "measure_code", enums.MEASURE_CODE_SET)
    target = get_number(payload, "measurable_goal_target", minimum=0)
    weight = get_int(payload, "weight", required=False, default=1, minimum=1, maximum=5)
    salt = get_bool(payload, "salt_storage_covered", required=False, default=False)
    fleet = get_bool(payload, "fleet_wash_recycle", required=False, default=False)

    term = find("permit_terms", term_id)
    if derive.measure_by_code(term["id"], code) is not None:
        raise ApiError("ERR_DUPLICATE_MEASURE_CODE")

    row = new_row(
        {
            "permit_term_id": term["id"],
            "measure_code": code,
            "measurable_goal_target": calc.num(target, 2),
            "measurable_goal_actual": 0.00,
            "weight": weight,
            "status": "ACTIVE",
            "goal_status": "PENDING",
            "attainment_pct": 0.00,
            "open_case_count": 0,
            "enforcement_count": 0,
            "salt_storage_covered": salt,
            "fleet_wash_recycle": fleet,
            "swept_lane_miles_ytd": 0.00,
            "last_progress_reported_at": None,
        }
    )
    DB.control_measures[row["id"]] = row
    settle(term)
    return one(row, 201)


@bp.get("/control-measures/<measure_id>")
def read_control_measure(measure_id):
    require(mw.OPERATIONAL_ROLES)
    return one(find("control_measures", measure_id))


@bp.post("/control-measures/<measure_id>/report-progress")
def report_progress(measure_id):
    require([mw.MANAGER, mw.OPS])
    payload = body()
    actual = get_number(payload, "measurable_goal_actual", minimum=0)
    measure = find("control_measures", measure_id)
    if measure["status"] != "ACTIVE":
        raise ApiError("ERR_MEASURE_RETIRED")

    term = DB.permit_terms.get(measure["permit_term_id"])
    before = snapshot(term)
    measure["measurable_goal_actual"] = calc.num(actual, 2)
    measure["last_progress_reported_at"] = CLOCK.stamp()
    touch(measure)
    settle(term, before, CLOCK.now())
    return one(measure)


@bp.post("/control-measures/<measure_id>/retire")
def retire_control_measure(measure_id):
    require([mw.MANAGER])
    measure = find("control_measures", measure_id)
    if measure["status"] != "ACTIVE":
        raise ApiError("ERR_MEASURE_RETIRED")
    term = DB.permit_terms.get(measure["permit_term_id"])
    if term is not None and term["status"] == "ACTIVE":
        raise ApiError("ERR_MEASURE_RETIRED")

    measure["status"] = "RETIRED"
    touch(measure)
    settle(term)
    return one(measure)
