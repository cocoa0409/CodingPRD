"""StaffAssignment endpoints (PRD 3.4)."""
from flask import Blueprint, g

import calc
import cascades
from core import (ApiError, ROLE_FITNESS_STAFF, ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER,
                 body, created, find, get_or_404, new_record, now, ok, opt_enum, opt_str,
                 req_str, require, upd, view, where)
from guards import ASSIGNMENT_TERMINAL, SESSION_TERMINAL, invalid_transition, terminal

bp = Blueprint("assignments", __name__)

ROLES_ON_SESSION = ("LEAD", "SUPPORT")
LIVE_ASSIGNMENT_STATUSES = ("ASSIGNED", "CONFIRMED", "VACANT_NEEDS_COVER")


def _staff_conflict(staff_id, session, exclude_id=None):
    """Half-open overlap, no buffer: back-to-back shifts are legal."""
    start = session["scheduled_start_utc"]
    end = session["scheduled_end_utc"]
    for assignment in where("assignment", staff_member_id=staff_id):
        if assignment["id"] == exclude_id:
            continue
        if assignment["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        other = find("session", assignment["session_id"])
        if other is None or other["id"] == session["id"]:
            continue
        if start < other["scheduled_end_utc"] and other["scheduled_start_utc"] < end:
            return True
    return False


def _duplicate_lead(session, exclude_id=None):
    for assignment in where("assignment", session_id=session["id"]):
        if assignment["id"] == exclude_id:
            continue
        if assignment["role_on_session"] == "LEAD" and \
                assignment["status"] in LIVE_ASSIGNMENT_STATUSES:
            return True
    return False


@bp.post("/staff-assignments")
def create_assignment():
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    data = body()
    session_id = req_str(data, "session_id")
    staff_member_id = req_str(data, "staff_member_id")
    role_on_session = opt_enum(data, "role_on_session", ROLES_ON_SESSION, default="LEAD")
    session = get_or_404("session", session_id)
    staff = get_or_404("staff", staff_member_id)
    terminal(session["status"] in SESSION_TERMINAL)
    if session["status"] not in calc.OPEN_SESSION_STATUSES:
        invalid_transition()
    offering = find("offering", session["offering_id"])
    required_type = offering["required_credential_type"] if offering else None
    if required_type is not None and \
            not calc.holds_live_credential(staff["id"], required_type):
        raise ApiError("ERR_CREDENTIAL_NOT_VERIFIED", 422)
    if staff["duty_status"] != "ACTIVE_DUTY":
        raise ApiError("ERR_STAFF_NOT_ON_DUTY", 422)
    if offering is not None and staff["contract_id"] != offering["contract_id"]:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    if _staff_conflict(staff["id"], session):
        raise ApiError("ERR_STAFF_TIME_CONFLICT", 409)
    if role_on_session == "LEAD" and _duplicate_lead(session):
        raise ApiError("ERR_DUPLICATE_LEAD_ASSIGNMENT", 409)
    paid_minutes = calc.paid_minutes_for(session, role_on_session)
    assignment = new_record("assignment", {
        "session_id": session_id,
        "staff_member_id": staff_member_id,
        "role_on_session": role_on_session,
        "status": "ASSIGNED",
        "paid_minutes": paid_minutes,
        "labor_cost_cents": 0,
        "confirmed_at": None,
    })
    upd(staff, committed_minutes_current_period=(
        staff.get("committed_minutes_current_period") or 0) + paid_minutes)
    cascades.refresh_readiness(staff)
    return created(view(assignment))


@bp.post("/staff-assignments/<aid>/confirm")
def confirm_assignment(aid):
    require(ROLE_FITNESS_STAFF, ROLE_SITE_MANAGER)
    assignment = get_or_404("assignment", aid)
    body()
    if g.role == ROLE_FITNESS_STAFF and g.user_id != assignment["staff_member_id"]:
        raise ApiError("ERR_FORBIDDEN_SCOPE", 403)
    terminal(assignment["status"] in ASSIGNMENT_TERMINAL)
    if assignment["status"] != "ASSIGNED":
        invalid_transition()
    session = find("session", assignment["session_id"])
    if session is None or session["status"] not in calc.OPEN_SESSION_STATUSES:
        invalid_transition()
    staff = find("staff", assignment["staff_member_id"])
    if staff is None or staff["duty_status"] != "ACTIVE_DUTY":
        raise ApiError("ERR_STAFF_NOT_ON_DUTY", 422)
    upd(assignment, status="CONFIRMED", confirmed_at=now())
    if assignment["role_on_session"] == "LEAD" and \
            session["status"] in ("SCHEDULED", "STAFFING_AT_RISK"):
        upd(session, status="STAFFED")
    cascades.refresh_attainment(find("offering", session["offering_id"]),
                                provisional=True, final=False)
    return ok(view(assignment))


@bp.post("/staff-assignments/<aid>/release")
def release_assignment_endpoint(aid):
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    assignment = get_or_404("assignment", aid)
    data = body()
    opt_str(data, "reason", 1, 500)
    terminal(assignment["status"] in ASSIGNMENT_TERMINAL)
    if assignment["status"] not in LIVE_ASSIGNMENT_STATUSES:
        invalid_transition()
    cascades.release_assignment(assignment, cascade=True)
    return ok(view(assignment))
