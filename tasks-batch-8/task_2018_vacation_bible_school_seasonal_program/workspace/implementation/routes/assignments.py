"""Role assignments: propose, confirm, release (PRD §3.4)."""

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from cascade import confirm_assignment
from derived import role_assignment_view
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_ASSIGNMENT,
    ERR_MINOR_ROLE_FORBIDDEN,
    ERR_LEAD_TEACHER_TAKEN,
    ERR_VOLUNTEER_DOUBLE_BOOKED,
    ERR_VOLUNTEER_NOT_CLEARED,
)
from routes.common import paginate, empty_body, guard_program_writable
from validate import Field, get_body, validate_body

bp = Blueprint("assignments", __name__)

ROLES = {"LEAD_TEACHER", "ASSISTANT_TEACHER", "SNACK_COORDINATOR", "CRAFT_LEADER", "CHECKIN_DESK"}

_CREATE_SPEC = {
    "volunteer_id": Field("str", required=True),
    "classroom_id": Field("str", required=True),
    "role": Field("enum", enum=ROLES, required=True),
}


def get_assignment_or_404(assignment_id):
    ra = store.get("role_assignments", assignment_id)
    if ra is None:
        raise_err(ERR_NOT_FOUND, "role assignment not found")
    return ra


@bp.post("/vbs/role-assignments")
def create_assignment():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "VolunteerCoordinator", "Volunteer")
    if ctx.role == "Volunteer" and data["volunteer_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "volunteers may only propose their own assignments")
    # P3 existence per the reference hierarchy: classroom before volunteer.
    classroom = store.get("classrooms", data["classroom_id"])
    if classroom is None:
        raise_err(ERR_NOT_FOUND, "classroom not found")
    volunteer = store.get("volunteers", data["volunteer_id"])
    if volunteer is None:
        raise_err(ERR_NOT_FOUND, "volunteer not found")
    guard_program_writable(store.get("programs", classroom["program_id"]))
    for other in store.all_of("role_assignments"):
        if (
            other["volunteer_id"] == volunteer["id"]
            and other["classroom_id"] == classroom["id"]
            and other["status"] in ("PROPOSED", "CONFIRMED")
        ):
            raise_err(ERR_DUPLICATE_ASSIGNMENT, "an active assignment already exists in this classroom")
    if data["role"] == "LEAD_TEACHER" and volunteer["is_minor"]:
        raise_err(ERR_MINOR_ROLE_FORBIDDEN, "a minor may not be proposed as LEAD_TEACHER")
    ra = store.new_record(
        volunteer_id=volunteer["id"],
        classroom_id=classroom["id"],
        role=data["role"],
        status="PROPOSED",
        confirmed_at=None,
        released_at=None,
    )
    store.put("role_assignments", ra)
    return ok_object(role_assignment_view(ra), status=201)


@bp.post("/vbs/role-assignments/<assignment_id>/confirm")
def confirm(assignment_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "VolunteerCoordinator")
    ra = get_assignment_or_404(assignment_id)
    classroom = store.get("classrooms", ra["classroom_id"])
    guard_program_writable(store.get("programs", classroom["program_id"]) if classroom else None)
    # Pipeline: state (P6) -> uniqueness / double-booking (P8) -> clearance (P9).
    if ra["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "only a PROPOSED assignment may be confirmed")
    volunteer = store.get("volunteers", ra["volunteer_id"])
    if ra["role"] == "LEAD_TEACHER":
        for other in store.all_of("role_assignments"):
            if (
                other["id"] != ra["id"]
                and other["classroom_id"] == ra["classroom_id"]
                and other["role"] == "LEAD_TEACHER"
                and other["status"] == "CONFIRMED"
            ):
                raise_err(ERR_LEAD_TEACHER_TAKEN, "a CONFIRMED lead teacher already exists in this classroom")
    if ra["role"] in ("LEAD_TEACHER", "ASSISTANT_TEACHER"):
        for other in store.all_of("role_assignments"):
            if (
                other["id"] == ra["id"]
                or other["volunteer_id"] != ra["volunteer_id"]
                or other["status"] != "CONFIRMED"
                or other["role"] not in ("LEAD_TEACHER", "ASSISTANT_TEACHER")
            ):
                continue
            other_classroom = store.get("classrooms", other["classroom_id"])
            if (
                other_classroom is not None
                and classroom is not None
                and other_classroom["program_id"] == classroom["program_id"]
                and other["classroom_id"] != ra["classroom_id"]
            ):
                raise_err(ERR_VOLUNTEER_DOUBLE_BOOKED,
                          "volunteer already holds a CONFIRMED child-facing assignment in another classroom")
    if volunteer is None or volunteer["status"] != "CLEARED":
        raise_err(ERR_VOLUNTEER_NOT_CLEARED, "volunteer is not CLEARED")
    confirm_assignment(ra)
    return ok_object(role_assignment_view(ra))


@bp.post("/vbs/role-assignments/<assignment_id>/release")
def release(assignment_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "VolunteerCoordinator")
    ra = get_assignment_or_404(assignment_id)
    classroom = store.get("classrooms", ra["classroom_id"])
    guard_program_writable(store.get("programs", classroom["program_id"]) if classroom else None)
    if ra["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "only a CONFIRMED assignment may be released")
    ra["status"] = "RELEASED"
    ra["released_at"] = clock.now()
    store.touch(ra)
    return ok_object(role_assignment_view(ra))


@bp.get("/vbs/role-assignments/<assignment_id>")
def get_assignment(assignment_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "VolunteerCoordinator", "SafetyOfficer", "Volunteer")
    ra = store.get("role_assignments", assignment_id)
    if ra is not None and ctx.role == "Volunteer" and ra["volunteer_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "volunteers may only read their own assignments")
    if ra is None:
        raise_err(ERR_NOT_FOUND, "role assignment not found")
    return ok_object(role_assignment_view(ra))


@bp.get("/vbs/role-assignments")
def list_assignments():
    ctx = authenticate()
    require_role(ctx, "VolunteerCoordinator", "SafetyOfficer")
    items = list(store.all_of("role_assignments"))
    volunteer_id = request.args.get("volunteer_id")
    classroom_id = request.args.get("classroom_id")
    status = request.args.get("status")
    if volunteer_id is not None:
        items = [r for r in items if r["volunteer_id"] == volunteer_id]
    if classroom_id is not None:
        items = [r for r in items if r["classroom_id"] == classroom_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, role_assignment_view)
