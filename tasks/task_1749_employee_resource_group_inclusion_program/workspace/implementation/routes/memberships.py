"""GroupMembership endpoints: join (upsert), get, list, leave."""
from flask import Blueprint, request

from db import STORE, clock_now
from errors import (
    ApiError, ERR_ALREADY_MEMBER, ERR_GROUP_NOT_ACCEPTING_MEMBERS,
    ERR_INVALID_STATE_TRANSITION, ERR_NOT_FOUND, ERR_NOT_GROUP_LEADER,
)
from middleware import authenticate, body, opt_str, req_str, sort_and_page
from services import MEMBER_ACCEPTING, active_term_of, membership_json, new_entity, touch
from util import ok_list, ok_object

bp = Blueprint("memberships", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")


def get_membership(membership_id):
    m = STORE["memberships"].get(membership_id)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "membership not found")
    return m


@bp.post("/v1/memberships")
def join_group():
    user_id, role = authenticate(("Employee", "DeiAdmin"))
    data = body()
    group_id = req_str(data, "group_id")
    employee_input = opt_str(data, "employee_id")
    employee_id = employee_input if (role == "DeiAdmin" and employee_input) else user_id
    # 4 existence
    group = STORE["groups"].get(group_id)
    if group is None:
        raise ApiError(ERR_NOT_FOUND, 404, "group not found")
    # 5 state
    if group["status"] not in MEMBER_ACCEPTING:
        raise ApiError(ERR_GROUP_NOT_ACCEPTING_MEMBERS, 409,
                       "group is not accepting members in its current state")
    # 8 constraint / upsert on (group_id, employee_id)
    existing = None
    for m in STORE["memberships"].values():
        if m["group_id"] == group_id and m["employee_id"] == employee_id:
            if m["status"] == "ACTIVE":
                raise ApiError(ERR_ALREADY_MEMBER, 409,
                               "an ACTIVE membership already exists for this pair")
            existing = m
    now = clock_now()
    if existing is not None:
        # Reactivate the INACTIVE row in place.
        existing["status"] = "ACTIVE"
        existing["joined_at"] = now
        existing["left_at"] = None
        touch(existing)
        return ok_object(membership_json(existing), 201)
    m = new_entity("memberships", {
        "group_id": group_id,
        "employee_id": employee_id,
        "status": "ACTIVE",
        "joined_at": now,
        "left_at": None,
    })
    return ok_object(membership_json(m), 201)


@bp.get("/v1/memberships/<membership_id>")
def read_membership(membership_id):
    authenticate(ALL_ROLES)
    return ok_object(membership_json(get_membership(membership_id)))


@bp.get("/v1/memberships")
def list_memberships():
    authenticate(ALL_ROLES)
    items = list(STORE["memberships"].values())
    for param, field in (("group_id", "group_id"), ("employee_id", "employee_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m.get(field) == v]
    page, limit, offset, total = sort_and_page(items, membership_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/memberships/<membership_id>/leave")
def leave_membership(membership_id):
    user_id, role = authenticate(("Employee", "GroupLeader", "DeiAdmin"))
    m = get_membership(membership_id)
    if m["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "membership is not ACTIVE")
    if role == "Employee":
        if m["employee_id"] != user_id:
            raise ApiError(ERR_NOT_GROUP_LEADER, 403,
                           "employees may only leave their own membership")
    elif role == "GroupLeader":
        term = active_term_of(m["group_id"])
        if term is None or term["leader_employee_id"] != user_id:
            raise ApiError(ERR_NOT_GROUP_LEADER, 403,
                           "caller does not lead this group")
    m["status"] = "INACTIVE"
    m["left_at"] = clock_now()
    touch(m)
    return ok_object(membership_json(m))
