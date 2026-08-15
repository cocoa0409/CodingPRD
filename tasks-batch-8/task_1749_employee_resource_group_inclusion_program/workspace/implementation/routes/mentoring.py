"""MentoringEngagement endpoints: propose / sponsor decision / complete."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError, ERR_INVALID_STATE_TRANSITION, ERR_MENTEE_ALREADY_ENGAGED,
    ERR_MENTORING_SELF_PAIRING, ERR_MENTORING_WINDOW_CONFLICT, ERR_NOT_FOUND,
    ERR_PROGRAM_NOT_OPEN, ERR_SPONSOR_CAPACITY_EXCEEDED, ERR_SPONSOR_NOT_ACTIVE,
    ERR_SPONSOR_NOT_ASSIGNED,
)
from middleware import (
    authenticate, body, opt_str, req_dt, req_enum, req_str, sort_and_page,
)
from services import MENTOR_BUFFER_DAYS, engagement_json, new_entity, touch
from util import ok_list, ok_object

bp = Blueprint("mentoring", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")
OPEN_ENGAGEMENT_STATUSES = ("PROPOSED", "ACTIVE")


def get_engagement(engagement_id):
    e = STORE["engagements"].get(engagement_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "mentoring engagement not found")
    return e


@bp.post("/v1/mentoring-engagements")
def create_engagement():
    user_id, role = authenticate(("Employee", "DeiAdmin"))
    data = body()
    program_id = req_str(data, "program_id")
    sponsor_id = req_str(data, "sponsor_id")
    mentee_input = opt_str(data, "mentee_employee_id")
    starts_at = req_dt(data, "starts_at")
    ends_at = req_dt(data, "ends_at")
    if ends_at <= starts_at:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "ends_at must be after starts_at")
    mentee = mentee_input if (role == "DeiAdmin" and mentee_input) else user_id
    # 4 existence
    program = STORE["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "program not found")
    sponsor = STORE["sponsors"].get(sponsor_id)
    if sponsor is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sponsor not found")
    # 5 state
    if program["status"] not in ("OPEN", "ALLOCATION_LOCKED"):
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not open")
    if sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_NOT_ACTIVE, 409, "sponsor is not ACTIVE")
    open_engagements = [e for e in STORE["engagements"].values()
                        if e["sponsor_id"] == sponsor_id
                        and e["status"] in OPEN_ENGAGEMENT_STATUSES]
    # 7 temporal: buffered-window conflict per sponsor. A start exactly at
    # existing.ends_at + 14 days is allowed (strict inequality).
    buffer = timedelta(days=MENTOR_BUFFER_DAYS)
    for e in open_engagements:
        if starts_at < e["ends_at"] + buffer and e["starts_at"] < ends_at + buffer:
            raise ApiError(ERR_MENTORING_WINDOW_CONFLICT, 409,
                           "sponsor has a conflicting engagement within the buffer")
    # 8 constraints: self-pairing (400), mentee single engagement
    if sponsor["employee_id"] == mentee:
        raise ApiError(ERR_MENTORING_SELF_PAIRING, 400,
                       "sponsor cannot mentor themselves")
    for e in STORE["engagements"].values():
        if (e["mentee_employee_id"] == mentee
                and e["status"] in OPEN_ENGAGEMENT_STATUSES):
            raise ApiError(ERR_MENTEE_ALREADY_ENGAGED, 409,
                           "mentee already has an open engagement")
    # 9 capacity
    if len(open_engagements) >= sponsor["max_mentees"]:
        raise ApiError(ERR_SPONSOR_CAPACITY_EXCEEDED, 409,
                       "sponsor is at the maximum number of mentees")
    e = new_entity("engagements", {
        "program_id": program_id,
        "sponsor_id": sponsor_id,
        "mentee_employee_id": mentee,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "PROPOSED",
    })
    return ok_object(engagement_json(e), 201)


@bp.get("/v1/mentoring-engagements/<engagement_id>")
def read_engagement(engagement_id):
    authenticate(ALL_ROLES)
    return ok_object(engagement_json(get_engagement(engagement_id)))


@bp.get("/v1/mentoring-engagements")
def list_engagements():
    authenticate(ALL_ROLES)
    items = list(STORE["engagements"].values())
    for param, field in (("program_id", "program_id"), ("sponsor_id", "sponsor_id"),
                         ("mentee_employee_id", "mentee_employee_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(field) == v]
    page, limit, offset, total = sort_and_page(items, engagement_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/mentoring-engagements/<engagement_id>/sponsor-decision")
def engagement_sponsor_decision(engagement_id):
    user_id, _ = authenticate(("ExecutiveSponsor",))
    data = body()
    decision = req_enum(data, "decision", ("ACCEPT", "DECLINE"))
    e = get_engagement(engagement_id)
    if e["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "sponsor decision requires a PROPOSED engagement")
    sponsor = STORE["sponsors"].get(user_id)
    if decision == "ACCEPT" and sponsor is not None and sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_NOT_ACTIVE, 409, "sponsor is not ACTIVE")
    if e["sponsor_id"] != user_id:
        raise ApiError(ERR_SPONSOR_NOT_ASSIGNED, 409,
                       "caller is not the engagement's sponsor")
    e["status"] = "ACTIVE" if decision == "ACCEPT" else "DECLINED"
    touch(e)
    return ok_object(engagement_json(e))


@bp.post("/v1/mentoring-engagements/<engagement_id>/complete")
def complete_engagement(engagement_id):
    user_id, role = authenticate(("ExecutiveSponsor", "DeiAdmin"))
    data = body()
    outcome = req_enum(data, "outcome", ("COMPLETED", "EARLY_TERMINATED"))
    e = get_engagement(engagement_id)
    if e["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "only an ACTIVE engagement can be completed")
    if role == "ExecutiveSponsor" and e["sponsor_id"] != user_id:
        raise ApiError(ERR_SPONSOR_NOT_ASSIGNED, 409,
                       "caller is not the engagement's sponsor")
    e["status"] = outcome
    touch(e)
    return ok_object(engagement_json(e))
