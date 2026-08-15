"""LeadershipTerm endpoints: succession-chained creation, get, list, resign."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, clock_now
from errors import (
    ApiError, ERR_ACTIVE_TERM_EXISTS, ERR_GROUP_NOT_ACTIVE,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND,
    ERR_NOT_GROUP_LEADER, ERR_PREDECESSOR_MISMATCH, ERR_TERM_LIMIT_EXCEEDED,
    ERR_TERM_TENURE_NOT_MET,
)
from middleware import authenticate, body, opt_str, req_dt, req_str, sort_and_page
from services import (
    LEADER_TENURE_DAYS, leadership_gap_cascade, new_entity, term_json, touch,
)
from util import ok_list, ok_object

bp = Blueprint("terms", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")


def get_term(term_id):
    t = STORE["terms"].get(term_id)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "leadership term not found")
    return t


@bp.post("/v1/leadership-terms")
def create_term():
    authenticate(("DeiAdmin",))
    data = body()
    group_id = req_str(data, "group_id")
    leader_employee_id = req_str(data, "leader_employee_id")
    ends_at = req_dt(data, "ends_at")
    predecessor_term_id = opt_str(data, "predecessor_term_id")
    now = clock_now()
    # 3 schema-range: expiry must be strictly after current logical time
    if ends_at <= now:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "ends_at must be strictly after the current time")
    # 4 existence: group first, then referenced predecessor
    group = STORE["groups"].get(group_id)
    if group is None:
        raise ApiError(ERR_NOT_FOUND, 404, "group not found")
    if predecessor_term_id is not None and predecessor_term_id not in STORE["terms"]:
        raise ApiError(ERR_NOT_FOUND, 404, "predecessor term not found")
    # 5 state
    if group["status"] != "ACTIVE":
        raise ApiError(ERR_GROUP_NOT_ACTIVE, 409, "group is not ACTIVE")
    # 6 referential: succession chain. The required predecessor is the prior
    # term with max(ends_at), tie-break max(created_at); the very first term
    # must carry a null predecessor.
    prior_terms = [t for t in STORE["terms"].values() if t["group_id"] == group_id]
    if prior_terms:
        expected = max(prior_terms, key=lambda t: (t["ends_at"], t["created_at"], t["_seq"]))
        if predecessor_term_id != expected["id"]:
            raise ApiError(ERR_PREDECESSOR_MISMATCH, 409,
                           "predecessor_term_id is not the latest prior term")
    else:
        if predecessor_term_id is not None:
            raise ApiError(ERR_PREDECESSOR_MISMATCH, 409,
                           "the first term of a group must not name a predecessor")
    # 7 temporal: single ACTIVE term per group
    if any(t["status"] == "ACTIVE" for t in prior_terms):
        raise ApiError(ERR_ACTIVE_TERM_EXISTS, 409,
                       "group already has an ACTIVE leadership term")
    # 8 constraints: 90-day membership tenure, then 2-term limit
    tenure_ready = any(
        m["group_id"] == group_id and m["employee_id"] == leader_employee_id
        and m["status"] == "ACTIVE"
        and m["joined_at"] <= now - timedelta(days=LEADER_TENURE_DAYS)
        for m in STORE["memberships"].values())
    if not tenure_ready:
        raise ApiError(ERR_TERM_TENURE_NOT_MET, 409,
                       "leader lacks an ACTIVE membership at least 90 days old")
    held = sum(1 for t in prior_terms if t["leader_employee_id"] == leader_employee_id)
    if held >= 2:
        raise ApiError(ERR_TERM_LIMIT_EXCEEDED, 409,
                       "employee already holds 2 terms in this group")
    t = new_entity("terms", {
        "group_id": group_id,
        "leader_employee_id": leader_employee_id,
        "predecessor_term_id": predecessor_term_id,
        "starts_at": now,
        "ends_at": ends_at,
        "status": "ACTIVE",
    })
    return ok_object(term_json(t), 201)


@bp.get("/v1/leadership-terms/<term_id>")
def read_term(term_id):
    authenticate(ALL_ROLES)
    return ok_object(term_json(get_term(term_id)))


@bp.get("/v1/leadership-terms")
def list_terms():
    authenticate(ALL_ROLES)
    items = list(STORE["terms"].values())
    for param, field in (("group_id", "group_id"),
                         ("employee_id", "leader_employee_id"),
                         ("predecessor_term_id", "predecessor_term_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t.get(field) == v]
    page, limit, offset, total = sort_and_page(items, term_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/leadership-terms/<term_id>/resign")
def resign_term(term_id):
    user_id, role = authenticate(("GroupLeader", "DeiAdmin"))
    t = get_term(term_id)
    if t["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "term is not ACTIVE")
    if role == "GroupLeader" and user_id != t["leader_employee_id"]:
        raise ApiError(ERR_NOT_GROUP_LEADER, 403, "caller does not hold this term")
    t["status"] = "RESIGNED"
    touch(t)
    leadership_gap_cascade(t["group_id"])
    return ok_object(term_json(t))
