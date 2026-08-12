"""HomeAssessment endpoints."""

from flask import Blueprint

import db
from errors import (ApiError, err_not_found, err_invalid_request,
                    err_invalid_state, err_invalid_measurement)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import stamp_new, touch, serialize, audit
from services.calculations import valid_rail_length_m
from services.sweeps import supersede_quotes_for_assessment

bp = Blueprint("home_assessments", __name__)

READ_ROLES = ("PlatformAdmin", "SalesRep", "Assessor", "AssessmentReviewer",
              "InstallCoordinator")


def _check_int_range(body, field, lo, hi):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_measurement(f"{field} missing or not an integer")
    if v < lo or v > hi:
        raise err_invalid_measurement(f"{field} out of range {lo}..{hi}")
    return v


@bp.post("/stairlift-ops/customers/<cid>/home-assessments")
def create_assessment(cid):
    user_id, role = require_role("SalesRep", "Assessor")
    customer = db.customers.get(cid)
    if customer is None:
        raise err_not_found("Customer not found")
    body = get_json_body(["scheduled_date"])
    if not isinstance(body["scheduled_date"], str):
        raise err_invalid_request("scheduled_date must be a string")
    # Supersede any prior SCHEDULED or MEASURED assessment for this customer
    for a in list(db.home_assessments.values()):
        if a["customer_id"] == cid and a["status"] in ("SCHEDULED", "MEASURED"):
            was_measured = a["status"] == "MEASURED"
            a["status"] = "SUPERSEDED"
            touch(a)
            audit("HomeAssessment", a["id"], "ASSESS_SUPERSEDED", "system",
                  {"from": "SCHEDULED/MEASURED", "to": "SUPERSEDED"})
            if was_measured:
                supersede_quotes_for_assessment(a["id"], "system")
    assessment = {
        "customer_id": cid,
        "scheduled_date": body["scheduled_date"],
        "status": "SCHEDULED",
        "staircase_kind": None,
        "stair_rise_mm": None,
        "stair_run_mm": None,
        "stair_width_mm": None,
        "landing_clearance_mm": None,
        "has_outdoor_exposure": False,
        "electrical_outlet_within_2m": None,
        "measured_at": None,
        "approved_at": None,
    }
    stamp_new(assessment)
    db.home_assessments[assessment["id"]] = assessment
    return success_object(serialize(assessment), 201)


@bp.get("/stairlift-ops/customers/<cid>/home-assessments")
def list_assessments(cid):
    require_role(*READ_ROLES)
    if cid not in db.customers:
        raise err_not_found("Customer not found")
    limit, offset = get_pagination()
    items = sorted(
        (a for a in db.home_assessments.values() if a["customer_id"] == cid),
        key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)


@bp.get("/stairlift-ops/home-assessments/<aid>")
def get_assessment(aid):
    require_role(*READ_ROLES)
    a = db.home_assessments.get(aid)
    if a is None:
        raise err_not_found("HomeAssessment not found")
    return success_object(serialize(a))


@bp.post("/stairlift-ops/home-assessments/<aid>/measure")
def measure_assessment(aid):
    user_id, role = require_role("Assessor")
    a = db.home_assessments.get(aid)
    if a is None:
        raise err_not_found("HomeAssessment not found")
    if a["status"] != "SCHEDULED":
        raise err_invalid_state("Assessment must be SCHEDULED to measure")
    body = get_json_body(["staircase_kind", "stair_rise_mm", "stair_run_mm",
                          "stair_width_mm", "landing_clearance_mm",
                          "electrical_outlet_within_2m"])
    kind = body["staircase_kind"]
    if kind not in ("STRAIGHT", "CURVED", "OUTDOOR"):
        raise err_invalid_measurement("staircase_kind invalid")
    rise = _check_int_range(body, "stair_rise_mm", 500, 6000)
    run = _check_int_range(body, "stair_run_mm", 500, 12000)
    width = _check_int_range(body, "stair_width_mm", 600, 1500)
    landing = _check_int_range(body, "landing_clearance_mm", 0, 3000)
    outlet = body["electrical_outlet_within_2m"]
    if not isinstance(outlet, bool):
        raise err_invalid_measurement("electrical_outlet_within_2m must be boolean")
    outdoor = body.get("has_outdoor_exposure", False)
    if not isinstance(outdoor, bool):
        raise err_invalid_measurement("has_outdoor_exposure must be boolean")
    # geometric safety: CURVED requires run >= 2 * rise
    if kind == "CURVED" and run < 2 * rise:
        raise err_invalid_measurement(
            "CURVED staircase requires stair_run_mm >= 2 * stair_rise_mm")
    a["staircase_kind"] = kind
    a["stair_rise_mm"] = rise
    a["stair_run_mm"] = run
    a["stair_width_mm"] = width
    a["landing_clearance_mm"] = landing
    a["has_outdoor_exposure"] = outdoor
    a["electrical_outlet_within_2m"] = outlet
    a["status"] = "MEASURED"
    a["measured_at"] = db.now_iso()
    touch(a)
    audit("HomeAssessment", a["id"], "ASSESS_MEASURED", role,
          {"to": "MEASURED"})
    return success_object(serialize(a))


@bp.post("/stairlift-ops/home-assessments/<aid>/approve")
def approve_assessment(aid):
    user_id, role = require_role("AssessmentReviewer")
    a = db.home_assessments.get(aid)
    if a is None:
        raise err_not_found("HomeAssessment not found")
    if a["status"] != "MEASURED":
        raise err_invalid_state("Assessment must be MEASURED to approve")
    body = get_json_body(["model_code"])
    model_code = body["model_code"]
    pm_id = db.product_models_by_code.get(model_code)
    if pm_id is None:
        raise err_not_found("ProductModel not found")
    pm = db.product_models[pm_id]
    # safety gates in priority order
    if a["stair_width_mm"] < pm["min_stair_width_mm"]:
        raise ApiError("ERR_STAIR_TOO_NARROW", 422,
                       "stair_width_mm below model minimum")
    if not a["electrical_outlet_within_2m"] and a["staircase_kind"] != "OUTDOOR":
        raise ApiError("ERR_NO_POWER_SOURCE", 422,
                       "No electrical outlet within 2m and staircase not OUTDOOR")
    if a["landing_clearance_mm"] < 500:
        raise ApiError("ERR_LANDING_CLEARANCE_TOO_SMALL", 422,
                       "landing_clearance_mm below 500")
    a["status"] = "APPROVED"
    a["approved_at"] = db.now_iso()
    touch(a)
    audit("HomeAssessment", a["id"], "ASSESS_APPROVED", role,
          {"to": "APPROVED", "model_code": model_code})
    return success_object(serialize(a))


@bp.post("/stairlift-ops/home-assessments/<aid>/reject")
def reject_assessment(aid):
    user_id, role = require_role("AssessmentReviewer")
    a = db.home_assessments.get(aid)
    if a is None:
        raise err_not_found("HomeAssessment not found")
    if a["status"] != "MEASURED":
        raise err_invalid_state("Assessment must be MEASURED to reject")
    a["status"] = "REJECTED"
    touch(a)
    audit("HomeAssessment", a["id"], "ASSESS_REJECTED", role,
          {"to": "REJECTED"})
    return success_object(serialize(a))
