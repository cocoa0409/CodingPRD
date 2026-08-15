"""Advisor assignment endpoints, including auto-assign selector and end."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, stamp_new, touch,
)
from services.calculations import recompute_advisor_loads

bp = Blueprint("assignments", __name__)

ROLE_READ = ("AdvisingDirector", "Advisor", "FrontDeskStaff")


def assignment_public(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "advisor_id": a["advisor_id"],
        "assignment_mode": a["assignment_mode"],
        "status": a["status"],
        "ended_reason": a["ended_reason"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _supersede_incumbent(student_id):
    """End any existing ACTIVE assignment for the student as SUPERSEDED; return old advisor id."""
    old_advisor_id = None
    for asg in db.assignments.values():
        if asg["student_id"] == student_id and asg["status"] == "ACTIVE":
            asg["status"] = "ENDED"
            asg["ended_reason"] = "SUPERSEDED"
            touch(asg)
            old_advisor_id = asg["advisor_id"]
    return old_advisor_id


@bp.route("/advising/advisor-assignments", methods=["POST"])
def create_assignment():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["student_id", "advisor_id", "expected_student_version"])
    require_role(role, ("AdvisingDirector",))

    # existence: body-referenced ids
    student = db.students.get(data["student_id"])
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {data['student_id']} not found", 404)
    advisor = db.advisors.get(data["advisor_id"])
    if not advisor:
        raise ApiError(errors.ERR_ADVISOR_NOT_FOUND, f"Advisor {data['advisor_id']} not found", 404)

    # OCC guard (priority 4.5): after existence, before state
    esv = data["expected_student_version"]
    if not isinstance(esv, int) or isinstance(esv, bool):
        raise ApiError(errors.ERR_VALIDATION, "expected_student_version must be an integer", 400)
    if esv != student["version"]:
        raise ApiError(
            errors.ERR_STALE_VERSION,
            f"expected_student_version {esv} does not match current student version {student['version']}",
            412,
        )

    # state: student must be ENROLLED
    if student["care_status"] != "ENROLLED":
        raise ApiError(errors.ERR_STUDENT_NOT_ENROLLED,
                       "Student care_status must be ENROLLED for assignment creation", 409)

    # business eligibility (priority 7): capacity, major served, advisor active
    if advisor["status"] != "ACTIVE":
        raise ApiError(errors.ERR_ADVISOR_NOT_ACTIVE, "Advisor is not ACTIVE", 409)
    if student["major_code"] not in advisor["major_codes"]:
        raise ApiError(errors.ERR_MAJOR_NOT_SERVED,
                       f"Student major {student['major_code']} not served by advisor", 409)
    recompute_advisor_loads(advisor["id"])
    if advisor["assigned_active_count"] >= advisor["max_caseload"]:
        raise ApiError(errors.ERR_ADVISOR_AT_CAPACITY, "Advisor is at capacity", 409)

    # create-with-supersede
    old_advisor_id = _supersede_incumbent(student["id"])
    assignment = stamp_new({
        "student_id": student["id"],
        "advisor_id": advisor["id"],
        "assignment_mode": "MANUAL",
        "status": "ACTIVE",
        "ended_reason": None,
    })
    db.assignments[assignment["id"]] = assignment
    recompute_advisor_loads(advisor["id"])
    if old_advisor_id and old_advisor_id != advisor["id"]:
        recompute_advisor_loads(old_advisor_id)
    touch(student)
    return success_object(assignment_public(assignment), 201)


@bp.route("/advising/advisor-assignments/auto-assign", methods=["POST"])
def auto_assign():
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["student_id"])
    ranking_mode = data.get("ranking_mode", "WEIGHTED")
    if ranking_mode not in ("WEIGHTED", "HEADCOUNT"):
        raise ApiError(errors.ERR_VALIDATION, f"Invalid ranking_mode: {ranking_mode}", 400)
    require_role(role, ("AdvisingDirector",))

    student = db.students.get(data["student_id"])
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {data['student_id']} not found", 404)
    if student["care_status"] != "ENROLLED":
        raise ApiError(errors.ERR_STUDENT_NOT_ENROLLED,
                       "Student care_status must be ENROLLED for assignment creation", 409)

    # eligibility pool
    pool = []
    for advisor in db.advisors.values():
        if advisor["status"] != "ACTIVE":
            continue
        if student["major_code"] not in advisor["major_codes"]:
            continue
        recompute_advisor_loads(advisor["id"])
        if advisor["assigned_active_count"] >= advisor["max_caseload"]:
            continue
        pool.append(advisor)
    if not pool:
        raise ApiError(errors.ERR_NO_ELIGIBLE_ADVISOR, "No eligible advisor available", 422)

    if ranking_mode == "WEIGHTED":
        pool.sort(key=lambda a: (a["weighted_load"], a["assigned_active_count"], a["created_at"], a["id"]))
    else:  # HEADCOUNT
        pool.sort(key=lambda a: (a["assigned_active_count"], a["weighted_load"], a["created_at"], a["id"]))
    chosen = pool[0]

    old_advisor_id = _supersede_incumbent(student["id"])
    assignment = stamp_new({
        "student_id": student["id"],
        "advisor_id": chosen["id"],
        "assignment_mode": "AUTO",
        "status": "ACTIVE",
        "ended_reason": None,
    })
    db.assignments[assignment["id"]] = assignment
    recompute_advisor_loads(chosen["id"])
    if old_advisor_id and old_advisor_id != chosen["id"]:
        recompute_advisor_loads(old_advisor_id)
    touch(student)
    return success_object(assignment_public(assignment), 201)


@bp.route("/advising/advisor-assignments", methods=["GET"])
def list_assignments():
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    limit, offset = get_pagination_params()
    items = list(db.assignments.values())
    student_id = request.args.get("student_id")
    advisor_id = request.args.get("advisor_id")
    status = request.args.get("status")
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if advisor_id is not None:
        items = [a for a in items if a["advisor_id"] == advisor_id]
    if status is not None:
        if status not in ("ACTIVE", "ENDED"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid status filter: {status}", 400)
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([assignment_public(a) for a in page], limit, offset, total)


@bp.route("/advising/advisor-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    user_id, role = get_auth_context()
    require_role(role, ROLE_READ)
    asg = db.assignments.get(assignmentId)
    if not asg:
        raise ApiError(errors.ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {assignmentId} not found", 404)
    return success_object(assignment_public(asg))


@bp.route("/advising/advisor-assignments/<assignmentId>/end", methods=["POST"])
def end_assignment(assignmentId):
    user_id, role = get_auth_context()
    require_role(role, ("AdvisingDirector",))
    asg = db.assignments.get(assignmentId)
    if not asg:
        raise ApiError(errors.ERR_ASSIGNMENT_NOT_FOUND, f"Assignment {assignmentId} not found", 404)
    if asg["status"] != "ACTIVE":
        raise ApiError(errors.ERR_ASSIGNMENT_ALREADY_ENDED, "Assignment is not ACTIVE", 409)
    asg["status"] = "ENDED"
    asg["ended_reason"] = "MANUAL_END"
    touch(asg)
    recompute_advisor_loads(asg["advisor_id"])
    student = db.students.get(asg["student_id"])
    if student:
        touch(student)
    return success_object(assignment_public(asg))
