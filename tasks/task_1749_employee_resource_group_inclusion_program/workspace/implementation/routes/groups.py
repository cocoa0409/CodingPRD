"""ErgGroup endpoints: charter lifecycle, sponsor assignment (OCC), status
management with cascades."""
from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError, ERR_CHARTER_NO_SPONSOR, ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS,
    ERR_GROUP_NAME_NOT_UNIQUE, ERR_GROUP_NOT_ACTIVE, ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND, ERR_NOT_GROUP_LEADER, ERR_PROGRAM_IN_CLIMATE_REVIEW,
    ERR_PROGRAM_NOT_OPEN, ERR_SPONSOR_CAPACITY_EXCEEDED, ERR_SPONSOR_NOT_ACTIVE,
    ERR_SPONSOR_NOT_ASSIGNED, ERR_STALE_GROUP_VERSION,
)
from middleware import (
    authenticate, body, opt_str, req_enum, req_int, req_str, sort_and_page,
)
from services import (
    GROUP_NON_TERMINAL, MEMBER_ACCEPTING, active_member_count, dissolve_cascade,
    group_json, new_entity, suspend_cascade, touch,
)
from util import ok_list, ok_object

bp = Blueprint("groups", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")
GROUP_CATEGORIES = ("AFFINITY", "PROFESSIONAL", "COMMUNITY_OUTREACH")
ASSIGNABLE_STATES = ("CHARTER_DRAFT", "CHANGES_REQUESTED", "ACTIVE")


def get_group(group_id):
    g = STORE["groups"].get(group_id)
    if g is None:
        raise ApiError(ERR_NOT_FOUND, 404, "group not found")
    return g


def acting_sponsor(user_id):
    """The ExecutiveSponsor entity whose id is the caller's X-User-ID."""
    return STORE["sponsors"].get(user_id)


@bp.post("/v1/groups")
def create_group():
    user_id, role = authenticate(("GroupLeader", "DeiAdmin"))
    data = body()
    program_id = req_str(data, "program_id")
    name = req_str(data, "name")
    mission_statement = req_str(data, "mission_statement")
    category = req_enum(data, "category", GROUP_CATEGORIES)
    owner_employee_id = opt_str(data, "owner_employee_id")
    # 4 existence
    program = STORE["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "program not found")
    # 5 state: chartering requires an open program and non-review posture
    if program["status"] not in ("OPEN", "ALLOCATION_LOCKED"):
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not open for chartering")
    if program["posture"] == "CLIMATE_REVIEW":
        raise ApiError(ERR_PROGRAM_IN_CLIMATE_REVIEW, 409,
                       "program is in climate review; chartering blocked")
    # 8 constraint: name unique within program across non-terminal groups
    for g in STORE["groups"].values():
        if (g["program_id"] == program_id and g["name"] == name
                and g["status"] in GROUP_NON_TERMINAL):
            raise ApiError(ERR_GROUP_NAME_NOT_UNIQUE, 409,
                           "a non-terminal group with this name exists in the program")
    created_by = owner_employee_id if (role == "DeiAdmin" and owner_employee_id) else user_id
    g = new_entity("groups", {
        "program_id": program_id,
        "sponsor_id": None,
        "created_by_employee_id": created_by,
        "name": name,
        "mission_statement": mission_statement,
        "category": category,
        "status": "CHARTER_DRAFT",
        "founding_member_count": None,
        "allocated_cents": 0,
        "reserved_cents": 0,
        "spent_cents": 0,
        "certified_standing_score": None,
    })
    return ok_object(group_json(g), 201)


@bp.get("/v1/groups/<group_id>")
def read_group(group_id):
    authenticate(ALL_ROLES)
    return ok_object(group_json(get_group(group_id)))


@bp.get("/v1/groups")
def list_groups():
    authenticate(ALL_ROLES)
    items = list(STORE["groups"].values())
    for param, field in (("program_id", "program_id"), ("sponsor_id", "sponsor_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [g for g in items if g.get(field) == v]
    page, limit, offset, total = sort_and_page(items, group_json)
    return ok_list(page, limit, offset, total)


@bp.post("/v1/groups/<group_id>/assign-sponsor")
def assign_sponsor(group_id):
    authenticate(("DeiAdmin",))
    data = body()
    sponsor_id = req_str(data, "sponsor_id")
    expected_group_version = req_int(data, "expected_group_version")
    # 4 existence: path id first, then body-referenced id
    g = get_group(group_id)
    sponsor = STORE["sponsors"].get(sponsor_id)
    if sponsor is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sponsor not found")
    # 4.5 OCC
    if expected_group_version != g["version"]:
        raise ApiError(ERR_STALE_GROUP_VERSION, 412, "group version is stale")
    # 5 state
    if g["status"] not in ASSIGNABLE_STATES:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "sponsor cannot be assigned in the group's current state")
    if sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_NOT_ACTIVE, 409, "sponsor is not ACTIVE")
    # 9 capacity: count of sponsored groups in non-terminal statuses < max_groups
    load = sum(1 for x in STORE["groups"].values()
               if x["sponsor_id"] == sponsor_id and x["status"] in GROUP_NON_TERMINAL)
    if load >= sponsor["max_groups"]:
        raise ApiError(ERR_SPONSOR_CAPACITY_EXCEEDED, 409,
                       "sponsor is at the maximum number of groups")
    g["sponsor_id"] = sponsor_id
    touch(g)
    return ok_object(group_json(g))


@bp.post("/v1/groups/<group_id>/submit-charter")
def submit_charter(group_id):
    user_id, _ = authenticate(("GroupLeader",))
    g = get_group(group_id)
    if g["status"] not in ("CHARTER_DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "charter cannot be submitted from the group's current state")
    if user_id != g["created_by_employee_id"]:
        raise ApiError(ERR_NOT_GROUP_LEADER, 403, "caller is not the charter owner")
    if g["sponsor_id"] is None:
        raise ApiError(ERR_CHARTER_NO_SPONSOR, 409, "charter has no assigned sponsor")
    if active_member_count(group_id) < 10:
        raise ApiError(ERR_CHARTER_INSUFFICIENT_FOUNDING_MEMBERS, 409,
                       "fewer than 10 active members")
    g["status"] = "SUBMITTED"
    touch(g)
    return ok_object(group_json(g))


@bp.post("/v1/groups/<group_id>/sponsor-decision")
def group_sponsor_decision(group_id):
    user_id, _ = authenticate(("ExecutiveSponsor",))
    data = body()
    decision = req_enum(data, "decision", ("ENDORSE", "REQUEST_CHANGES"))
    opt_str(data, "change_note")
    g = get_group(group_id)
    if g["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "sponsor decision requires a SUBMITTED charter")
    sponsor = acting_sponsor(user_id)
    if sponsor is not None and sponsor["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_NOT_ACTIVE, 409, "sponsor is not ACTIVE")
    if g["sponsor_id"] != user_id:
        raise ApiError(ERR_SPONSOR_NOT_ASSIGNED, 409,
                       "caller is not the group's assigned sponsor")
    g["status"] = "SPONSOR_ENDORSED" if decision == "ENDORSE" else "CHANGES_REQUESTED"
    touch(g)
    return ok_object(group_json(g))


@bp.post("/v1/groups/<group_id>/dei-decision")
def group_dei_decision(group_id):
    authenticate(("DeiAdmin",))
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    g = get_group(group_id)
    if g["status"] != "SPONSOR_ENDORSED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "DEI decision requires a SPONSOR_ENDORSED charter")
    if decision == "APPROVE":
        g["founding_member_count"] = active_member_count(group_id)
        g["status"] = "ACTIVE"
    else:
        g["status"] = "CHARTER_REJECTED"
    touch(g)
    return ok_object(group_json(g))


@bp.post("/v1/groups/<group_id>/set-status")
def group_set_status(group_id):
    authenticate(("DeiAdmin",))
    data = body()
    to_status = req_enum(data, "to_status", ("SUSPENDED", "ACTIVE", "DISSOLVED"))
    opt_str(data, "reason")
    g = get_group(group_id)
    allowed = {
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "DISSOLVED"),
        ("SUSPENDED", "DISSOLVED"),
    }
    if (g["status"], to_status) not in allowed:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       f"cannot move group from {g['status']} to {to_status}")
    if to_status == "SUSPENDED":
        g["status"] = "SUSPENDED"
        touch(g)
        suspend_cascade(g)
    elif to_status == "DISSOLVED":
        g["status"] = "DISSOLVED"
        touch(g)
        dissolve_cascade(g)
    else:  # SUSPENDED -> ACTIVE reinstatement
        g["status"] = "ACTIVE"
        touch(g)
    return ok_object(group_json(g))
