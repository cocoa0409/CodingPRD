"""SiteSurvey endpoints (PRD 3.1)."""

from flask import Blueprint, g

import db
from errors import (
    ApiError, ERR_NOT_ASSIGNED_SURVEYOR, ERR_PROPERTY_NOT_FOUND,
    ERR_SURVEY_NOT_FOUND, ERR_SURVEY_STATE_FORBIDS, ERR_TECHNICIAN_NOT_ACTIVE,
    ERR_TECHNICIAN_NOT_FOUND, invalid_request, state_forbids,
)
from middleware import PROJECT_COORDINATOR, SURVEYOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc
from util import get_json_body, serialize, validate_body

bp = Blueprint("surveys", __name__)

CREATE_SPEC = {
    "property_id": ("string", True, None),
    "surveyor_technician_id": ("string", True, None),
    "scheduled_date": ("datetime", True, None),
}

COMPLETE_SPEC = {
    "measured_pit_depth_inches": ("number", True, None),
    "measured_overhead_clearance_inches": ("number", True, None),
    "shaft_width_inches": ("number", True, None),
    "shaft_depth_inches": ("number", True, None),
    "floors_served": ("int", True, None),
}


@bp.post("/api/surveys")
@require_roles(PROJECT_COORDINATOR)
def create_survey():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    # body foreign-key references
    get_or_404(db.properties, vals["property_id"], ERR_PROPERTY_NOT_FOUND, "Property")
    technician = get_or_404(db.technicians, vals["surveyor_technician_id"], ERR_TECHNICIAN_NOT_FOUND, "Technician")
    # referenced technician must be ACTIVE
    if technician["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, 409, "Referenced technician is INACTIVE")
    rec = db.new_record({
        "property_id": vals["property_id"],
        "surveyor_technician_id": vals["surveyor_technician_id"],
        "scheduled_date": vals["scheduled_date"],
        "measured_pit_depth_inches": None,
        "measured_overhead_clearance_inches": None,
        "shaft_width_inches": None,
        "shaft_depth_inches": None,
        "floors_served": None,
        "feasibility_verdict": None,
        "status": "SCHEDULED",
    })
    db.surveys[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/surveys")
@require_roles(*ALL_ROLES)
def list_surveys():
    return list_endpoint(db.surveys, {
        "property_id": "property_id",
        "surveyor_technician_id": "surveyor_technician_id",
        "status": "status",
    })


@bp.get("/api/surveys/<surveyId>")
@require_roles(*ALL_ROLES)
def get_survey(surveyId):
    rec = get_or_404(db.surveys, surveyId, ERR_SURVEY_NOT_FOUND, "Survey")
    return ok(serialize(rec))


@bp.post("/api/surveys/<surveyId>/complete")
@require_roles(SURVEYOR)
def complete_survey(surveyId):
    survey = get_or_404(db.surveys, surveyId, ERR_SURVEY_NOT_FOUND, "Survey")
    vals = validate_body(get_json_body(), COMPLETE_SPEC)
    if vals["floors_served"] < 2:
        raise invalid_request("Field 'floors_served' must be at least 2")
    # state admission (priority 5) before identity binding (priority 7)
    if survey["status"] != "SCHEDULED":
        raise state_forbids(ERR_SURVEY_STATE_FORBIDS, "Survey")
    if g.user_id != survey["surveyor_technician_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_SURVEYOR, 403, "Caller is not the assigned surveyor")
    survey["measured_pit_depth_inches"] = vals["measured_pit_depth_inches"]
    survey["measured_overhead_clearance_inches"] = vals["measured_overhead_clearance_inches"]
    survey["shaft_width_inches"] = vals["shaft_width_inches"]
    survey["shaft_depth_inches"] = vals["shaft_depth_inches"]
    survey["floors_served"] = vals["floors_served"]
    survey["feasibility_verdict"] = calc.feasibility_verdict(list(db.product_models.values()), survey)
    survey["status"] = "COMPLETED"
    db.touch(survey)
    return ok(serialize(survey))


@bp.post("/api/surveys/<surveyId>/cancel")
@require_roles(PROJECT_COORDINATOR)
def cancel_survey(surveyId):
    survey = get_or_404(db.surveys, surveyId, ERR_SURVEY_NOT_FOUND, "Survey")
    if survey["status"] != "SCHEDULED":
        raise state_forbids(ERR_SURVEY_STATE_FORBIDS, "Survey")
    survey["status"] = "CANCELLED"
    db.touch(survey)
    return ok(serialize(survey))
