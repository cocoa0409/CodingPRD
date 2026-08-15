"""Assignment endpoints (PRD §3.4, §3.5): chair proposal with the full
validation gauntlet, faculty consent, chair withdraw/rescind."""

from decimal import Decimal

import db
from errors import (
    ApiError,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_SECTION_NOT_FOUND,
    ERR_FACULTY_NOT_FOUND,
    ERR_INVALID_TERM_STATE,
    ERR_SECTION_NOT_ASSIGNABLE,
    ERR_INVALID_ASSIGNMENT_TRANSITION,
    ERR_INVALID_FACULTY_STATE,
    ERR_FORBIDDEN_RESOURCE_OWNERSHIP,
    ERR_NOT_QUALIFIED_FOR_COURSE,
    ERR_MEETING_TIME_CONFLICT,
    ERR_SECTION_ALREADY_ASSIGNED,
    ERR_UNION_OVERLOAD_CAP_EXCEEDED,
    ERR_COMP_BUDGET_EXCEEDED,
)
from middleware import authenticate, require_to_state_role, ALL_ROLES, CHAIR, FACULTY
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, dec
import services

bp = make_blueprint("assignments")

ASSIGNMENT_STATUSES = ["PROPOSED", "CONFIRMED", "DECLINED", "WITHDRAWN", "RESCINDED", "CANCELLED"]

# Per-to_state role gates on the shared transition endpoint (SCAFFOLD §1.7).
TO_STATE_ROLES = {
    "CONFIRMED": {FACULTY},
    "DECLINED": {FACULTY},
    "WITHDRAWN": {CHAIR},
    "RESCINDED": {CHAIR},
}


def require_assignment(assignment_id):
    assignment = db.get("assignments", assignment_id)
    if assignment is None:
        raise ApiError(ERR_ASSIGNMENT_NOT_FOUND, 404, "assignment not found")
    return assignment


@bp.post("/assignments")
def create_assignment():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "section_id": {"type": "string", "required": True},
        "faculty_id": {"type": "string", "required": True},
    })
    # Existence (priority 4), body FKs in declared input order.
    section = db.get("course_sections", body["section_id"])
    if section is None:
        raise ApiError(ERR_SECTION_NOT_FOUND, 404, "section not found")
    faculty = db.get("faculty_members", body["faculty_id"])
    if faculty is None:
        raise ApiError(ERR_FACULTY_NOT_FOUND, 404, "faculty member not found")
    term = services.term_of_section(section)
    course = services.course_of_section(section)
    # State (priority 5): assignments only while the term is OPEN; the section
    # must be SCHEDULED or STAFFED.
    if term["status"] != "OPEN":
        raise ApiError(ERR_INVALID_TERM_STATE, 409,
                       "assignments may be created only while the term is OPEN")
    if section["status"] not in ("SCHEDULED", "STAFFED"):
        raise ApiError(ERR_SECTION_NOT_ASSIGNABLE, 409,
                       "assignment requires a section in SCHEDULED or STAFFED status")
    # Qualification (priority 6): an ACTIVE qualification (lazy EXPIRED applied)
    # must exist for (faculty, section.course).
    if not services.has_active_qualification(faculty["id"], course["id"]):
        raise ApiError(ERR_NOT_QUALIFIED_FOR_COURSE, 422,
                       "no ACTIVE qualification for this faculty and course")
    # Temporal overlap (priority 7): half-open [start, end) against every other
    # section holding a non-terminal assignment for this faculty in this term.
    for other in db.all_of("assignments"):
        if (other["faculty_id"] == faculty["id"] and other["term_id"] == term["id"]
                and other["status"] in services.LIVE_ASSIGNMENT_STATUSES
                and other["section_id"] != section["id"]):
            other_section = db.get("course_sections", other["section_id"])
            if other_section is None or other_section["meeting_day"] != section["meeting_day"]:
                continue
            if (section["start_minute"] < other_section["end_minute"]
                    and other_section["start_minute"] < section["end_minute"]):
                raise ApiError(ERR_MEETING_TIME_CONFLICT, 409,
                               "meeting window overlaps another assignment for this faculty")
    # Business constraints (priority 8): one non-terminal assignment per
    # section, then the union overload cap.
    for other in db.all_of("assignments"):
        if (other["section_id"] == section["id"]
                and other["status"] in services.LIVE_ASSIGNMENT_STATUSES):
            raise ApiError(ERR_SECTION_ALREADY_ASSIGNED, 409,
                           "section already has a non-terminal assignment")
    credit_units = services.assignment_credits(section, course, term, section["enrolled_count"])
    if faculty["is_union_covered"]:
        sheet = services.find_sheet(term["id"], faculty["id"])
        teaching = dec(sheet["teaching_credits"]) if sheet else Decimal("0")
        effective = (dec(sheet["effective_obligation_credits"]) if sheet
                     else dec(faculty["base_load_credits"]))
        projected_overload = teaching + dec(credit_units) - effective
        if projected_overload < 0:
            projected_overload = Decimal("0")
        # Strictly greater than the cap is rejected; landing exactly on it passes.
        if projected_overload > dec(term["union_max_overload_credits"]):
            raise ApiError(ERR_UNION_OVERLOAD_CAP_EXCEEDED, 422,
                           "projected overload would exceed the union overload cap")
    assignment = db.new_entity("assignments", {
        "term_id": section["term_id"],
        "section_id": section["id"],
        "faculty_id": faculty["id"],
        "credit_units": credit_units,
        "final_credit_units": None,
        "stipend_cents": 0,
        "matches_preference": course["id"] in (faculty.get("preferred_course_ids") or []),
        "status": "PROPOSED",
    })
    sheet = services.get_or_create_sheet(term["id"], faculty["id"])
    services.recompute_sheet(sheet)
    return success_obj(db.public(assignment), 201)


