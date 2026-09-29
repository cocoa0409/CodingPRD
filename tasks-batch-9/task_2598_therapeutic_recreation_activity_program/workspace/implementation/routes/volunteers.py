"""Volunteer registration, the screening lifecycle and assignments (PRD 3.7)."""
from flask import Blueprint

import serializers
from db import add_days, date_str, parse_date, parse_datetime, store
from errors import ApiError
from helpers import ctx, load, new_entity, paginate, resolve_fk
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_VOLUNTEER,
    ROLE_VOLUNTEER_COORDINATOR,
    authorize,
    deny,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import constants as C
from services import volunteers as volunteer_svc
from validation import read_body, validate

bp = Blueprint("volunteers", __name__)

CREATE_SPEC = {
    "full_name": {"type": "string", "max_len": 120, "required": True},
    "volunteer_type": {"type": "enum", "values": C.VOLUNTEER_TYPES, "required": True},
}

SCREENING_SPEC = {
    "event_type": {
        "type": "enum",
        "values": [
            "BACKGROUND_CHECK_CLEARED",
            "ORIENTATION_COMPLETED",
            "EXPIRE",
            "SUSPEND",
            "REINSTATE",
            "TERMINATE",
        ],
        "required": True,
    },
    "cleared_on": {"type": "date"},
    "completed_on": {"type": "date"},
}

ASSIGN_SPEC = {
    "volunteer_id": {"type": "id", "required": True},
    "session_id": {"type": "id", "required": True},
    "role_type": {"type": "enum", "values": C.ROLE_TYPES, "required": True},
}

PATCH_SPEC = {
    "status": {
        "type": "enum",
        "values": ["PROPOSED", "CONFIRMED", "WITHDRAWN", "COMPLETED"],
        "required": True,
    },
    "withdrawn_reason": {"type": "string", "max_len": 200},
}

EVENT_SOURCES = {
    "BACKGROUND_CHECK_CLEARED": ("APPLICANT", "EXPIRED"),
    "ORIENTATION_COMPLETED": ("SCREENING",),
    "EXPIRE": ("CLEARED",),
    "SUSPEND": ("CLEARED",),
    "REINSTATE": ("SUSPENDED",),
    "TERMINATE": ("SUSPENDED",),
}


def _expires_on(volunteer):
    return parse_date(volunteer.get("background_check_expires_on"))


@bp.post("/volunteers")
def create_volunteer():
    authorize(ROLE_VOLUNTEER_COORDINATOR)
    body = read_body()
    values = validate(body, CREATE_SPEC)
    volunteer = new_entity(
        {
            "full_name": values["full_name"],
            "volunteer_type": values["volunteer_type"],
            "screening_level": "NONE",
            "background_check_cleared_on": None,
            "background_check_expires_on": None,
            "orientation_completed_on": None,
            "status": "APPLICANT",
            "scheduled_hours_week": 0.0,
            "credited_service_hours": 0.0,
        }
    )
    store.volunteers[volunteer["id"]] = volunteer
    return object_response(serializers.volunteer(volunteer), 201)


