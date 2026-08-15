"""Classrooms: create, read, list, OCC-guarded patch, close (PRD §3.1)."""

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from cascade import cancel_registration, seat_freed
from derived import classroom_view, enrolled_count, open_seats
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_CAPACITY_BELOW_ENROLLED,
    ERR_CLASSROOM_NOT_EMPTY,
)
from routes.common import paginate, empty_body, guard_program_writable
from validate import Field, get_body, validate_body, bad

bp = Blueprint("classrooms", __name__)

_READ_ROLES = (
    "ProgramDirector", "RegistrationCoordinator", "VolunteerCoordinator",
    "SafetyOfficer", "CheckInStaff", "Parent", "Volunteer",
)

_CREATE_SPEC = {
    "program_id": Field("str", required=True),
    "name": Field("str", required=True),
    "age_min": Field("int", required=True),
    "age_max": Field("int", required=True),
    "capacity": Field("int", required=True),
}

_PATCH_SPEC = {
    "capacity": Field("int"),
    "age_min": Field("int"),
    "age_max": Field("int"),
    "expected_classroom_version": Field("int", required=True),
}


def get_classroom_or_404(classroom_id):
    classroom = store.get("classrooms", classroom_id)
    if classroom is None:
        raise_err(ERR_NOT_FOUND, "classroom not found")
    return classroom


@bp.post("/vbs/classrooms")
def create_classroom():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    if data["age_min"] < 0:
        bad("age_min must be >= 0")
    if data["age_max"] < data["age_min"]:
        bad("age_min must not be greater than age_max")
    if data["capacity"] < 1:
        bad("capacity must be >= 1")
    ctx = authenticate()
    require_role(ctx, "RegistrationCoordinator")
    program = store.get("programs", data["program_id"])
    if program is None:
        raise_err(ERR_NOT_FOUND, "program not found")
    if program["status"] not in ("DRAFT", "REGISTRATION_OPEN"):
        raise_err(
            ERR_INVALID_STATE,
            "classrooms may be created only while the program is DRAFT or REGISTRATION_OPEN",
        )
    initial = "ACCEPTING" if program["status"] == "REGISTRATION_OPEN" else "SETUP"
    classroom = store.new_record(
        program_id=program["id"],
        name=data["name"],
        age_min=data["age_min"],
        age_max=data["age_max"],
        capacity=data["capacity"],
        status=initial,
    )
    store.put("classrooms", classroom)
    return ok_object(classroom_view(classroom), status=201)


@bp.get("/vbs/classrooms/<classroom_id>")
def get_classroom(classroom_id):
    ctx = authenticate()
    require_role(ctx, *_READ_ROLES)
    return ok_object(classroom_view(get_classroom_or_404(classroom_id)))


@bp.get("/vbs/classrooms")
def list_classrooms():
    ctx = authenticate()
    require_role(
        ctx,
        "ProgramDirector", "RegistrationCoordinator", "VolunteerCoordinator",
        "SafetyOfficer", "CheckInStaff", "Parent",
    )
    items = list(store.all_of("classrooms"))
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items, classroom_view)


@bp.patch("/vbs/classrooms/<classroom_id>")
def patch_classroom(classroom_id):
    body = get_body()
    data = validate_body(body, _PATCH_SPEC)
    if "capacity" in data and data["capacity"] < 1:
        bad("capacity must be >= 1")
    ctx = authenticate()
    require_role(ctx, "RegistrationCoordinator")
    classroom = get_classroom_or_404(classroom_id)
    # Merged age-band well-formedness.
    new_min = data.get("age_min", classroom["age_min"])
    new_max = data.get("age_max", classroom["age_max"])
    if new_min < 0:
        bad("age_min must be >= 0")
    if new_max < new_min:
        bad("age_min must not be greater than age_max")
    # Priority 4 (OCC) ahead of every business rule.
    if data["expected_classroom_version"] != classroom["version"]:
        raise_err(ERR_STALE_VERSION, "expected_classroom_version does not match the classroom version")
    program = store.get("programs", classroom["program_id"])
    guard_program_writable(program)
    if program is not None and program["status"] not in ("DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED"):
        raise_err(ERR_INVALID_STATE, "program status does not permit classroom edits")
    if classroom["status"] == "CLOSED":
        raise_err(ERR_INVALID_STATE, "classroom is CLOSED")
    if "capacity" in data and data["capacity"] < enrolled_count(classroom):
        raise_err(ERR_CAPACITY_BELOW_ENROLLED, "capacity may not drop below the enrolled count")
    if "capacity" in data:
        classroom["capacity"] = data["capacity"]
    if "age_min" in data:
        classroom["age_min"] = data["age_min"]
    if "age_max" in data:
        classroom["age_max"] = data["age_max"]
    store.touch(classroom)
    # A capacity increase that reopens seats while FULL flips back and runs the waterfall.
    if classroom["status"] == "FULL" and open_seats(classroom) >= 1:
        seat_freed(classroom)
    return ok_object(classroom_view(classroom))


@bp.post("/vbs/classrooms/<classroom_id>/close")
def close_classroom(classroom_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "RegistrationCoordinator")
    classroom = get_classroom_or_404(classroom_id)
    guard_program_writable(store.get("programs", classroom["program_id"]))
    if classroom["status"] == "CLOSED":
        raise_err(ERR_INVALID_STATE, "classroom is already CLOSED")
    if enrolled_count(classroom) > 0:
        raise_err(ERR_CLASSROOM_NOT_EMPTY, "classroom still has enrolled children")
    for reg in list(store.all_of("registrations")):
        if reg["classroom_id"] == classroom["id"] and reg["status"] in ("WAITLISTED", "OFFERED"):
            cancel_registration(reg, "CLASSROOM_CLOSED", run_cascade=False)
    for ra in list(store.all_of("role_assignments")):
        if ra["classroom_id"] == classroom["id"] and ra["status"] == "CONFIRMED":
            ra["status"] = "RELEASED"
            ra["released_at"] = clock.now()
            store.touch(ra)
    classroom["status"] = "CLOSED"
    store.touch(classroom)
    return ok_object(classroom_view(classroom))
