"""PackingSession + PackingAssignment endpoints."""

from flask import Blueprint, request
from db import db, iso_z
from middleware import require_roles
from validate import (get_body, req_string, req_datetime, req_int,
                      parse_pagination)
from response import success_object, success_list
from errors import (not_found, invalid_state, already_terminal, invalid_enum,
                    invalid_request, self_service_forbidden, ApiError)
from services.core import session_overlap, volunteer_double_booked

bp = Blueprint("packing", __name__)

SESSION_STATUSES = {"SCHEDULED", "COMPLETED", "CANCELLED"}
SESSION_TERMINAL = {"COMPLETED", "CANCELLED"}
ASSIGNMENT_STATUSES = {"SIGNUP", "ATTENDED", "NO_SHOW", "CANCELLED"}
ASSIGNMENT_TERMINAL = {"ATTENDED", "NO_SHOW", "CANCELLED"}


def session_view(s):
    out = {k: v for k, v in s.items() if not k.startswith("_")}
    out["start_at"] = iso_z(s["_start_dt"])
    out["end_at"] = iso_z(s["_end_dt"])
    return out


def assignment_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def get_session_or_404(session_id):
    s = db.sessions.get(session_id)
    if s is None:
        raise not_found("Packing session not found.")
    return s


def get_assignment_or_404(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise not_found("Packing assignment not found.")
    return a


@bp.post("/api/packing-sessions")
def create_session():
    require_roles("ProgramAdmin")
    body = get_body()
    site_id = req_string(body, "site_id")
    title = req_string(body, "title")
    start_dt = req_datetime(body, "start_at")
    end_dt = req_datetime(body, "end_at")
    if end_dt <= start_dt:
        raise invalid_request("end_at must be strictly after start_at.")
    capacity = req_int(body, "capacity", min_v=1)
    if site_id not in db.sites:
        raise not_found("site_id does not resolve to an existing site.")
    # band 9.1: half-open overlap
    if session_overlap(site_id, start_dt, end_dt):
        raise ApiError("ERR_SESSION_WINDOW_OVERLAP", 409,
                       "Session window intersects another session at this site.")
    session = {
        "site_id": site_id,
        "title": title,
        "capacity": capacity,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    db.stamp_new(session)
    db.sessions[session["id"]] = session
    return success_object(session_view(session), 201)


@bp.get("/api/packing-sessions")
def list_sessions():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    site_id = request.args.get("site_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in SESSION_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.sessions.values(), key=lambda s: s["_seq"])
    if site_id:
        items = [s for s in items if s["site_id"] == site_id]
    if status_f:
        items = [s for s in items if s["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([session_view(s) for s in page], limit, offset, total)


@bp.get("/api/packing-sessions/<session_id>")
def get_session(session_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    s = get_session_or_404(session_id)
    return success_object(session_view(s))


@bp.post("/api/packing-sessions/<session_id>/cancel")
def cancel_session(session_id):
    require_roles("ProgramAdmin")
    s = get_session_or_404(session_id)
    if s["status"] in SESSION_TERMINAL:
        raise already_terminal("Packing session is in a terminal state.")
    if s["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be cancelled.")
    for a in db.assignments.values():
        if a["session_id"] == s["id"] and a["status"] == "SIGNUP":
            a["status"] = "CANCELLED"
            db.touch(a)
    s["status"] = "CANCELLED"
    db.touch(s)
    return success_object(session_view(s))


@bp.post("/api/packing-sessions/<session_id>/complete")
def complete_session(session_id):
    require_roles("ProgramAdmin")
    s = get_session_or_404(session_id)
    if s["status"] in SESSION_TERMINAL:
        raise already_terminal("Packing session is in a terminal state.")
    if s["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED session can be completed.")
    if db.now() < s["_end_dt"]:
        raise invalid_state("Session cannot complete before its end_at.")
    for a in db.assignments.values():
        if a["session_id"] == s["id"] and a["status"] == "SIGNUP":
            a["status"] = "NO_SHOW"
            db.touch(a)
    s["status"] = "COMPLETED"
    db.touch(s)
    return success_object(session_view(s))


@bp.post("/api/packing-sessions/<session_id>/assignments")
def signup_assignment(session_id):
    user_id, role = require_roles("Volunteer", "ProgramAdmin")
    s = get_session_or_404(session_id)
    body = get_body()
    volunteer_id = req_string(body, "volunteer_id")
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise not_found("volunteer_id does not resolve to an existing volunteer.")
    # terminal lockdown on session
    if s["status"] in SESSION_TERMINAL:
        raise already_terminal("Packing session is in a terminal state.")
    # band 6: session must be SCHEDULED; volunteer must be ACTIVE
    if s["status"] != "SCHEDULED":
        raise invalid_state("Session is not SCHEDULED.")
    if vol["status"] != "ACTIVE":
        raise invalid_state("Only ACTIVE volunteers may sign up.")
    # band 9.2: double-booking FIRST, then capacity (pinned order)
    if volunteer_double_booked(volunteer_id, s["_start_dt"], s["_end_dt"]):
        raise ApiError("ERR_VOLUNTEER_DOUBLE_BOOKED", 409,
                       "Volunteer has a touching or overlapping live assignment.")
    # band 11.4: capacity
    live = sum(1 for a in db.assignments.values()
               if a["session_id"] == s["id"] and a["status"] in ("SIGNUP", "ATTENDED"))
    if live >= s["capacity"]:
        raise ApiError("ERR_SESSION_CAPACITY_FULL", 422,
                       "Session capacity is full.")
    # band 12: ownership
    if role == "Volunteer" and volunteer_id != user_id:
        raise self_service_forbidden("Volunteer may sign up only itself.")
    assignment = {
        "session_id": s["id"],
        "volunteer_id": volunteer_id,
        "status": "SIGNUP",
    }
    db.stamp_new(assignment)
    db.assignments[assignment["id"]] = assignment
    return success_object(assignment_view(assignment), 201)


@bp.get("/api/packing-assignments")
def list_assignments():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    session_id = request.args.get("session_id")
    volunteer_id = request.args.get("volunteer_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in ASSIGNMENT_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.assignments.values(), key=lambda a: a["_seq"])
    if session_id:
        items = [a for a in items if a["session_id"] == session_id]
    if volunteer_id:
        items = [a for a in items if a["volunteer_id"] == volunteer_id]
    if status_f:
        items = [a for a in items if a["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([assignment_view(a) for a in page], limit, offset, total)


@bp.get("/api/packing-assignments/<assignment_id>")
def get_assignment(assignment_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    a = get_assignment_or_404(assignment_id)
    return success_object(assignment_view(a))


@bp.post("/api/packing-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    user_id, role = require_roles("Volunteer", "ProgramAdmin")
    a = get_assignment_or_404(assignment_id)
    if a["status"] in ASSIGNMENT_TERMINAL:
        raise already_terminal("Packing assignment is in a terminal state.")
    if a["status"] != "SIGNUP":
        raise invalid_state("Only a SIGNUP assignment can be cancelled.")
    # band 12: ownership
    if role == "Volunteer" and a["volunteer_id"] != user_id:
        raise self_service_forbidden("Volunteer may cancel only its own assignments.")
    a["status"] = "CANCELLED"
    db.touch(a)
    return success_object(assignment_view(a))


@bp.post("/api/packing-assignments/<assignment_id>/mark-attended")
def mark_attended(assignment_id):
    require_roles("ProgramAdmin")
    a = get_assignment_or_404(assignment_id)
    if a["status"] in ASSIGNMENT_TERMINAL:
        raise already_terminal("Packing assignment is in a terminal state.")
    if a["status"] != "SIGNUP":
        raise invalid_state("Only a SIGNUP assignment can be marked attended.")
    s = db.sessions.get(a["session_id"])
    if s is None or s["status"] not in ("SCHEDULED", "COMPLETED"):
        raise invalid_state("Session must be SCHEDULED or COMPLETED.")
    a["status"] = "ATTENDED"
    db.touch(a)
    return success_object(assignment_view(a))