@bp.post("/volunteers/<volunteer_id>/screening")
def record_screening(volunteer_id):
    authorize(ROLE_VOLUNTEER_COORDINATOR)
    body = read_body()
    volunteer = load("volunteer", volunteer_id)
    values = validate(body, SCREENING_SPEC)
    event = values["event_type"]
    today = store.today()
    context = ctx()

    # Rank 15: the event must be declared for the volunteer's current status.
    if volunteer["status"] not in EVENT_SOURCES[event]:
        raise ApiError("ERR_VOLUNTEER_INVALID_STATE")

    if event == "BACKGROUND_CHECK_CLEARED":
        cleared_on = values["cleared_on"]
        if cleared_on is None or cleared_on > today:
            raise ApiError("ERR_VOLUNTEER_INVALID_STATE")
        volunteer["background_check_cleared_on"] = date_str(cleared_on)
        volunteer["background_check_expires_on"] = date_str(
            add_days(cleared_on, C.BACKGROUND_CHECK_VALID_DAYS)
        )
        volunteer["screening_level"] = "BASIC"
        volunteer["status"] = "SCREENING"
    elif event == "ORIENTATION_COMPLETED":
        expires = _expires_on(volunteer)
        if volunteer["background_check_cleared_on"] is None:
            raise ApiError("ERR_VOLUNTEER_INVALID_STATE")
        if expires is None or expires < today:
            raise ApiError("ERR_VOLUNTEER_INVALID_STATE")
        completed_on = values["completed_on"]
        volunteer["orientation_completed_on"] = date_str(
            completed_on if completed_on is not None else today
        )
        volunteer["screening_level"] = "FULL"
        volunteer["status"] = "CLEARED"
    elif event == "EXPIRE":
        expires = _expires_on(volunteer)
        if expires is None or not expires < today:
            raise ApiError("ERR_VOLUNTEER_INVALID_STATE")
        volunteer["status"] = "EXPIRED"
        volunteer_svc.withdraw_for_volunteer(
            store, volunteer, "CLEARANCE_EXPIRED", context
        )
    elif event == "SUSPEND":
        volunteer["status"] = "SUSPENDED"
        volunteer_svc.withdraw_for_volunteer(
            store, volunteer, "VOLUNTEER_SUSPENDED", context
        )
    elif event == "REINSTATE":
        expires = _expires_on(volunteer)
        if expires is None or expires < today:
            raise ApiError("ERR_VOLUNTEER_INVALID_STATE")
        if volunteer["orientation_completed_on"] is None:
            raise ApiError("ERR_VOLUNTEER_INVALID_STATE")
        volunteer["status"] = "CLEARED"
    else:
        volunteer["status"] = "TERMINATED"
        volunteer_svc.withdraw_for_volunteer(
            store, volunteer, "VOLUNTEER_SUSPENDED", context
        )

    volunteer_svc.refresh_hours(store, volunteer, context)
    context.bump(volunteer)
    return object_response(serializers.volunteer(volunteer), 200)


@bp.get("/volunteers/<volunteer_id>")
def get_volunteer(volunteer_id):
    authorize(
        ROLE_VOLUNTEER_COORDINATOR, ROLE_ACTIVITY_DIRECTOR, ROLE_COMPLIANCE_OFFICER
    )
    volunteer = load("volunteer", volunteer_id)
    return object_response(serializers.volunteer(volunteer), 200)


def _screening_ok(volunteer, program):
    if program is None:
        return False
    if not program.get("volunteer_eligible"):
        return False
    have = C.SCREENING_RANK.get(volunteer["screening_level"], 0)
    need = C.SCREENING_RANK.get(program["required_screening_level"], 0)
    return have >= need


@bp.post("/volunteer-assignments")
def create_assignment():
    authorize(ROLE_VOLUNTEER_COORDINATOR)
    body = read_body()
    volunteer = resolve_fk(body, "volunteer_id", "volunteer")
    session = resolve_fk(body, "session_id", "session")
    values = validate(body, ASSIGN_SPEC)
    role_type = values["role_type"]
    program = store.programs.get(session["program_id"])

    # Rank 11: a volunteer may only be assigned to a SCHEDULED session.
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_INVALID_STATE")
    # Rank 27: a volunteer is never double-booked (no turnover buffer on people).
    if volunteer_svc.time_conflict(store, volunteer["id"], session) is not None:
        raise ApiError("ERR_VOLUNTEER_TIME_CONFLICT")
    # Rank 32: only a CLEARED volunteer may be assigned.
    if volunteer["status"] != "CLEARED":
        raise ApiError("ERR_VOLUNTEER_CLEARANCE_EXPIRED")
    # Rank 33: screening depth plus the program's volunteer_eligible flag.
    if not _screening_ok(volunteer, program):
        raise ApiError("ERR_VOLUNTEER_SCREENING_INSUFFICIENT")
    # Rank 34: intergenerational supervision floor for student volunteers.
    if volunteer["volunteer_type"] == "STUDENT_INTERGENERATIONAL":
        if session["assigned_staff_count"] < 2 or role_type == "PROGRAM_LEAD":
            raise ApiError("ERR_INTERGENERATIONAL_SUPERVISION_MISSING")
    # Rank 51: the weekly hour cap, measured with the new assignment included.
    hours = volunteer_svc.assignment_hours(session)
    candidate = {"status": "PROPOSED", "session_id": session["id"], "hours": hours}
    projected = volunteer_svc.scheduled_hours_week(
        store, volunteer["id"], extra_assignments=[candidate]
    )
    if volunteer_svc.hour_cap_exceeded(projected):
        raise ApiError("ERR_VOLUNTEER_HOUR_CAP_EXCEEDED")

    context = ctx()
    assignment = new_entity(
        {
            "volunteer_id": volunteer["id"],
            "session_id": session["id"],
            "role_type": role_type,
            "status": "PROPOSED",
            "hours": hours,
            "withdrawn_reason": None,
        }
    )
    store.assignments[assignment["id"]] = assignment
    volunteer_svc.refresh_hours(store, volunteer, context, force_bump=True)
    return object_response(serializers.assignment(assignment), 201)


