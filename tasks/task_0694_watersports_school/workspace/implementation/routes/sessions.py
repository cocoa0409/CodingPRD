"""Session routes: schedule, weather-hold/clear (cyclic), start, complete, cancel."""
from flask import Blueprint, request

import db
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_SCHOOL_STORM_CLOSED, ERR_INSTRUCTOR_NOT_CERTIFIED, ERR_TIDE_WINDOW_INVALID,
    ERR_INSTRUCTOR_DOUBLE_BOOKED,
)
from middleware import get_identity, require_role
from response import success, success_list
from services import derive
from util import (
    parse_dt, require_str, require_int, parse_pagination, paginate, touch,
)

bp = Blueprint("sessions", __name__)
READ_ROLES = {"SchoolAdmin", "Instructor", "Student"}
NON_TERMINAL_SESSION = {"SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def _instructor_is_lead(role, user_id, session):
    """Instructor may only act on a session whose instructor_id == own id (PRD §2.1)."""
    if role == "Instructor" and user_id != session["instructor_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the session's lead instructor")


@bp.route("/sessions", methods=["POST"])
def create_session():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    body = _body()
    school_id = require_str(body, "school_id")
    course_level_id = require_str(body, "course_level_id")
    instructor_id = require_str(body, "instructor_id")
    for f in ("starts_at", "ends_at", "tide_window_start", "tide_window_end"):
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, f"missing required field: {f}")
    starts_at = parse_dt(body["starts_at"], "starts_at")
    ends_at = parse_dt(body["ends_at"], "ends_at")
    tide_start = parse_dt(body["tide_window_start"], "tide_window_start")
    tide_end = parse_dt(body["tide_window_end"], "tide_window_end")
    capacity = require_int(body, "capacity", minimum=1)
    if ends_at <= starts_at:
        raise err(ERR_VALIDATION, "ends_at must be after starts_at")

    with db.lock():
        # FK existence within school (priority 4).
        school = db.schools.get(school_id)
        if school is None:
            raise err(ERR_NOT_FOUND, "school not found")
        level = db.levels.get(course_level_id)
        if level is None or level["school_id"] != school_id:
            raise err(ERR_NOT_FOUND, "course level not found")
        instructor = db.instructors.get(instructor_id)
        if instructor is None or instructor["school_id"] != school_id:
            raise err(ERR_NOT_FOUND, "instructor not found")

        # priority 8: storm closure blocks scheduling.
        if derive.school_operating_status(school) == "STORM_CLOSED":
            raise err(ERR_SCHOOL_STORM_CLOSED, "school is storm-closed")
        # priority 12: instructor certified for discipline.
        course = db.courses.get(level["course_id"])
        discipline = course["discipline"] if course else None
        if discipline not in instructor["certified_disciplines"]:
            raise err(ERR_INSTRUCTOR_NOT_CERTIFIED, "instructor not certified for discipline")
        # priority 14: tide window contains session interval.
        if not (tide_start <= starts_at and ends_at <= tide_end):
            raise err(ERR_TIDE_WINDOW_INVALID, "tide window does not contain session")
        # priority 15: instructor double-booking (half-open overlap).
        for other in db.sessions.values():
            if other["instructor_id"] != instructor_id:
                continue
            if other["status"] not in NON_TERMINAL_SESSION:
                continue
            os = parse_dt(other["starts_at"], "starts_at")
            oe = parse_dt(other["ends_at"], "ends_at")
            # half-open overlap: [a,b) overlaps [c,d) iff a < d and c < b
            if starts_at < oe and os < ends_at:
                raise err(ERR_INSTRUCTOR_DOUBLE_BOOKED, "instructor double-booked")

        now = db.now_iso()
        sid = db.new_id()
        rec = {
            "id": sid, "school_id": school_id, "course_level_id": course_level_id,
            "instructor_id": instructor_id,
            "starts_at": body["starts_at"], "ends_at": body["ends_at"],
            "tide_window_start": body["tide_window_start"],
            "tide_window_end": body["tide_window_end"],
            "capacity": capacity, "status": "SCHEDULED",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.sessions[sid] = rec
        # School.open_session_count is derived; touch school so it advances.
        touch(school)
        return success(derive.serialize_session(rec), 201)


@bp.route("/sessions", methods=["GET"])
def list_sessions():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    course_level_id = request.args.get("course_level_id")
    instructor_id = request.args.get("instructor_id")
    rows = [
        s for s in db.sessions.values()
        if (school_id is None or s["school_id"] == school_id)
        and (course_level_id is None or s["course_level_id"] == course_level_id)
        and (instructor_id is None or s["instructor_id"] == instructor_id)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_session(r) for r in page], limit, offset, total)


