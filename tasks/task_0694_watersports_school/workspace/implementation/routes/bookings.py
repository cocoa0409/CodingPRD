"""SessionBooking routes: create (OCC, capacity, makeup), check-in, cancel."""
from flask import Blueprint, request

import db
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION, ERR_SESSION_FULL, ERR_NO_MAKEUP_CREDIT,
    ERR_WAIVER_REQUIRED, ERR_SCHOOL_STORM_CLOSED,
)
from middleware import get_identity, require_role
from response import success, success_list
from services import derive
from util import (
    require_str, optional_bool, parse_pagination, paginate, touch,
)

bp = Blueprint("bookings", __name__)
READ_ROLES = {"SchoolAdmin", "Instructor", "Student"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def _booking_student_id(booking):
    enr = db.enrollments.get(booking["enrollment_id"])
    return enr["student_id"] if enr else None


@bp.route("/bookings", methods=["POST"])
def create_booking():
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    body = _body()
    session_id = require_str(body, "session_id")
    enrollment_id = require_str(body, "enrollment_id")
    if "expected_session_version" not in body or body["expected_session_version"] is None:
        raise err(ERR_VALIDATION, "missing required field: expected_session_version")
    expected = body["expected_session_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_VALIDATION, "expected_session_version must be an integer")
    use_makeup = optional_bool(body, "use_makeup_credit", False)

    with db.lock():
        # FK existence (priority 4).
        session = db.sessions.get(session_id)
        if session is None:
            raise err(ERR_NOT_FOUND, "session not found")
        enrollment = db.enrollments.get(enrollment_id)
        if enrollment is None:
            raise err(ERR_NOT_FOUND, "enrollment not found")

        # Ownership scoping for Student role (priority 5).
        if role == "Student" and user_id != enrollment["student_id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")

        # OCC (priority 6).
        if expected != session["version"]:
            raise err(ERR_STALE_VERSION, "session version mismatch")

        # Capacity (priority 18).
        if derive.session_enrolled_count(session_id) >= session["capacity"]:
            raise err(ERR_SESSION_FULL, "session is full")

        # Makeup credit (priority 19).
        membership = None
        if use_makeup:
            membership = db.memberships.get(enrollment["membership_id"]) if enrollment["membership_id"] else None
            bal = membership["makeup_credit_balance"] if membership else 0
            if bal < 1:
                raise err(ERR_NO_MAKEUP_CREDIT, "no makeup credit available")

        now = db.now_iso()
        bid = db.new_id()
        rec = {
            "id": bid, "session_id": session_id, "enrollment_id": enrollment_id,
            "is_makeup": bool(use_makeup), "status": "BOOKED",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.bookings[bid] = rec
        if use_makeup and membership is not None:
            membership["makeup_credit_balance"] -= 1
            touch(membership)
        # Adding a booking mutates the session: enrolled_count/required_instructors
        # recomputed (derived) and Session.version +1 (PRD §2.7).
        touch(session)
        return success(derive.serialize_booking(rec), 201)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    session_id = request.args.get("session_id")
    enrollment_id = request.args.get("enrollment_id")
    rows = [
        b for b in db.bookings.values()
        if (session_id is None or b["session_id"] == session_id)
        and (enrollment_id is None or b["enrollment_id"] == enrollment_id)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_booking(r) for r in page], limit, offset, total)


@bp.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.bookings.get(bid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "booking not found")
    return success(derive.serialize_booking(rec), 200)


@bp.route("/bookings/<bid>/check-in", methods=["POST"])
def check_in(bid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Instructor"})
    with db.lock():
        rec = db.bookings.get(bid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "booking not found")
        session = db.sessions.get(rec["session_id"])
        # Instructor must be the session's lead (PRD §2.1).
        if role == "Instructor" and session is not None and user_id != session["instructor_id"]:
            raise err(ERR_NOT_RESOURCE_OWNER, "not the session's lead instructor")
        # State legality (priority 7): booking must be BOOKED.
        if rec["status"] != "BOOKED":
            raise err(ERR_INVALID_STATE, "booking is not BOOKED")
        # parent session must be IN_PROGRESS.
        if session is None or session["status"] != "IN_PROGRESS":
            raise err(ERR_INVALID_STATE, "session is not IN_PROGRESS")
        # storm closure (priority 8).
        school = db.schools.get(session["school_id"])
        if school is not None and derive.school_operating_status(school) == "STORM_CLOSED":
            raise err(ERR_SCHOOL_STORM_CLOSED, "school is storm-closed")
        # waiver (priority 9): student waiver_status must be SIGNED.
        student_id = _booking_student_id(rec)
        if student_id is None or derive.student_waiver_status(student_id) != "SIGNED":
            raise err(ERR_WAIVER_REQUIRED, "student waiver not SIGNED")
        rec["status"] = "CHECKED_IN"
        touch(rec)
        return success(derive.serialize_booking(rec), 200)


@bp.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.bookings.get(bid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "booking not found")
        # Ownership scoping for Student (priority 5).
        if role == "Student":
            student_id = _booking_student_id(rec)
            if student_id != user_id:
                raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")
        if rec["status"] not in ("BOOKED", "CHECKED_IN"):
            raise err(ERR_INVALID_STATE, "booking not in BOOKED or CHECKED_IN")
        rec["status"] = "CANCELLED"
        touch(rec)
        # Session.enrolled_count decremented; required_instructors recomputed;
        # Session.version +1 (PRD §3.7).
        session = db.sessions.get(rec["session_id"])
        if session is not None:
            touch(session)
        return success(derive.serialize_booking(rec), 200)