@bp.patch("/volunteer-assignments/<assignment_id>")
def update_assignment(assignment_id):
    actor = authorize(ROLE_VOLUNTEER_COORDINATOR, ROLE_VOLUNTEER)
    body = read_body()
    assignment = load("assignment", assignment_id)
    # Rank 2: the entity-backed Volunteer ownership check is an authorization
    # failure, never a 404 and never a 422.
    if actor.role == ROLE_VOLUNTEER and assignment["volunteer_id"] != actor.user_id:
        deny()
    values = validate(body, PATCH_SPEC)
    status = values["status"]
    if actor.role == ROLE_VOLUNTEER and status != "WITHDRAWN":
        deny()
    if status == "WITHDRAWN":
        if values["withdrawn_reason"] is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "withdrawn_reason is required on a withdrawal."
            )
    elif values["withdrawn_reason"] is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "withdrawn_reason is only accepted on a withdrawal.",
        )

    volunteer = store.volunteers.get(assignment["volunteer_id"])
    session = store.sessions.get(assignment["session_id"])
    context = ctx()

    if status == "CONFIRMED":
        # Rank 16 first: the assignment's own state.
        if assignment["status"] != "PROPOSED":
            raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
        if session is None or session["status"] != "SCHEDULED":
            raise ApiError("ERR_SESSION_INVALID_STATE")
        if volunteer is None or volunteer["status"] != "CLEARED":
            raise ApiError("ERR_VOLUNTEER_CLEARANCE_EXPIRED")
        expires = _expires_on(volunteer)
        ends_at = parse_datetime(session["ends_at"])
        if expires is None or (ends_at is not None and expires < ends_at.date()):
            raise ApiError("ERR_VOLUNTEER_CLEARANCE_EXPIRED")
        program = store.programs.get(session["program_id"])
        if not _screening_ok(volunteer, program):
            raise ApiError("ERR_VOLUNTEER_SCREENING_INSUFFICIENT")
        if volunteer["volunteer_type"] == "STUDENT_INTERGENERATIONAL":
            if not volunteer_svc.program_lead_present(
                store, session["id"], ignore_assignment_id=assignment["id"]
            ):
                raise ApiError("ERR_INTERGENERATIONAL_SUPERVISION_MISSING")
        assignment["status"] = "CONFIRMED"
    elif status == "WITHDRAWN":
        if assignment["status"] not in ("PROPOSED", "CONFIRMED"):
            raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
        assignment["status"] = "WITHDRAWN"
        assignment["withdrawn_reason"] = values["withdrawn_reason"]
    else:
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")

    context.bump(assignment)
    if volunteer is not None:
        volunteer_svc.refresh_hours(store, volunteer, context, force_bump=True)
    return object_response(serializers.assignment(assignment), 200)


@bp.get("/volunteer-assignments/<assignment_id>")
def get_assignment(assignment_id):
    actor = authorize(
        ROLE_VOLUNTEER_COORDINATOR,
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_COMPLIANCE_OFFICER,
        ROLE_VOLUNTEER,
    )
    assignment = load("assignment", assignment_id)
    if actor.role == ROLE_VOLUNTEER and assignment["volunteer_id"] != actor.user_id:
        deny()
    return object_response(serializers.assignment(assignment), 200)


@bp.get("/volunteer-assignments")
def list_assignments():
    actor = authorize(
        ROLE_VOLUNTEER_COORDINATOR,
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_ACTIVITY_AIDE,
        ROLE_COMPLIANCE_OFFICER,
        ROLE_VOLUNTEER,
    )
    limit, offset = pagination()
    volunteer_id = filter_arg("volunteer_id")
    session_id = filter_arg("session_id")
    status = filter_arg("status")
    rows = list(store.assignments.values())
    if actor.role == ROLE_VOLUNTEER:
        rows = [a for a in rows if a["volunteer_id"] == actor.user_id]
    if volunteer_id:
        rows = [a for a in rows if a["volunteer_id"] == volunteer_id]
    if session_id:
        rows = [a for a in rows if a["session_id"] == session_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.assignment(a) for a in page], limit, offset, total
    )
