"""Enrollment endpoints: creation/seat allocation, activation, cancellation,
attendance, analytics, materials, and sub-resource lists (PRD §3.3–§3.5, §3.8).
"""
from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_auth, get_json_body, parse_pagination, parse_iso8601
from services import serialize, validators, core
from services.calculations import (
    enrollment_net_price,
    first_installment_amount,
    scaled_score,
    percentile,
)
from services.listing import sort_and_page

bp = Blueprint("enrollments", __name__)


def _get_enrollment_or_404(eid):
    e = db.enrollments.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Enrollment not found.")
    return e


def _authorize_owner(user_id, role, enrollment):
    # A Student may act only on enrollments it owns (PRD §2.1).
    if role == "Student" and enrollment["student_id"] != user_id:
        raise err("ERR_UNAUTHORIZED", "Student does not own this enrollment.")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@bp.post("/enrollments")
def create_enrollment():
    user_id, role = require_auth({"Student", "Registrar"})
    body = get_json_body()

    # Existence resolution (priority 3): body FKs in declaration order.
    student_id = validators.require_str(body, "student_id")
    cohort_id = validators.require_str(body, "cohort_id")
    student = db.students.get(student_id)
    if student is None:
        raise err("ERR_NOT_FOUND", "Student not found.")
    cohort = db.cohorts.get(cohort_id)
    if cohort is None:
        raise err("ERR_NOT_FOUND", "Cohort not found.")

    # Ownership: a Student may only create enrollments for itself.
    if role == "Student" and student_id != user_id:
        raise err("ERR_UNAUTHORIZED", "Student may only enroll itself.")

    # Request well-formedness (priority 4).
    expected_version = validators.require_int(body, "expected_cohort_version")
    coupon_code = body.get("coupon_code")

    # Coupon validity (priority 5) — only when supplied.
    if coupon_code is not None and coupon_code not in validators.COUPONS:
        raise err("ERR_INVALID_COUPON", "coupon_code must be EARLYBIRD or REFER50.")

    course = db.courses[cohort["course_id"]]

    # Duplicate enrollment (priority 16): non-terminal enrollment in this cohort.
    for e in db.enrollments.values():
        if (
            e["student_id"] == student_id
            and e["cohort_id"] == cohort_id
            and e["status"] in ("PENDING_PAYMENT", "WAITLISTED", "ACTIVE", "COMPLETED")
        ):
            raise err("ERR_DUPLICATE_ENROLLMENT", "Student already enrolled in this cohort.")

    # Student schedule conflict (priority 17): closed-interval, buffer-inclusive,
    # against other cohorts where the student holds a non-terminal
    # {PENDING_PAYMENT, WAITLISTED, ACTIVE} enrollment.
    a_start = parse_iso8601(cohort["starts_at"])
    a_end = parse_iso8601(cohort["ends_at"])
    for e in db.enrollments.values():
        if e["student_id"] != student_id:
            continue
        if e["status"] not in ("PENDING_PAYMENT", "WAITLISTED", "ACTIVE"):
            continue
        other = db.cohorts.get(e["cohort_id"])
        if other is None or other["id"] == cohort_id:
            continue
        b_start = parse_iso8601(other["starts_at"])
        b_end = parse_iso8601(other["ends_at"])
        # Closed-interval overlap: touching boundaries count as conflict.
        if a_start <= b_end and b_start <= a_end:
            raise err(
                "ERR_STUDENT_SCHEDULE_CONFLICT",
                "Student has a schedule-conflicting enrollment.",
            )

    # OCC version match (ERR_STALE_VERSION) — checked among the business rules.
    if expected_version != cohort["version"]:
        raise err("ERR_STALE_VERSION", "expected_cohort_version does not match.")

    # Pricing (calc enrollment_net_price).
    price_paid = enrollment_net_price(course["list_price_cents"], coupon_code)

    # Seat-vs-waitlist branch (PRD §3.4): full iff seats_committed + holds >= cap.
    holds = core.held_seat_count(cohort)
    is_full = (cohort["seats_committed"] + holds) >= cohort["seat_capacity"]

    rec = {
        "id": db.new_id(),
        "student_id": student_id,
        "cohort_id": cohort_id,
        "status": "PENDING_PAYMENT",
        "price_paid_cents": price_paid,
        "completed_practice_count": 0,
        "sessions_attended": 0,
        "best_practice_score": None,
        "guarantee_status": "PENDING",
        "materials_expire_at": None,
        "waitlist_seq": None,
    }

    if is_full:
        rec["status"] = "WAITLISTED"
        existing = [
            e["waitlist_seq"]
            for e in db.enrollments.values()
            if e["cohort_id"] == cohort_id and e["status"] == "WAITLISTED"
            and e["waitlist_seq"] is not None
        ]
        rec["waitlist_seq"] = (max(existing) if existing else 0) + 1

    db.stamp_create(rec)
    db.enrollments[rec["id"]] = rec

    # Successful creation advances the cohort version by one (PRD §2.6).
    db.touch(cohort)
    return response.success(serialize.enrollment(rec), 201)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
