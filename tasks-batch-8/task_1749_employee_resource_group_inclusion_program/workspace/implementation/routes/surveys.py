"""ClimateSurvey and SurveyResponse endpoints."""
import uuid
from decimal import Decimal

from flask import Blueprint, request

from db import STORE, clock_now, next_seq
from errors import (
    ApiError, ERR_DUPLICATE_RESPONSE, ERR_INVALID_STATE_TRANSITION,
    ERR_MIN_RESPONSES_NOT_MET, ERR_NOT_FOUND, ERR_PROGRAM_NOT_OPEN,
    ERR_SURVEY_ALREADY_OPEN, ERR_SURVEY_NOT_OPEN, ERR_SURVEY_WINDOW_CLOSED,
)
from middleware import (
    authenticate, body, req_dt, req_int, req_str, sort_and_page,
)
from services import (
    CLIMATE_THRESHOLD, compute_response_score, mean_score_2dp, new_entity,
    response_json, survey_json, survey_responses, touch,
)
from util import ok_list, ok_object

bp = Blueprint("surveys", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")


def get_survey(survey_id):
    s = STORE["surveys"].get(survey_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "survey not found")
    return s


def get_response(response_id):
    r = STORE["responses"].get(response_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "survey response not found")
    return r


@bp.post("/v1/climate-surveys")
def create_survey():
    authenticate(("DeiAdmin",))
    data = body()
    program_id = req_str(data, "program_id")
    title = req_str(data, "title")
    opens_at = req_dt(data, "opens_at")
    closes_at = req_dt(data, "closes_at")
    min_responses = req_int(data, "min_responses", min_v=1)
    if closes_at <= opens_at:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "closes_at must be after opens_at")
    program = STORE["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "program not found")
    s = new_entity("surveys", {
        "program_id": program_id,
        "title": title,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "min_responses": min_responses,
        "status": "DRAFT",
        "final_index": None,
    })
    return ok_object(survey_json(s), 201)


@bp.get("/v1/climate-surveys/<survey_id>")
def read_survey(survey_id):
    authenticate(ALL_ROLES)
    return ok_object(survey_json(get_survey(survey_id)))


@bp.get("/v1/climate-surveys")
def list_surveys():
    authenticate(ALL_ROLES)
    items = list(STORE["surveys"].values())
    for param, field in (("program_id", "program_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(field) == v]
    page, limit, offset, total = sort_and_page(items, survey_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/climate-surveys/<survey_id>/open")
def open_survey(survey_id):
    authenticate(("DeiAdmin",))
    s = get_survey(survey_id)
    if s["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only a DRAFT survey can be opened")
    program = STORE["programs"].get(s["program_id"])
    if program is None or program["status"] not in ("OPEN", "ALLOCATION_LOCKED"):
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not open")
    for other in STORE["surveys"].values():
        if (other["program_id"] == s["program_id"] and other["id"] != s["id"]
                and other["status"] == "OPEN"):
            raise ApiError(ERR_SURVEY_ALREADY_OPEN, 409,
                           "another survey of this program is already OPEN")
    s["status"] = "OPEN"
    touch(s)
    return ok_object(survey_json(s))


@bp.post("/v1/climate-surveys/<survey_id>/close")
def close_survey(survey_id):
    authenticate(("DeiAdmin",))
    s = get_survey(survey_id)
    if s["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only an OPEN survey can be closed")
    responses = survey_responses(s["id"])
    if len(responses) < s["min_responses"]:
        raise ApiError(ERR_MIN_RESPONSES_NOT_MET, 409,
                       "fewer than min_responses responses received")
    s["final_index"] = mean_score_2dp([r["response_score"] for r in responses])
    s["status"] = "CLOSED"
    touch(s)
    # Posture cascade: strictly below the 3.00 threshold flips the program
    # into CLIMATE_REVIEW; exactly 3.00 leaves posture untouched.
    if Decimal(str(s["final_index"])) < CLIMATE_THRESHOLD:
        program = STORE["programs"].get(s["program_id"])
        if program is not None and program["posture"] != "CLIMATE_REVIEW":
            program["posture"] = "CLIMATE_REVIEW"
            touch(program)
    return ok_object(survey_json(s))


# ---------------------------------------------------------------------------
# Survey responses (SurveyResponse has id + created_at only; no version)
# ---------------------------------------------------------------------------
@bp.post("/v1/survey-responses")
def create_response():
    user_id, _ = authenticate(("Employee",))
    data = body()
    survey_id = req_str(data, "survey_id")
    belonging = req_int(data, "belonging_score", min_v=1, max_v=5)
    growth = req_int(data, "growth_score", min_v=1, max_v=5)
    fairness = req_int(data, "fairness_score", min_v=1, max_v=5)
    safety = req_int(data, "safety_score", min_v=1, max_v=5)
    s = STORE["surveys"].get(survey_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "survey not found")
    if s["status"] != "OPEN":
        raise ApiError(ERR_SURVEY_NOT_OPEN, 409, "survey is not OPEN")
    now = clock_now()
    if not (s["opens_at"] <= now < s["closes_at"]):
        raise ApiError(ERR_SURVEY_WINDOW_CLOSED, 409,
                       "response is outside the survey window")
    for r in STORE["responses"].values():
        if r["survey_id"] == survey_id and r["respondent_employee_id"] == user_id:
            raise ApiError(ERR_DUPLICATE_RESPONSE, 409,
                           "respondent already answered this survey")
    resp = {
        "id": str(uuid.uuid4()),
        "survey_id": survey_id,
        "respondent_employee_id": user_id,
        "belonging_score": belonging,
        "growth_score": growth,
        "fairness_score": fairness,
        "safety_score": safety,
        "response_score": compute_response_score(belonging, growth, fairness, safety),
        "created_at": now,
        "_seq": next_seq(),
    }
    STORE["responses"][resp["id"]] = resp
    return ok_object(response_json(resp), 201)


@bp.get("/v1/survey-responses/<response_id>")
def read_response(response_id):
    authenticate(ALL_ROLES)
    return ok_object(response_json(get_response(response_id)))


@bp.get("/v1/survey-responses")
def list_responses():
    authenticate(ALL_ROLES)
    items = list(STORE["responses"].values())
    for param, field in (("survey_id", "survey_id"),
                         ("employee_id", "respondent_employee_id")):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(field) == v]
    page, limit, offset, total = sort_and_page(items, response_json)
    return ok_list(page, limit, offset, total)
