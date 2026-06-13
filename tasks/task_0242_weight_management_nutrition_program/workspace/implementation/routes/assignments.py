"""CoachAssignment endpoints (PRD 3.8)."""
from flask import Blueprint, request

from common import (as_str, get_body, init_common, parse_pagination, require,
                    sort_by_creation, touch)
from db import db
from errors import (ERR_COACH_CAPACITY_EXCEEDED, ERR_ENROLLMENT_ALREADY_ASSIGNED,
                    ERR_INVALID_STATE, raise_error)
from lookups import get_assignment, get_coach, get_enrollment, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import services

bp = Blueprint("assignments", __name__)

ALL_READ = ("ProgramAdmin", "Clinician", "Coach", "Member")


@bp.route("/wm/coach-assignments", methods=["POST"])
@require_roles("ProgramAdmin")
def create_assignment():
    body = get_body()
    enrollment_id = as_str(require(body, "enrollment_id"), "enrollment_id")
    coach_id = as_str(require(body, "coach_id"), "coach_id")

    enrollment = get_enrollment(enrollment_id)
    coach = get_coach(coach_id)
    program = get_program(enrollment["program_id"])

    # at most one ACTIVE assignment per enrollment (priority 16)
    for a in db.coach_assignments.values():
        if a["enrollment_id"] == enrollment_id and a["status"] == "ACTIVE":
            raise_error(ERR_ENROLLMENT_ALREADY_ASSIGNED,
                        "Enrollment already has an ACTIVE assignment")

    # capacity gate (priority 17): new active count must not exceed cap
    new_count = services.recompute_coach_active_count(coach_id) + 1
    if new_count > program["coach_max_active_members"]:
        raise_error(ERR_COACH_CAPACITY_EXCEEDED, "Coach capacity exceeded")

    assignment = {
        "enrollment_id": enrollment_id,
        "coach_id": coach_id,
        "member_id": enrollment["member_id"],
        "assigned_at_utc": program["current_utc"],
        "ended_at_utc": None,
        "status": "ACTIVE",
    }
    init_common(assignment)
    db.coach_assignments[assignment["id"]] = assignment

    coach["active_member_count"] = services.recompute_coach_active_count(coach_id)
    touch(coach)
    return success(serialize(assignment), 201)


@bp.route("/wm/coach-assignments", methods=["GET"])
@require_roles(*ALL_READ)
def list_assignments():
    limit, offset = parse_pagination()
    items = list(db.coach_assignments.values())
    coach_id = request.args.get("coach_id")
    enrollment_id = request.args.get("enrollment_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if coach_id is not None:
        items = [a for a in items if a["coach_id"] == coach_id]
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([serialize(a) for a in page], limit, offset, total)


@bp.route("/wm/coach-assignments/<assignment_id>", methods=["GET"])
@require_roles(*ALL_READ)
def get_one_assignment(assignment_id):
    return success(serialize(get_assignment(assignment_id)), 200)


@bp.route("/wm/coach-assignments/<assignment_id>/end", methods=["POST"])
@require_roles("ProgramAdmin")
def end_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    if assignment["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "End requires ACTIVE assignment")
    program = get_program(db.enrollments[assignment["enrollment_id"]]["program_id"])
    services.end_coach_assignment(assignment, program)
    return success(serialize(assignment), 200)
