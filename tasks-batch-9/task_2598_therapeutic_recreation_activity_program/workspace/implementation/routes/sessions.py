"""Session calendar endpoints (PRD 3.4 / 3.6)."""
from flask import Blueprint

import serializers
from db import iso, parse_datetime, store
from errors import ApiError
from helpers import ctx, load, new_entity, paginate, resolve_fk
from middleware import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RECREATION_THERAPIST,
    ROLE_VOLUNTEER_COORDINATOR,
    authorize,
    filter_arg,
    pagination,
)
from response import list_response, object_response
from services import plans as plan_svc
from services import sessions as session_svc
from services import volunteers as volunteer_svc
from validation import bad, read_body, validate

bp = Blueprint("sessions", __name__)

CREATE_SPEC = {
    "program_id": {"type": "id", "required": True},
    "room_id": {"type": "id", "required": True},
    "starts_at": {"type": "datetime", "required": True},
    "ends_at": {"type": "datetime", "required": True},
    "assigned_staff_count": {"type": "int", "min": 1, "max": 20, "required": True},
}

STATUS_SPEC = {
    "action": {
        "type": "enum",
        "values": ["START", "CLOSE_DOCUMENTATION", "CANCEL"],
        "required": True,
    },
    "cancel_reason": {"type": "string", "max_len": 500},
}


@bp.post("/sessions")
def create_session():
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_RECREATION_THERAPIST)
    body = read_body()
    program = resolve_fk(body, "program_id", "program")
    room = resolve_fk(body, "room_id", "room")
    values = validate(body, CREATE_SPEC)
    starts_at = values["starts_at"]
    ends_at = values["ends_at"]
    if ends_at <= starts_at:
        raise ApiError("ERR_TIME_WINDOW_INVALID")
    if starts_at < store.now():
        raise ApiError("ERR_SESSION_IN_PAST")
    if session_svc.room_conflict(store, room, starts_at, ends_at) is not None:
        raise ApiError("ERR_ROOM_TIME_CONFLICT")

    session = new_entity(
        {
            "program_id": program["id"],
            "room_id": room["id"],
            "starts_at": iso(starts_at),
            "ends_at": iso(ends_at),
            "assigned_staff_count": values["assigned_staff_count"],
            "status": "SCHEDULED",
            "enrolled_count": 0,
            "weighted_supervision_load": 0.0,
            "required_staff_count": 0,
            "effective_capacity": min(program["max_group_size"], room["capacity"]),
            "documented_at": None,
            "cancel_reason": None,
        }
    )
    store.sessions[session["id"]] = session
    return object_response(serializers.session(session), 201)


@bp.get("/sessions/<session_id>")
def get_session(session_id):
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_VOLUNTEER_COORDINATOR,
        ROLE_COMPLIANCE_OFFICER,
    )
    session = load("session", session_id)
    return object_response(serializers.session(session), 200)


@bp.get("/sessions")
def list_sessions():
    authorize(
        ROLE_ACTIVITY_DIRECTOR,
        ROLE_RECREATION_THERAPIST,
        ROLE_ACTIVITY_AIDE,
        ROLE_VOLUNTEER_COORDINATOR,
        ROLE_COMPLIANCE_OFFICER,
    )
    limit, offset = pagination()
    program_id = filter_arg("program_id")
    room_id = filter_arg("room_id")
    status = filter_arg("status")
    starts_from = filter_arg("starts_from")
    starts_to = filter_arg("starts_to")
    rows = list(store.sessions.values())
    if program_id:
        rows = [s for s in rows if s["program_id"] == program_id]
    if room_id:
        rows = [s for s in rows if s["room_id"] == room_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    if starts_from:
        lo = parse_datetime(starts_from)
        if lo is None:
            bad("starts_from must be an ISO 8601 UTC instant.")
        rows = [s for s in rows if parse_datetime(s["starts_at"]) >= lo]
    if starts_to:
        hi = parse_datetime(starts_to)
        if hi is None:
            bad("starts_to must be an ISO 8601 UTC instant.")
        rows = [s for s in rows if parse_datetime(s["starts_at"]) <= hi]
    rows.sort(key=lambda s: (s["starts_at"], s["created_at"], s["_seq"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serializers.session(s) for s in page], limit, offset, total)


@bp.post("/sessions/<session_id>/status")
def change_session_status(session_id):
    authorize(ROLE_ACTIVITY_DIRECTOR, ROLE_RECREATION_THERAPIST, ROLE_ACTIVITY_AIDE)
    session = load("session", session_id)
    body = read_body()
    values = validate(body, STATUS_SPEC)
    action = values["action"]
    if action == "CANCEL":
        if values["cancel_reason"] is None:
            bad("cancel_reason is required for the CANCEL action.")
    elif values["cancel_reason"] is not None:
        bad("cancel_reason is only accepted with the CANCEL action.")

    context = ctx()
    if action == "START":
        if session["status"] != "SCHEDULED":
            raise ApiError("ERR_SESSION_INVALID_STATE")
        if store.now() < parse_datetime(session["starts_at"]):
            raise ApiError("ERR_SESSION_INVALID_STATE")
        if not session_svc.has_active_roster(store, session["id"]):
            raise ApiError("ERR_SESSION_HAS_NO_ENROLLMENTS")
        session["status"] = "IN_PROGRESS"
        context.bump(session)
    elif action == "CLOSE_DOCUMENTATION":
        if session["status"] != "IN_PROGRESS":
            raise ApiError("ERR_SESSION_INVALID_STATE")
        if session_svc.pending_rows(store, session["id"]):
            raise ApiError("ERR_DOCUMENTATION_INCOMPLETE")
        session["status"] = "DOCUMENTED"
        session["documented_at"] = store.now_iso()
        context.bump(session)
        for record in session_svc.roster(store, session["id"]):
            if record["status"] in ("ATTENDED", "REFUSED", "ABSENT"):
                record["finalized_from"] = record["status"]
                record["status"] = "FINALIZED"
                context.bump(record)
        volunteer_svc.complete_for_session(store, session, context)
    else:
        if session["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError("ERR_SESSION_INVALID_STATE")
        session["status"] = "CANCELLED"
        session["cancel_reason"] = values["cancel_reason"]
        voided_residents = []
        for record in session_svc.roster(store, session["id"]):
            if record["status"] == "PLANNED":
                record["status"] = "VOID"
                context.bump(record)
                voided_residents.append(record["resident_id"])
        volunteer_svc.withdraw_for_session(
            store, session, "SESSION_CANCELLED", context
        )
        session_svc.recompute_session_counters(
            store, session, context, force_bump=True
        )
        for resident_id in dict.fromkeys(voided_residents):
            plan_svc.recompute_resident_plans(store, resident_id, context)
    return object_response(serializers.session(session), 200)
