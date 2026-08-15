"""StaffAssignment endpoints."""
from flask import Blueprint

from db import STORE
from errors import (
    ApiError,
    ERR_ASSIGNMENT_INVALID_STATE,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_CASE_INVALID_STATE,
    ERR_CASE_NOT_FOUND,
    ERR_STAFF_INACTIVE,
    ERR_STAFF_NOT_FOUND,
    ERR_STAFF_ROLE_MISMATCH,
    ERR_STAFF_WINDOW_CONFLICT,
)
from helpers import (
    ROLE_IN_CASE_TO_STAFF_ROLE,
    ROLES_IN_CASE,
    get_payload,
    new_id,
    paginate,
    req_enum,
    req_str,
)
from middleware import ALL_ROLES, require_roles
from response import success
from services import assignment_out, new_entity, staff_window_conflict, touch

bp = Blueprint("assignments", __name__)


@bp.route("/cath-lab/cases/<case_id>/staff-assignments", methods=["POST"])
@require_roles("CathLabScheduler")
def create_assignment(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    data = get_payload()
    # Body FK existence (priority 3) before remaining shape checks (priority 4).
    staff_id = data.get("staff_id")
    member = None
    if isinstance(staff_id, str):
        member = STORE["staff"].get(staff_id)
        if member is None:
            raise ApiError(ERR_STAFF_NOT_FOUND, "No StaffMember with the given staff_id", 404)
    staff_id = req_str(data, "staff_id")
    role_in_case = req_enum(data, "role_in_case", ROLES_IN_CASE)
    # Priority 5: case state gate.
    if case["status"] != "SCHEDULED":
        raise ApiError(
            ERR_CASE_INVALID_STATE,
            "Staff assignments may only be added to a SCHEDULED case",
            409,
        )
    # Priority 7: staff window conflict (strict half-open, adjacency allowed).
    if staff_window_conflict(staff_id, case["scheduled_start"], case["scheduled_end"]):
        raise ApiError(
            ERR_STAFF_WINDOW_CONFLICT,
            "Staff member has a conflicting assignment window",
            409,
        )
    # Priority 8: role mapping, then is_active.
    if member["staff_role"] != ROLE_IN_CASE_TO_STAFF_ROLE[role_in_case]:
        raise ApiError(
            ERR_STAFF_ROLE_MISMATCH,
            "role_in_case %s requires staff_role %s"
            % (role_in_case, ROLE_IN_CASE_TO_STAFF_ROLE[role_in_case]),
            422,
        )
    if not member["is_active"]:
        raise ApiError(ERR_STAFF_INACTIVE, "Staff member is not active", 409)
    assignment = new_entity()
    assignment["id"] = new_id()
    assignment.update(
        {
            "case_id": case_id,
            "staff_id": staff_id,
            "role_in_case": role_in_case,
            "window_start": case["scheduled_start"],
            "window_end": case["scheduled_end"],
            "status": "ASSIGNED",
        }
    )
    STORE["assignments"][assignment["id"]] = assignment
    return success(assignment_out(assignment), 201)


@bp.route("/cath-lab/cases/<case_id>/staff-assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_case_assignments(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "No CathCase with the given id", 404)
    items = [a for a in STORE["assignments"].values() if a["case_id"] == case_id]
    items.sort(key=lambda a: a["_seq"])
    page, pg = paginate(items)
    return success([assignment_out(a) for a in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/staff-assignments/<assignment_id>/release", methods=["POST"])
@require_roles("CathLabScheduler")
def release_assignment(assignment_id):
    assignment = STORE["assignments"].get(assignment_id)
    if assignment is None:
        raise ApiError(
            ERR_ASSIGNMENT_NOT_FOUND, "No StaffAssignment with the given id", 404
        )
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            ERR_ASSIGNMENT_INVALID_STATE,
            "Only an ASSIGNED assignment can be released",
            409,
        )
    assignment["status"] = "RELEASED"
    touch(assignment)
    return success(assignment_out(assignment), 200)
