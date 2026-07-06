"""Enrollment routes: create (gated), pay, withdraw, refund, complete.

Two independent dimensions on one row (PRD §3.5):
  progress_status: ACTIVE -> COMPLETED | WITHDRAWN
  payment_status:  UNPAID -> PAID -> REFUNDED
"""
from flask import Blueprint, request

import db
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_WAIVER_REQUIRED, ERR_AGE_REQUIREMENT_NOT_MET, ERR_SWIM_TEST_REQUIRED,
    ERR_PREREQUISITE_NOT_MET, ERR_PAYMENT_REQUIRED, ERR_ATTENDANCE_INCOMPLETE,
)
from middleware import get_identity, require_role
from response import success, success_list
from services import derive, calc
from util import (
    require_str, require_int, parse_pagination, paginate, touch,
)

bp = Blueprint("enrollments", __name__)
READ_ROLES = {"SchoolAdmin", "Instructor", "Student"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def _student_owns_enrollment(role, user_id, enrollment):
    if role == "Student" and user_id != enrollment["student_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    body = _body()
    school_id = require_str(body, "school_id")
    student_id = require_str(body, "student_id")
    course_level_id = require_str(body, "course_level_id")
    membership_id = body.get("membership_id")
    if membership_id is not None and not isinstance(membership_id, str):
        raise err(ERR_VALIDATION, "membership_id must be a string or null")
    planned_sessions = require_int(body, "planned_sessions", minimum=1)
    party_size = require_int(body, "party_size", minimum=1)

    with db.lock():
        # Existence of body FKs within the same school (priority 4).
        if school_id not in db.schools:
            raise err(ERR_NOT_FOUND, "school not found")
        student = db.students.get(student_id)
        if student is None or student["school_id"] != school_id:
            raise err(ERR_NOT_FOUND, "student not found")
        level = db.levels.get(course_level_id)
        if level is None or level["school_id"] != school_id:
            raise err(ERR_NOT_FOUND, "course level not found")
        membership = None
        if membership_id is not None:
            membership = db.memberships.get(membership_id)
            if membership is None or membership["student_id"] != student_id:
                raise err(ERR_NOT_FOUND, "membership not found")

        # Ownership scoping for Student role (priority 5).
        if role == "Student" and user_id != student_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")

        # --- Business safety gates in PRD §3.4 order ---
        # storm closure does NOT block enrolling (PRD §3.4); skip.
        # 1. waiver
        if derive.student_waiver_status(student_id) != "SIGNED":
            raise err(ERR_WAIVER_REQUIRED, "student waiver not SIGNED")
        # 2. age
        if derive.student_age_years(student) < level["min_age"]:
            raise err(ERR_AGE_REQUIREMENT_NOT_MET, "student below minimum age")
        # 3. swim test
        if level["requires_swim_test"] and student["swim_test_status"] != "PASSED":
            raise err(ERR_SWIM_TEST_REQUIRED, "swim test not passed")
        # 4. prerequisite (rank>1 needs COMPLETED enrollment at rank-1 same course)
        if level["rank"] > 1:
            rank1 = None
            for l in db.levels.values():
                if l["course_id"] == level["course_id"] and l["rank"] == 1:
                    rank1 = l
                    break
            ok = False
            if rank1 is not None:
                for e in db.enrollments.values():
                    if (e["student_id"] == student_id
                            and e["course_level_id"] == rank1["id"]
                            and e["progress_status"] == "COMPLETED"):
                        ok = True
                        break
            if not ok:
                raise err(ERR_PREREQUISITE_NOT_MET, "rank-1 prerequisite not completed")

        # Membership tier only applies while ACTIVE (PRD §3.8).
        tier = membership["tier"] if (membership and membership["status"] == "ACTIVE") else None
        estimated = calc.enrollment_estimate_price(
            planned_sessions, level["base_price_cents"], party_size, tier
        )
        now = db.now_iso()
        eid = db.new_id()
        rec = {
            "id": eid, "school_id": school_id, "student_id": student_id,
            "course_level_id": course_level_id, "membership_id": membership_id,
            "planned_sessions": planned_sessions, "party_size": party_size,
            "progress_status": "ACTIVE", "payment_status": "UNPAID",
            "estimated_price_cents": estimated,
            "final_price_cents": None, "refund_cents": None,
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.enrollments[eid] = rec
        return success(derive.serialize_enrollment(rec), 201)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    student_id = request.args.get("student_id")
    course_level_id = request.args.get("course_level_id")
    membership_id = request.args.get("membership_id")
    rows = [
        e for e in db.enrollments.values()
        if (school_id is None or e["school_id"] == school_id)
        and (student_id is None or e["student_id"] == student_id)
        and (course_level_id is None or e["course_level_id"] == course_level_id)
        and (membership_id is None or e["membership_id"] == membership_id)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_enrollment(r) for r in page], limit, offset, total)


@bp.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.enrollments.get(eid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "enrollment not found")
    _student_owns_enrollment(role, user_id, rec)
    return success(derive.serialize_enrollment(rec), 200)


@bp.route("/enrollments/<eid>/pay", methods=["POST"])
def pay_enrollment(eid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.enrollments.get(eid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "enrollment not found")
        _student_owns_enrollment(role, user_id, rec)
        # Requires UNPAID and progress != WITHDRAWN (PRD §3.5).
        if rec["payment_status"] != "UNPAID":
            raise err(ERR_INVALID_STATE, "enrollment is not UNPAID")
        if rec["progress_status"] == "WITHDRAWN":
            raise err(ERR_INVALID_STATE, "withdrawn enrollment cannot be paid")
        rec["payment_status"] = "PAID"
        touch(rec)
        return success(derive.serialize_enrollment(rec), 200)


@bp.route("/enrollments/<eid>/withdraw", methods=["POST"])
def withdraw_enrollment(eid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.enrollments.get(eid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "enrollment not found")
        _student_owns_enrollment(role, user_id, rec)
        if rec["progress_status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "enrollment is not ACTIVE")
        rec["progress_status"] = "WITHDRAWN"
        touch(rec)
        # CASCADE: BOOKED/CHECKED_IN bookings -> CANCELLED (student-caused, NO makeup).
        for b in db.bookings.values():
            if b["enrollment_id"] == eid and b["status"] in ("BOOKED", "CHECKED_IN"):
                b["status"] = "CANCELLED"
                # Mark so the refund waterfall can still see this enrollment's
                # future sessions: withdraw is a precondition of refund and cancels
                # exactly the bookings the refund lead-time tier reads (PRD §3.8 +
                # corner refund_half_tier_at_thirty_six_hours).
                b["cancelled_by_withdraw"] = True
                touch(b)
                # decrement session enrolled_count -> recompute required_instructors -> bump version
                sess = db.sessions.get(b["session_id"])
                if sess is not None:
                    touch(sess)
        return success(derive.serialize_enrollment(rec), 200)


@bp.route("/enrollments/<eid>/refund", methods=["POST"])
def refund_enrollment(eid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.enrollments.get(eid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "enrollment not found")
        # Requires PAID and progress == WITHDRAWN (PRD §3.5).
        if rec["payment_status"] != "PAID":
            raise err(ERR_INVALID_STATE, "enrollment is not PAID")
        if rec["progress_status"] != "WITHDRAWN":
            raise err(ERR_INVALID_STATE, "enrollment is not WITHDRAWN")
        # Lead-time waterfall over earliest remaining future booking (PRD §3.8).
        # The withdraw cascade (a precondition of refund) cancels this enrollment's
        # BOOKED/CHECKED_IN bookings; those withdraw-cancelled bookings are exactly
        # the "remaining" set the lead-time tier reads, so include them here.
        from util import parse_dt
        now = clock.get()
        remaining = []
        for b in db.bookings.values():
            if b["enrollment_id"] != eid:
                continue
            is_remaining = b["status"] in ("BOOKED", "CHECKED_IN") or \
                b.get("cancelled_by_withdraw")
            if not is_remaining:
                continue
            sess = db.sessions.get(b["session_id"])
            if sess is None:
                continue
            starts = parse_dt(sess["starts_at"], "starts_at")
            if starts > now:
                remaining.append((starts, sess["created_at"], sess["_seq"]))
        if not remaining:
            lead = None
        else:
            remaining.sort(key=lambda t: (t[0], t[1], t[2]))
            lead = calc.lead_time_hours(remaining[0][0], now)
        rec["refund_cents"] = calc.refund_cents(rec["estimated_price_cents"], lead)
        rec["payment_status"] = "REFUNDED"
        touch(rec)
        return success(derive.serialize_enrollment(rec), 200)


@bp.route("/enrollments/<eid>/complete", methods=["POST"])
def complete_enrollment(eid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.enrollments.get(eid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "enrollment not found")
        # State legality first: progress must be ACTIVE (PRD §3.5).
        if rec["progress_status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "enrollment is not ACTIVE")
        # Payment gate before attendance gate (PRD §3.5).
        if rec["payment_status"] != "PAID":
            raise err(ERR_PAYMENT_REQUIRED, "enrollment not PAID")
        attended = derive.enrollment_attended_count(eid)
        if attended < rec["planned_sessions"]:
            raise err(ERR_ATTENDANCE_INCOMPLETE, "attendance incomplete")

        # Chronological final price over ATTENDED bookings (PRD §3.8).
        level = db.levels.get(rec["course_level_id"])
        from util import parse_dt
        attended_bookings = [
            b for b in db.bookings.values()
            if b["enrollment_id"] == eid and b["status"] == "ATTENDED"
        ]
        # Build per-session ATTENDED counts; order by session starts_at, created_at.
        def sort_key(b):
            sess = db.sessions.get(b["session_id"])
            return (parse_dt(sess["starts_at"], "starts_at"), sess["created_at"], sess["_seq"])
        attended_bookings.sort(key=sort_key)
        lines = []
        for b in attended_bookings:
            sess_id = b["session_id"]
            per_session = sum(
                1 for x in db.bookings.values()
                if x["session_id"] == sess_id and x["status"] == "ATTENDED"
            )
            lines.append(per_session)
        membership = db.memberships.get(rec["membership_id"]) if rec["membership_id"] else None
        tier = membership["tier"] if (membership and membership["status"] == "ACTIVE") else None
        rec["final_price_cents"] = calc.enrollment_final_price(
            lines, level["base_price_cents"], tier
        )
        rec["progress_status"] = "COMPLETED"
        touch(rec)

        # CASCADE: issue CertificationCard if parent Course.kind == CERTIFICATION
        # and no card yet exists for this enrollment (PRD §3.9).
        course = db.courses.get(level["course_id"]) if level else None
        if course is not None and course["kind"] == "CERTIFICATION":
            already = any(c["enrollment_id"] == eid for c in db.certification_cards.values())
            if not already:
                serial = db.next_card_serial(rec["school_id"])
                now_iso = db.now_iso()
                issued = clock.get().strftime("%Y-%m-%dT%H:%M:%S.") + \
                    f"{clock.get().microsecond // 1000:03d}Z"
                cid = db.new_id()
                card = {
                    "id": cid, "student_id": rec["student_id"], "enrollment_id": eid,
                    "course_level_id": rec["course_level_id"],
                    "discipline": course["discipline"],
                    "card_number": f"CARD-{serial}",
                    "issued_at": issued, "created_at": now_iso,
                    "_seq": db.next_seq(),
                }
                db.certification_cards[cid] = card
        return success(derive.serialize_enrollment(rec), 200)