@bp.get("/assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("assignments"), ["term_id", "section_id", "faculty_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.get("/assignments/<assignmentId>")
def get_assignment(assignmentId):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_assignment(assignmentId)), 200)


@bp.post("/assignments/<assignmentId>/transition")
def transition_assignment(assignmentId):
    user_id, role = authenticate([CHAIR, FACULTY])
    body = body_json()
    check_shape(body, {"to_state": {"type": "enum", "values": ASSIGNMENT_STATUSES, "required": True}})
    to_state = body["to_state"]
    require_to_state_role(role, to_state, TO_STATE_ROLES)
    assignment = require_assignment(assignmentId)
    # Ownership (priority 2.1): a FacultyMember caller may confirm/decline only
    # their own assignment.
    if role == FACULTY and to_state in ("CONFIRMED", "DECLINED"):
        if user_id != assignment["faculty_id"]:
            raise ApiError(ERR_FORBIDDEN_RESOURCE_OWNERSHIP, 403,
                           "faculty may act only on their own assignments")
    from_state = assignment["status"]
    if to_state == "CONFIRMED":
        if from_state != "PROPOSED":
            raise ApiError(ERR_INVALID_ASSIGNMENT_TRANSITION, 409,
                           f"cannot move a {from_state} assignment to CONFIRMED")
        faculty = db.get("faculty_members", assignment["faculty_id"])
        if faculty is None or faculty["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_FACULTY_STATE, 409,
                           "only an ACTIVE faculty member can confirm an assignment")
        assignment["status"] = "CONFIRMED"
        db.touch(assignment)
        section = db.get("course_sections", assignment["section_id"])
        if section is not None:
            services.staff_section_on_confirm(section)
        services.recompute_pair(assignment["term_id"], assignment["faculty_id"])
        return success_obj(db.public(assignment), 200)
    if to_state == "DECLINED":
        if from_state != "PROPOSED":
            raise ApiError(ERR_INVALID_ASSIGNMENT_TRANSITION, 409,
                           f"cannot move a {from_state} assignment to DECLINED")
        assignment["status"] = "DECLINED"
        db.touch(assignment)
        services.recompute_pair(assignment["term_id"], assignment["faculty_id"])
        return success_obj(db.public(assignment), 200)
    if to_state == "WITHDRAWN":
        if from_state != "PROPOSED":
            raise ApiError(ERR_INVALID_ASSIGNMENT_TRANSITION, 409,
                           f"cannot move a {from_state} assignment to WITHDRAWN")
        assignment["status"] = "WITHDRAWN"
        db.touch(assignment)
        services.recompute_pair(assignment["term_id"], assignment["faculty_id"])
        return success_obj(db.public(assignment), 200)
    # RESCINDED (chair, from CONFIRMED; late stipend rules).
    if from_state != "CONFIRMED":
        raise ApiError(ERR_INVALID_ASSIGNMENT_TRANSITION, 409,
                       f"cannot move a {from_state} assignment to RESCINDED")
    term = db.get("workload_terms", assignment["term_id"])
    if term["status"] == "PUBLISHED":
        raise ApiError(ERR_INVALID_TERM_STATE, 409,
                       "rescission is forbidden once the term is PUBLISHED")
    late = services.is_late(term)
    if late and term["comp_budget_spent_cents"] + term["late_cancel_stipend_cents"] > term["comp_budget_cents"]:
        raise ApiError(ERR_COMP_BUDGET_EXCEEDED, 402,
                       "the late-cancel stipend would exceed the term compensation budget")
    if late:
        assignment["stipend_cents"] = term["late_cancel_stipend_cents"]
        term["comp_budget_spent_cents"] += assignment["stipend_cents"]
        db.touch(term)
    assignment["status"] = "RESCINDED"
    db.touch(assignment)
    section = db.get("course_sections", assignment["section_id"])
    if section is not None:
        services.demote_section_if_unstaffed(section)
    services.recompute_pair(assignment["term_id"], assignment["faculty_id"])
    return success_obj(db.public(assignment), 200)
