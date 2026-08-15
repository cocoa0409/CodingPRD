"""Refund request endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination, check_student_scope
from response import success_object, success_list

bp = Blueprint("refund_requests", __name__)


def _refund_to_json(r):
    return {k: v for k, v in r.items()}


def _get_refund(refund_id):
    r = db.refund_requests.get(refund_id)
    if not r:
        errors.raise_error(errors.ERR_REFUND_REQUEST_NOT_FOUND,
                           f"RefundRequest {refund_id} not found")
    return r


def _check_refund_scope(refund, auth):
    """Check director or student scope on a refund request."""
    enrollment = db.enrollments.get(refund["enrollment_id"])
    if not enrollment:
        return

    if auth["role"] == "Student":
        if enrollment["student_id"] != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own refund request")

    if auth["role"] == "SchoolDirector":
        offering = db.offerings.get(enrollment["offering_id"])
        if offering:
            course = db.courses.get(offering["course_id"])
            if course:
                school = db.schools.get(course["school_id"])
                if school and school.get("director_user_id") != auth["user_id"]:
                    errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")


@bp.route("/refund-requests", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def list_refund_requests():
    limit, offset = parse_pagination()
    items = list(db.refund_requests.values())

    auth = request.auth

    # Student scope
    if auth["role"] == "Student":
        own_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["student_id"] == auth["user_id"]}
        items = [r for r in items if r["enrollment_id"] in own_enrollment_ids]

    # Filters
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        items = [r for r in items if r["enrollment_id"] == enrollment_id]

    status_filter = request.args.get("status")
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]

    # Director scope
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        own_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] in own_school_ids}
        own_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in own_course_ids}
        own_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["offering_id"] in own_offering_ids}
        items = [r for r in items if r["enrollment_id"] in own_enrollment_ids]

    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_refund_to_json(r) for r in page], limit, offset, total)


@bp.route("/refund-requests/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def get_refund_request(id):
    refund = _get_refund(id)
    auth = request.auth
    _check_refund_scope(refund, auth)
    return success_object(_refund_to_json(refund))


@bp.route("/refund-requests/<id>/approve", methods=["POST"])
@require_roles("SchoolDirector")
def approve_refund(id):
    refund = _get_refund(id)
    auth = request.auth
    _check_refund_scope(refund, auth)

    if refund["status"] != "PENDING":
        errors.raise_error(errors.ERR_REFUND_STATE_INVALID,
                           f"Refund status is {refund['status']}, expected PENDING")

    refund["status"] = "APPROVED"
    refund["decided_at"] = db.now_iso()
    db.touch(refund)
    db.audit("RefundRequest", refund["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "PENDING", "to_status": "APPROVED"})
    return success_object(_refund_to_json(refund))


@bp.route("/refund-requests/<id>/deny", methods=["POST"])
@require_roles("SchoolDirector")
def deny_refund(id):
    refund = _get_refund(id)
    auth = request.auth
    _check_refund_scope(refund, auth)

    body = get_json_body(required_fields=["denial_reason"])

    if refund["status"] != "PENDING":
        errors.raise_error(errors.ERR_REFUND_STATE_INVALID,
                           f"Refund status is {refund['status']}, expected PENDING")

    refund["status"] = "DENIED"
    refund["denial_reason"] = body["denial_reason"]
    refund["decided_at"] = db.now_iso()
    db.touch(refund)
    db.audit("RefundRequest", refund["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "PENDING", "to_status": "DENIED"})
    return success_object(_refund_to_json(refund))


@bp.route("/refund-requests/<id>/pay", methods=["POST"])
@require_roles("Registrar")
def pay_refund(id):
    refund = _get_refund(id)
    auth = request.auth

    if refund["status"] != "APPROVED":
        errors.raise_error(errors.ERR_REFUND_STATE_INVALID,
                           f"Refund status is {refund['status']}, expected APPROVED")

    refund["status"] = "PAID"
    refund["paid_at"] = db.now_iso()
    db.touch(refund)
    db.audit("RefundRequest", refund["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "APPROVED", "to_status": "PAID"})

    # Update enrollment
    enrollment = db.enrollments.get(refund["enrollment_id"])
    if enrollment:
        enrollment["retained_cents"] = enrollment["paid_cents"] - refund["granted_refund_cents"]
        if refund["granted_refund_cents"] == enrollment["paid_cents"]:
            enrollment["payment_status"] = "REFUNDED"
        else:
            enrollment["payment_status"] = "PARTIALLY_REFUNDED"
        db.touch(enrollment)
        db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
                 auth["role"], auth["user_id"],
                 {"note": f"payment_status -> {enrollment['payment_status']}"})

    return success_object(_refund_to_json(refund))
