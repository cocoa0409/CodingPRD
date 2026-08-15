"""Assignment lifecycle per PRD 3.3."""

from .auth import require, require_owner
from .blueprint import bp
from .calc import (
    provisional_cost_cents,
    reallocate_week_for,
    recompute_active_assignment_count,
)
from .envelope import ok_obj
from .errors import ApiError, invalid_state, not_found
from .serialize import ser_assignment
from .store import STORE, new_entity, now, touch
from .util import body, req_dt, req_enum, req_int, req_str

ASSIGNMENT_ROLES = ("REPORTER", "PHOTOGRAPHER")
FIELD_ROLES = ["Reporter", "Photographer"]


def get_assignment(aid):
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    return a


def _has_time_conflict(staff_id, start_at, end_at, exclude_id=None):
    """Half-open interval overlap against the staff member's other
    PROPOSED/ACCEPTED assignments. Touching endpoints do not conflict."""
    for other in STORE.assignments.values():
        if other["staff_id"] != staff_id:
            continue
        if other["status"] not in ("PROPOSED", "ACCEPTED"):
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if start_at < other["end_at"] and end_at > other["start_at"]:
            return True
    return False


@bp.post("/newsroom/assignments")
def propose_assignment():
    require(["AssignmentEditor"])
    b = body()
    story_id = req_str(b, "story_id")
    staff_id = req_str(b, "staff_id")
    assignment_role = req_enum(b, "assignment_role", ASSIGNMENT_ROLES)
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    planned_effort_minutes = req_int(b, "planned_effort_minutes", minimum=1)

    # Body FK existence (priority 5): story first, then staff.
    story = STORE.stories.get(story_id)
    if story is None:
        not_found("ERR_STORY_NOT_FOUND", "Story")
    staff = STORE.staff.get(staff_id)
    if staff is None:
        not_found("ERR_STAFF_NOT_FOUND", "StaffMember")

    if story["status"] not in ("DRAFT", "IN_EDIT", "ON_HOLD"):
        invalid_state("Story cannot be crewed in its current state")
    if staff["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_STAFF_INACTIVE", 422, "Staff member is not ACTIVE"
        )
    if staff["role_capability"] != assignment_role:
        raise ApiError(
            "ERR_CAPABILITY_MISMATCH",
            422,
            "assignment_role differs from the staff member's role_capability",
        )
    if end_at <= start_at:
        raise ApiError(
            "ERR_INVALID_INTERVAL", 422, "end_at must be strictly after start_at"
        )
    if _has_time_conflict(staff_id, start_at, end_at):
        raise ApiError(
            "ERR_STAFF_TIME_CONFLICT",
            409,
            "Assignment window overlaps another PROPOSED/ACCEPTED assignment",
        )

    e = new_entity()
    e.update({
        "story_id": story_id,
        "staff_id": staff_id,
        "assignment_role": assignment_role,
        "status": "PROPOSED",
        "start_at": start_at,
        "end_at": end_at,
        "planned_effort_minutes": planned_effort_minutes,
        "actual_effort_minutes": None,
        "provisional_cost_cents": provisional_cost_cents(
            planned_effort_minutes, staff["hourly_rate_cents"]
        ),
        "final_cost_cents": None,
        "completed_at": None,
        "bumped_by_event_id": None,
    })
    STORE.assignments[e["id"]] = e
    recompute_active_assignment_count(staff_id)
    return ok_obj(ser_assignment(e), 201)


@bp.post("/newsroom/assignments/<aid>/accept")
def accept_assignment(aid):
    uid, _role = require(FIELD_ROLES)
    a = get_assignment(aid)
    require_owner(uid, a["staff_id"])
    if a["status"] != "PROPOSED":
        invalid_state("Assignment is not PROPOSED")
    staff = STORE.staff.get(a["staff_id"])
    if staff is None:
        not_found("ERR_STAFF_NOT_FOUND", "StaffMember")
    if staff["employment_status"] != "ACTIVE":
        raise ApiError("ERR_STAFF_INACTIVE", 422, "Staff member is not ACTIVE")
    if _has_time_conflict(a["staff_id"], a["start_at"], a["end_at"], exclude_id=a["id"]):
        raise ApiError(
            "ERR_STAFF_TIME_CONFLICT",
            409,
            "Assignment window overlaps another PROPOSED/ACCEPTED assignment",
        )
    accepted_count = sum(
        1
        for x in STORE.assignments.values()
        if x["staff_id"] == a["staff_id"] and x["status"] == "ACCEPTED"
    )
    if accepted_count >= staff["max_concurrent_assignments"]:
        raise ApiError(
            "ERR_ASSIGNMENT_CAP_REACHED",
            422,
            "Staff member has reached max_concurrent_assignments",
        )

    a["status"] = "ACCEPTED"
    touch(a)
    recompute_active_assignment_count(a["staff_id"])

    # Bubble-up: ON_HOLD story resumes to DRAFT when a REPORTER assignment is accepted.
    story = STORE.stories.get(a["story_id"])
    if (
        story is not None
        and story["status"] == "ON_HOLD"
        and a["assignment_role"] == "REPORTER"
    ):
        story["status"] = "DRAFT"
        touch(story)
    return ok_obj(ser_assignment(a))


@bp.post("/newsroom/assignments/<aid>/decline")
def decline_assignment(aid):
    uid, _role = require(FIELD_ROLES)
    a = get_assignment(aid)
    require_owner(uid, a["staff_id"])
    if a["status"] != "PROPOSED":
        invalid_state("Assignment is not PROPOSED")
    a["status"] = "DECLINED"
    touch(a)
    recompute_active_assignment_count(a["staff_id"])
    return ok_obj(ser_assignment(a))


@bp.post("/newsroom/assignments/<aid>/complete")
def complete_assignment(aid):
    uid, role = require(["Reporter", "Photographer", "AssignmentEditor"])
    a = get_assignment(aid)
    if role in ("Reporter", "Photographer"):
        require_owner(uid, a["staff_id"])
    b = body()
    actual_effort_minutes = req_int(b, "actual_effort_minutes", minimum=1)
    if a["status"] != "ACCEPTED":
        invalid_state("Assignment is not ACCEPTED")

    a["status"] = "COMPLETED"
    a["actual_effort_minutes"] = actual_effort_minutes
    a["completed_at"] = now()
    touch(a)
    # Retroactive weekly overtime re-allocation across the payroll week.
    reallocate_week_for(a["staff_id"], a["completed_at"])
    recompute_active_assignment_count(a["staff_id"])
    return ok_obj(ser_assignment(a))


@bp.post("/newsroom/assignments/<aid>/cancel")
def cancel_assignment(aid):
    require(["AssignmentEditor"])
    a = get_assignment(aid)
    if a["status"] not in ("PROPOSED", "ACCEPTED"):
        invalid_state("Assignment is not PROPOSED or ACCEPTED")
    a["status"] = "CANCELLED"
    touch(a)
    recompute_active_assignment_count(a["staff_id"])
    return ok_obj(ser_assignment(a))
