"""Enrollment endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import (
    require_roles, get_json_body, parse_pagination,
    check_student_scope, check_director_scope,
)
from response import success_object, success_list
from services.calculations import (
    compute_order_total_cents, compute_enrolled_count, update_offering_counts,
    _extract_date,
)
from services.cascade import withdraw_enrollment
from datetime import timedelta

bp = Blueprint("enrollments", __name__)


def _enrollment_to_json(e):
    return {k: v for k, v in e.items()}


def _get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if not e:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND,
                           f"Enrollment {enrollment_id} not found")
    return e


def _check_student_schedule_conflict(student_id, new_offering, exclude_enrollment_id=None):
    """Student must not hold another active enrollment with overlapping window (half-open)."""
    new_start = _extract_date(new_offering["start_date"])
    new_end = _extract_date(new_offering["end_date"])
    if new_start is None or new_end is None:
        return

    for e in db.enrollments.values():
        if e["student_id"] != student_id:
            continue
        if e["academic_status"] in ("WITHDRAWN", "FAILED", "EXPIRED"):
            continue
        if exclude_enrollment_id and e["id"] == exclude_enrollment_id:
            continue
        existing_offering = db.offerings.get(e["offering_id"])
        if not existing_offering:
            continue
        existing_start = _extract_date(existing_offering["start_date"])
        existing_end = _extract_date(existing_offering["end_date"])
        if existing_start is None or existing_end is None:
            continue
        # Half-open overlap: conflict if NOT (new.start >= existing.end OR new.end <= existing.start)
        if new_start >= existing_end or new_end <= existing_start:
            continue  # Adjacency allowed
        errors.raise_error(errors.ERR_STUDENT_SCHEDULE_CONFLICT,
                           "Student has a conflicting enrollment")


@bp.route("/enrollments", methods=["POST"])
@require_roles("Registrar", "Student")
def create_enrollment():
    body = get_json_body(
        required_fields=["offering_id"],
        optional_fields=["student_id", "scholarship_cents"],
    )
    auth = request.auth

    # Determine student_id
    if auth["role"] == "Student":
        student_id = body.get("student_id", auth["user_id"])
        if student_id != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE,
                               "Student may only enroll self")
    else:
        student_id = body.get("student_id")
        if not student_id:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "student_id required for Registrar")

    # Existence
    student = db.students.get(student_id)
    if not student:
        errors.raise_error(errors.ERR_STUDENT_NOT_FOUND, f"Student {student_id} not found")

    offering = db.offerings.get(body["offering_id"])
    if not offering:
        errors.raise_error(errors.ERR_OFFERING_NOT_FOUND,
                           f"Offering {body['offering_id']} not found")

    course = db.courses.get(offering["course_id"])
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, f"Course not found")

    # Shape: scholarship
    scholarship = body.get("scholarship_cents", 0)
    if not isinstance(scholarship, int) or isinstance(scholarship, bool) or scholarship < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "scholarship_cents must be >= 0")

    # State: offering must be PUBLISHED
    if offering["status"] != "PUBLISHED":
        errors.raise_error(errors.ERR_OFFERING_NOT_OPEN,
                           f"Offering status is {offering['status']}, expected PUBLISHED")

    # Capacity
    if offering["seats_available"] < 1:
        errors.raise_error(errors.ERR_OFFERING_FULL, "Offering is full")

    # Student schedule conflict
    _check_student_schedule_conflict(student_id, offering)

    # Compute charge
    charge_total = compute_order_total_cents(course["tuition_cents"], scholarship)

    # Compute deadline
    end_d = _extract_date(offering["end_date"])
    deadline = end_d + timedelta(days=course["completion_deadline_days"])

    enrollment = db.new_entity({
        "student_id": student_id,
        "offering_id": body["offering_id"],
        "academic_status": "ENROLLED",
        "payment_status": "PENDING",
        "scholarship_cents": scholarship,
        "charge_total_cents": charge_total,
        "paid_cents": 0,
        "retained_cents": 0,
        "verified_seat_minutes": 0,
        "creditable_seat_minutes": 0,
        "completion_fraction_bps": 0,
        "exam_attempts_used": 0,
        "deadline_date": deadline.isoformat(),
        "enrolled_at": db.now_iso(),
        "withdrawn_at": None,
        "withdrawal_reason": None,
    })
    db.enrollments[enrollment["id"]] = enrollment

    # Recompute offering counts
    update_offering_counts(offering)
    db.touch(offering)

    db.audit("Enrollment", enrollment["id"], "ENROLLMENT_CREATED",
             auth["role"], auth["user_id"])
    return success_object(_enrollment_to_json(enrollment), 201)


@bp.route("/enrollments", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def list_enrollments():
    limit, offset = parse_pagination()
    items = list(db.enrollments.values())

    auth = request.auth

    # Student: only own
    if auth["role"] == "Student":
        items = [e for e in items if e["student_id"] == auth["user_id"]]

    # Filters
    student_id = request.args.get("student_id")
    if student_id:
        if auth["role"] == "Student" and student_id != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Student can only list own enrollments")
        items = [e for e in items if e["student_id"] == student_id]

    offering_id = request.args.get("offering_id")
    if offering_id:
        items = [e for e in items if e["offering_id"] == offering_id]

    academic_status = request.args.get("academic_status")
    if academic_status:
        items = [e for e in items if e["academic_status"] == academic_status]

    payment_status = request.args.get("payment_status")
    if payment_status:
        items = [e for e in items if e["payment_status"] == payment_status]

    # Director scope
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        own_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] in own_school_ids}
        own_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in own_course_ids}
        items = [e for e in items if e["offering_id"] in own_offering_ids]

    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_enrollment_to_json(e) for e in page], limit, offset, total)


@bp.route("/enrollments/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def get_enrollment(id):
    enrollment = _get_enrollment(id)
    auth = request.auth
    check_student_scope(enrollment["student_id"], auth)
    if auth["role"] == "SchoolDirector":
        offering = db.offerings.get(enrollment["offering_id"])
        if offering:
            course = db.courses.get(offering["course_id"])
            if course:
                school = db.schools.get(course["school_id"])
                if school:
                    check_director_scope(school, auth)
    return success_object(_enrollment_to_json(enrollment))


@bp.route("/enrollments/<id>/withdraw", methods=["POST"])
@require_roles("Registrar", "Student")
def withdraw_enrollment_endpoint(id):
    enrollment = _get_enrollment(id)
    auth = request.auth

    # Scope: student can only withdraw own
    check_student_scope(enrollment["student_id"], auth)

    body = get_json_body(
        required_fields=["reason"],
        optional_fields=["effective_date"],
    )

    reason = body["reason"]
    if reason not in ("VOLUNTARY", "ADMINISTRATIVE"):
        errors.raise_error(errors.ERR_WITHDRAWAL_REASON_INVALID,
                           f"Invalid withdrawal reason: {reason}")

    # State: must be ENROLLED, IN_PROGRESS, or SEAT_TIME_MET
    if enrollment["academic_status"] not in ("ENROLLED", "IN_PROGRESS", "SEAT_TIME_MET"):
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Cannot withdraw from state {enrollment['academic_status']}")

    effective_date = body.get("effective_date")

    withdraw_enrollment(enrollment, reason, effective_date, auth["role"], auth["user_id"])
    return success_object(_enrollment_to_json(enrollment))


@bp.route("/enrollments/<id>/pay", methods=["POST"])
@require_roles("Registrar", "Student")
def pay_enrollment(id):
    enrollment = _get_enrollment(id)
    auth = request.auth

    # Scope
    check_student_scope(enrollment["student_id"], auth)

    body = get_json_body(required_fields=["amount_cents"])

    # State: payment_status must be PENDING
    if enrollment["payment_status"] != "PENDING":
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Payment status is {enrollment['payment_status']}, expected PENDING")

    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "amount_cents must be an integer")

    if amount != enrollment["charge_total_cents"]:
        errors.raise_error(errors.ERR_PAYMENT_AMOUNT_MISMATCH,
                           f"Expected {enrollment['charge_total_cents']}, got {amount}")

    enrollment["payment_status"] = "PAID"
    enrollment["paid_cents"] = amount
    db.touch(enrollment)
    db.audit("Enrollment", enrollment["id"], "PAYMENT_CAPTURED",
             auth["role"], auth["user_id"],
             {"note": f"paid_cents={amount}"})
    return success_object(_enrollment_to_json(enrollment))
