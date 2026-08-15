"""Survey action endpoints (PRD §3.9)."""

from flask import Blueprint

import calc
from auth import require_roles
from db import store
from errors import (ApiError, ERR_SURVEY_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
                    ERR_INVALID_SURVEY_STATE)
from helpers import touch, get_or_404, ser_survey
from util import success, get_body, req_present, as_rating

bp = Blueprint("surveys", __name__)


@bp.post("/api/surveys/<sid>/submit")
def submit_survey(sid):
    uid, _ = require_roles("NewHire")
    body = get_body()
    experience = as_rating(req_present(body, "onboarding_experience_rating"),
                           "onboarding_experience_rating")
    manager = as_rating(req_present(body, "manager_support_rating"),
                        "manager_support_rating")
    resources = as_rating(req_present(body, "resources_rating"),
                          "resources_rating")
    sv = get_or_404("surveys", sid, ERR_SURVEY_NOT_FOUND, "Survey")
    case = store["cases"][sv["case_id"]]
    # Stage 5: ownership
    if case["new_hire_id"] != uid:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "NewHire may only submit the survey of its own case")
    # Stage 6: only while SENT
    if sv["status"] != "SENT":
        raise ApiError(ERR_INVALID_SURVEY_STATE, 409,
                       "submit requires a SENT survey")
    sv["onboarding_experience_rating"] = experience
    sv["manager_support_rating"] = manager
    sv["resources_rating"] = resources
    sv["overall_score"] = calc.survey_overall_score(experience, manager,
                                                    resources)
    sv["status"] = "SUBMITTED"
    touch(sv)
    return success(ser_survey(sv))
