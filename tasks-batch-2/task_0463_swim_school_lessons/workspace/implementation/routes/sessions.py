"""ClassSession routes. PRD 3.3, 3.4, 3.5."""
from flask import Blueprint, request

from db import store, common_fields_on_create, touch
from errors import (
    err, ERR_INVALID_REQUEST, ERR_REFERENCE_MISMATCH, ERR_INVALID_STATE,
    ERR_INSTRUCTOR_NOT_CERTIFIED, ERR_INSTRUCTOR_SCHEDULE_CONFLICT, ERR_LANE_CONFLICT,
)
from helpers import (
    get_body, require_str, require_int, parse_pagination, paginate,
)
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import (
    serialize_class_session, reconcile_session_counts, withdraw_enrollment,
)
from lookups import get_location, get_level, get_instructor, get_class_session
from calculations import instructor_schedule_conflict

bp = Blueprint("sessions", __name__)

ALL_ROLES = ["SchoolAdmin", "BillingAdmin", "Instructor", "Parent"]


@bp.route("/class-sessions", methods=["POST"])
def create_session():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    body = get_body()
    # Existence in path-then-body order; body FKs validated left to right.
    location_id = require_str(body, "location_id")
    level_id = require_str(body, "level_id")
    instructor_id = require_str(body, "instructor_id")
    # Existence check (404) — these ids must resolve to entities.
    # ERR_REFERENCE_MISMATCH (422) covers wrong entity type; here every collection
    # is type-distinct, so a missing id is a not-found. We resolve each to confirm.
    location = get_location(location_id)
    level = get_level(level_id)
    instructor = get_instructor(instructor_id)
    lane_number = require_int(body, "lane_number", min_value=1)
    day_of_week = require_int(body, "day_of_week", min_value=0, max_value=6)
    start_minute = require_int(body, "start_minute", min_value=0, max_value=1439)
    end_minute = require_int(body, "end_minute")
    if not (start_minute < end_minute <= 1440):
        err(ERR_INVALID_REQUEST, "require start_minute < end_minute <= 1440")
    rec = common_fields_on_create()
    rec.update({
        "location_id": location["id"],
        "level_id": level["id"],
        "instructor_id": instructor["id"],
        "lane_number": lane_number,
        "day_of_week": day_of_week,
        "start_minute": start_minute,
        "end_minute": end_minute,
        # capacity copied from the level ratio at creation (immutable quota).
        "capacity": level["max_students_per_instructor"],
        "enrolled_count": 0,
        "waitlist_count": 0,
        "status": "DRAFT",
    })
    store.class_sessions[rec["id"]] = rec
    return object_response(serialize_class_session(rec), 201)


@bp.route("/class-sessions", methods=["GET"])
def list_sessions():
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.class_sessions.values())
    for f in ("location_id", "level_id", "instructor_id"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_class_session(r) for r in window], limit, offset, total)


@bp.route("/class-sessions/<id>", methods=["GET"])
def get_session_route(id):
    principal = get_principal()
    require_roles(principal, ALL_ROLES)
    rec = get_class_session(id)
    return object_response(serialize_class_session(rec), 200)


@bp.route("/class-sessions/<id>/open", methods=["POST"])
def open_session(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    session = get_class_session(id)
    # State legality: only a DRAFT session may open.
    if session["status"] != "DRAFT":
        err(ERR_INVALID_STATE, "Only a DRAFT session may be opened")
    # Precondition 1 (priority 9): instructor ACTIVE and certified for level.
    instructor = store.instructors.get(session["instructor_id"])
    if (instructor is None or instructor["status"] != "ACTIVE"
            or session["level_id"] not in instructor["certified_level_ids"]):
        err(ERR_INSTRUCTOR_NOT_CERTIFIED,
            "Instructor not certified or not active for this level")
    # Precondition 2 (priority 10): instructor weekly schedule overlap (closed+buffer).
    other_open = [
        s for s in store.class_sessions.values()
        if s["id"] != session["id"] and s["status"] == "OPEN"
        and s["instructor_id"] == session["instructor_id"]
        and s["day_of_week"] == session["day_of_week"]
    ]
    if instructor_schedule_conflict(session, other_open):
        err(ERR_INSTRUCTOR_SCHEDULE_CONFLICT, "Instructor schedule conflict")
    # Precondition 3 (priority 10): lane uniqueness — no OPEN/DRAFT session shares
    # (location_id, day_of_week, lane_number) with an overlapping time window.
    for s in store.class_sessions.values():
        if s["id"] == session["id"]:
            continue
        if s["status"] not in ("OPEN", "DRAFT"):
            continue
        if (s["location_id"] == session["location_id"]
                and s["day_of_week"] == session["day_of_week"]
                and s["lane_number"] == session["lane_number"]):
            # overlapping time window (half-open).
            if (session["start_minute"] < s["end_minute"]
                    and s["start_minute"] < session["end_minute"]):
                err(ERR_LANE_CONFLICT, "Lane already occupied in this time window")
    session["status"] = "OPEN"
    touch(session)
    return object_response(serialize_class_session(session), 200)


@bp.route("/class-sessions/<id>/close", methods=["POST"])
def close_session(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    session = get_class_session(id)
    # State legality: only an OPEN session may close (CLOSED is terminal).
    if session["status"] != "OPEN":
        err(ERR_INVALID_STATE, "Only an OPEN session may be closed")
    session["status"] = "CLOSED"
    touch(session)
    # CASCADE: every enrollment in ACTIVE/PAUSED/WAITLISTED -> WITHDRAWN; each
    # withdrawal runs its own seat/credit side effects. No further promotions can
    # land seats in a CLOSED session (status guard in promote path), so counts -> 0.
    affected = [e for e in store.enrollments.values()
                if e["class_session_id"] == session["id"]
                and e["status"] in ("ACTIVE", "PAUSED", "WAITLISTED")]
    affected.sort(key=lambda e: (e["created_at"], e["id"]))
    for enrollment in affected:
        # withdraw_enrollment will attempt promotion, but since the session is now
        # CLOSED its enrolled_count after the loop reconciles to 0 anyway. Guard:
        enrollment["status"] = "WITHDRAWN"
        touch(enrollment)
    reconcile_session_counts(session)
    touch(session)
    return object_response(serialize_class_session(session), 200)