@bp.get("/enrollments/<eid>")
def get_enrollment(eid):
    user_id, role = require_auth({"Student", "Instructor", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)
    return response.success(serialize.enrollment(e), 200)


# ---------------------------------------------------------------------------
# Activate
# ---------------------------------------------------------------------------
@bp.post("/enrollments/<eid>/activate")
def activate_enrollment(eid):
    require_auth({"Registrar"})
    e = _get_enrollment_or_404(eid)

    if e["status"] != "PENDING_PAYMENT":
        raise err("ERR_INVALID_STATE", "Enrollment is not PENDING_PAYMENT.")

    cohort = db.cohorts[e["cohort_id"]]
    course = db.courses[cohort["course_id"]]

    # Payment settled (priority 14): a plan exists whose amount_paid_cents >=
    # the first installment amount.
    plans = [p for p in db.installment_plans.values() if p["enrollment_id"] == eid]
    settled = False
    for p in plans:
        first_amt = first_installment_amount(p["total_financed_cents"], p["num_installments"])
        if p["amount_paid_cents"] >= first_amt:
            settled = True
            break
    if not settled:
        raise err("ERR_PAYMENT_NOT_SETTLED", "First installment not settled.")

    # Cohort enrollable (must be SCHEDULED or IN_SESSION).
    if cohort["status"] not in ("SCHEDULED", "IN_SESSION"):
        raise err("ERR_COHORT_NOT_ENROLLABLE", "Cohort is not enrollable.")

    # Free committed seat (priority 15).
    if cohort["seats_committed"] >= cohort["seat_capacity"]:
        raise err("ERR_COHORT_FULL", "Cohort has no free committed seat.")

    e["status"] = "ACTIVE"
    core.set_materials_expiry(e, course)
    db.touch(e)
    core.recompute_seats_committed(cohort)
    return response.success(serialize.enrollment(e), 200)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------
@bp.post("/enrollments/<eid>/cancel")
def cancel_enrollment_endpoint(eid):
    user_id, role = require_auth({"Student", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)
    body = get_json_body()
    expected_version = validators.require_int(body, "expected_cohort_version")

    if e["status"] not in ("ACTIVE", "WAITLISTED", "PENDING_PAYMENT"):
        raise err("ERR_INVALID_STATE", "Enrollment is not in a cancellable state.")

    cohort = db.cohorts[e["cohort_id"]]
    if expected_version != cohort["version"]:
        raise err("ERR_STALE_VERSION", "expected_cohort_version does not match.")

    core.cancel_enrollment(e)
    # Every successful cancellation advances the cohort version by one (PRD §3.4).
    db.touch(cohort)
    return response.success(serialize.enrollment(e), 200)


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
@bp.post("/enrollments/<eid>/attendance")
def record_attendance(eid):
    require_auth({"Instructor", "Registrar"})
    e = _get_enrollment_or_404(eid)
    body = get_json_body()
    sessions_attended = validators.require_int(body, "sessions_attended", minimum=0)
    e["sessions_attended"] = sessions_attended
    db.touch(e)
    return response.success(serialize.enrollment(e), 200)


# ---------------------------------------------------------------------------
# Analytics (provisional, advisory projection)
# ---------------------------------------------------------------------------
@bp.get("/enrollments/<eid>/analytics")
def enrollment_analytics(eid):
    user_id, role = require_auth({"Student", "Instructor", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)

    cohort = db.cohorts[e["cohort_id"]]
    course = db.courses[cohort["course_id"]]
    student = db.students[e["student_id"]]

    # Latest COMPLETED PRACTICE attempt's scaled_score (most recent, not best).
    completed_practice = [
        a
        for a in db.practice_attempts.values()
        if a["enrollment_id"] == eid
        and a["attempt_type"] == "PRACTICE"
        and a["status"] == "COMPLETED"
    ]
    latest = max(completed_practice, key=lambda a: a["_seq"]) if completed_practice else None
    latest_practice_score = latest["scaled_score"] if latest else None

    # Provisional projected improvement uses the LATEST (advisory) vs diagnostic.
    if student["diagnostic_score"] is not None and latest_practice_score is not None:
        projected_improvement = latest_practice_score - student["diagnostic_score"]
    else:
        projected_improvement = None

    # Attendance pct (SELF: not gated, but report the raw fraction).
    if cohort["total_sessions"] > 0:
        attendance_pct = e["sessions_attended"] / cohort["total_sessions"]
    else:
        attendance_pct = None

    latest_percentile = (
        percentile(latest_practice_score, course["baseline_scale_max"])
        if latest_practice_score is not None
        else None
    )

    data = serialize.enrollment(e)
    data["analytics"] = {
        "diagnostic_score": student["diagnostic_score"],
        "best_practice_score": e["best_practice_score"],
        "latest_practice_score": latest_practice_score,
        "projected_improvement": projected_improvement,
        "completed_practice_count": e["completed_practice_count"],
        "attendance_pct": attendance_pct,
        "latest_percentile": latest_percentile,
    }
    return response.success(data, 200)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
@bp.get("/enrollments/<eid>/materials")
def get_materials(eid):
    user_id, role = require_auth({"Student", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)

    expire = e["materials_expire_at"]
    # Access denied at/after materials_expire_at (PRD §3.8). If never activated
    # (expire is null), there is no granted access window -> expired/denied.
    if expire is None:
        raise err("ERR_MATERIALS_EXPIRED", "Materials are not accessible.")
    if db.now_clock() >= parse_iso8601(expire):
        raise err("ERR_MATERIALS_EXPIRED", "Materials access window has passed.")
    return response.success(serialize.enrollment(e), 200)


# ---------------------------------------------------------------------------
# Sub-resource lists
# ---------------------------------------------------------------------------
@bp.get("/enrollments/<eid>/practice-attempts")
def list_practice_attempts(eid):
    user_id, role = require_auth({"Student", "Instructor", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)
    limit, offset = parse_pagination()
    attempt_type = request.args.get("attempt_type")
    status = request.args.get("status")
    records = [a for a in db.practice_attempts.values() if a["enrollment_id"] == eid]
    if attempt_type is not None:
        records = [a for a in records if a["attempt_type"] == attempt_type]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.practice_attempt(a) for a in page], limit, offset, total
    )


@bp.get("/enrollments/<eid>/installment-plans")
def list_installment_plans(eid):
    user_id, role = require_auth({"Student", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [p for p in db.installment_plans.values() if p["enrollment_id"] == eid]
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.installment_plan(p) for p in page], limit, offset, total
    )


@bp.get("/enrollments/<eid>/guarantee-claims")
def list_guarantee_claims(eid):
    user_id, role = require_auth({"Student", "Registrar"})
    e = _get_enrollment_or_404(eid)
    _authorize_owner(user_id, role, e)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [g for g in db.guarantee_claims.values() if g["enrollment_id"] == eid]
    if status is not None:
        records = [g for g in records if g["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.guarantee_claim(g) for g in page], limit, offset, total
    )