@bp.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.sessions.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "session not found")
    return success(derive.serialize_session(rec), 200)


@bp.route("/sessions/<sid>/weather-hold", methods=["POST"])
def weather_hold(sid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.sessions.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "session not found")
        if rec["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "session is not SCHEDULED")
        rec["status"] = "WEATHER_HOLD"
        touch(rec)
        return success(derive.serialize_session(rec), 200)


@bp.route("/sessions/<sid>/clear-hold", methods=["POST"])
def clear_hold(sid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.sessions.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "session not found")
        if rec["status"] != "WEATHER_HOLD":
            raise err(ERR_INVALID_STATE, "session is not WEATHER_HOLD")
        school = db.schools.get(rec["school_id"])
        if school is not None and derive.school_operating_status(school) == "STORM_CLOSED":
            raise err(ERR_SCHOOL_STORM_CLOSED, "school is storm-closed")
        rec["status"] = "SCHEDULED"
        touch(rec)
        return success(derive.serialize_session(rec), 200)


@bp.route("/sessions/<sid>/start", methods=["POST"])
def start_session(sid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Instructor"})
    with db.lock():
        rec = db.sessions.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "session not found")
        _instructor_is_lead(role, user_id, rec)
        if rec["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "session is not SCHEDULED")
        school = db.schools.get(rec["school_id"])
        if school is not None and derive.school_operating_status(school) == "STORM_CLOSED":
            raise err(ERR_SCHOOL_STORM_CLOSED, "school is storm-closed")
        now = clock.get()
        tide_start = parse_dt(rec["tide_window_start"], "tide_window_start")
        tide_end = parse_dt(rec["tide_window_end"], "tide_window_end")
        # within tide window: >= start and strictly < end (PRD §3.6).
        if not (now >= tide_start and now < tide_end):
            raise err(ERR_INVALID_STATE, "outside tide window")
        rec["status"] = "IN_PROGRESS"
        touch(rec)
        return success(derive.serialize_session(rec), 200)


@bp.route("/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Instructor"})
    with db.lock():
        rec = db.sessions.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "session not found")
        _instructor_is_lead(role, user_id, rec)
        if rec["status"] != "IN_PROGRESS":
            raise err(ERR_INVALID_STATE, "session is not IN_PROGRESS")
        rec["status"] = "COMPLETED"
        touch(rec)
        # BRANCH: CHECKED_IN -> ATTENDED (enrollment attended_count derived),
        # BOOKED -> NO_SHOW (PRD §3.6).
        for b in db.bookings.values():
            if b["session_id"] != sid:
                continue
            if b["status"] == "CHECKED_IN":
                b["status"] = "ATTENDED"
                touch(b)
                enr = db.enrollments.get(b["enrollment_id"])
                if enr is not None:
                    touch(enr)  # attended_count is derived; advance enrollment
            elif b["status"] == "BOOKED":
                b["status"] = "NO_SHOW"
                touch(b)
        # School.open_session_count derived; touch school.
        school = db.schools.get(rec["school_id"])
        if school is not None:
            touch(school)
        return success(derive.serialize_session(rec), 200)


@bp.route("/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.sessions.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "session not found")
        if rec["status"] not in ("SCHEDULED", "WEATHER_HOLD"):
            raise err(ERR_INVALID_STATE, "session not in SCHEDULED or WEATHER_HOLD")
        rec["status"] = "CANCELLED"
        touch(rec)
        # CASCADE hop1: non-terminal bookings -> CANCELLED;
        # hop2: +1 makeup credit per affected ACTIVE-member booking (PRD §3.6).
        for b in db.bookings.values():
            if b["session_id"] != sid:
                continue
            if b["status"] in ("BOOKED", "CHECKED_IN"):
                b["status"] = "CANCELLED"
                touch(b)
                enr = db.enrollments.get(b["enrollment_id"])
                if enr is not None:
                    touch(enr)
                    if enr["membership_id"]:
                        m = db.memberships.get(enr["membership_id"])
                        if m is not None and m["status"] == "ACTIVE":
                            m["makeup_credit_balance"] += 1
                            touch(m)
        school = db.schools.get(rec["school_id"])
        if school is not None:
            touch(school)
        return success(derive.serialize_session(rec), 200)
