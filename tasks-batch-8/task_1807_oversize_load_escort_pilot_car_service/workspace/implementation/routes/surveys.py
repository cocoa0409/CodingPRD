"""RouteSurvey submit/accept and obstruction listing."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_SURVEY_NOT_FOUND,
    ERR_SURVEY_INVALID_STATE,
    ERR_STALE_LEG_VERSION,
    raise_err,
)
from middleware import require_roles, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_survey, ser_obstruction
from services import calc, cascade
from util import (
    body_json, req_int, req_enum, require_field, new_id, is_int, is_number,
)

bp = Blueprint("surveys", __name__)


def _get_survey_or_404(survey_id):
    survey = db.surveys.get(survey_id)
    if survey is None:
        raise_err(ERR_SURVEY_NOT_FOUND, f"Survey {survey_id} not found")
    return survey


@bp.get("/route-surveys/<id>")
def get_survey(id):
    require_roles(*ALL_ROLES)
    return success_object(ser_survey(_get_survey_or_404(id)))


def _validate_obstruction(el, idx):
    if not isinstance(el, dict):
        raise_err(ERR_INVALID_REQUEST, f"obstructions[{idx}] must be an object")
    milepost = require_field(el, "milepost")
    if not is_number(milepost) or milepost < 0:
        raise_err(ERR_INVALID_REQUEST, f"obstructions[{idx}].milepost must be a number >= 0")
    obstruction_type = req_enum(el, "obstruction_type", calc.OBSTRUCTION_TYPES)
    measured = require_field(el, "measured_clearance_inches")
    if not is_int(measured) or measured < 0:
        raise_err(ERR_INVALID_REQUEST,
                  f"obstructions[{idx}].measured_clearance_inches must be an integer >= 0")
    disposition = req_enum(el, "disposition", calc.OBSTRUCTION_DISPOSITIONS)
    return {
        "milepost": milepost,
        "obstruction_type": obstruction_type,
        "measured_clearance_inches": measured,
        "disposition": disposition,
    }


@bp.post("/route-surveys/<id>/submit")
def submit_survey(id):
    require_roles("RouteSurveyor")
    data = body_json(request)
    clearance = req_int(data, "surveyed_min_clearance_inches", min_v=0)
    obstructions_in = data.get("obstructions")
    if obstructions_in is None:
        obstructions_in = []
    if not isinstance(obstructions_in, list):
        raise_err(ERR_INVALID_REQUEST, "obstructions must be an array")
    specs = [_validate_obstruction(el, i) for i, el in enumerate(obstructions_in)]

    survey = _get_survey_or_404(id)
    if survey["survey_status"] != "REQUESTED":
        raise_err(ERR_SURVEY_INVALID_STATE, "Submission requires the survey to be REQUESTED")
    n = db.now()
    survey["surveyed_min_clearance_inches"] = clearance
    survey["submitted_at"] = n
    survey["survey_status"] = "SUBMITTED"
    mark(survey)
    for spec in specs:
        obstruction = {
            "id": new_id(),
            "created_at": n,
            "_seq": db.next_seq(),
            "survey_id": survey["id"],
            "milepost": spec["milepost"],
            "obstruction_type": spec["obstruction_type"],
            "measured_clearance_inches": spec["measured_clearance_inches"],
            "disposition": spec["disposition"],
        }
        db.obstructions[obstruction["id"]] = obstruction
    # Provisional mirror onto the leg; per the scaffold transition table this does
    # not bump the leg's version (verdict stays UNKNOWN until a decision).
    leg = db.legs.get(survey["leg_id"])
    if leg is not None:
        leg["survey_min_clearance_inches"] = clearance
    return success_object(ser_survey(survey))


@bp.post("/route-surveys/<id>/accept")
def accept_survey(id):
    uid, _role = require_roles("SafetyManager")
    data = body_json(request)
    expected_leg_version = req_int(data, "expected_leg_version")
    outcome = req_enum(data, "outcome", calc.SURVEY_OUTCOMES)
    rejection_reason = None
    if outcome == "REJECTED":
        rejection_reason = data.get("rejection_reason")
        if not isinstance(rejection_reason, str) or rejection_reason.strip() == "":
            raise_err(ERR_INVALID_REQUEST, "rejection_reason is required when outcome is REJECTED")

    survey = _get_survey_or_404(id)
    if survey["survey_status"] != "SUBMITTED":
        raise_err(ERR_SURVEY_INVALID_STATE, "A decision requires the survey to be SUBMITTED")
    leg = db.legs.get(survey["leg_id"])
    if expected_leg_version != leg["version"]:
        raise_err(ERR_STALE_LEG_VERSION,
                  "expected_leg_version does not match the leg's current version")

    n = db.now()
    survey["decided_at"] = n
    survey["decided_by_user_id"] = uid
    if outcome == "REJECTED":
        survey["rejection_reason"] = rejection_reason
        survey["survey_status"] = "REJECTED"
        mark(survey)
        mark(leg)
        return success_object(ser_survey(survey))

    # ACCEPTED
    survey["survey_status"] = "ACCEPTED"
    mark(survey)
    for prior in cascade.surveys_of_leg(leg["id"]):
        if prior["id"] != survey["id"] and prior["survey_status"] == "ACCEPTED":
            prior["survey_status"] = "SUPERSEDED"
            mark(prior)
    job = cascade.job_of_leg(leg)
    leg["survey_min_clearance_inches"] = survey["surveyed_min_clearance_inches"]
    verdict = calc.clearance_verdict_for(job["height_inches"], survey["surveyed_min_clearance_inches"])
    leg["clearance_verdict"] = verdict
    mark(leg)
    if verdict == "FAIL":
        cascade.block_leg_and_demote(leg)
    else:
        cascade.promote_leg(leg, ("DETERMINED", "BLOCKED"))
        cascade.reevaluate_job_clearance(job)
    return success_object(ser_survey(survey))


@bp.get("/route-surveys/<id>/obstructions")
def list_survey_obstructions(id):
    require_roles(*ALL_ROLES)
    survey = _get_survey_or_404(id)
    rows = [o for o in db.obstructions.values() if o["survey_id"] == survey["id"]]
    rows.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return paginate(request, [ser_obstruction(o) for o in rows])
