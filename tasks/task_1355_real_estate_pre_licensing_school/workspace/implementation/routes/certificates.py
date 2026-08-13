"""Certificate endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination, check_student_scope
from response import success_object, success_list
from services.calculations import assign_certificate_number
from services.cascade import revoke_certificate_cascade

bp = Blueprint("certificates", __name__)


def _cert_to_json(c):
    return {k: v for k, v in c.items()}


@bp.route("/enrollments/<enrollment_id>/certificate", methods=["POST"])
@require_roles("Registrar")
def issue_certificate(enrollment_id):
    enrollment = db.enrollments.get(enrollment_id)
    if not enrollment:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND,
                           f"Enrollment {enrollment_id} not found")
    auth = request.auth

    # State: must be EXAM_PASSED
    if enrollment["academic_status"] != "EXAM_PASSED":
        errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                           f"Enrollment status is {enrollment['academic_status']}, expected EXAM_PASSED")

    # Check no existing certificate
    for c in db.certificates.values():
        if c["enrollment_id"] == enrollment_id:
            errors.raise_error(errors.ERR_ENROLLMENT_STATE_INVALID,
                               "Certificate already exists for this enrollment")

    # Get school for certificate number
    offering = db.offerings.get(enrollment["offering_id"])
    if not offering:
        errors.raise_error(errors.ERR_OFFERING_NOT_FOUND, "Offering not found")
    course = db.courses.get(offering["course_id"])
    if not course:
        errors.raise_error(errors.ERR_COURSE_NOT_FOUND, "Course not found")
    school = db.schools.get(course["school_id"])
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, "School not found")

    cert_number = assign_certificate_number(school)

    cert = db.new_entity({
        "enrollment_id": enrollment_id,
        "certificate_number": cert_number,
        "credit_hours_pinned": course["ce_credit_hours"],
        "issue_date": db.today().isoformat(),
        "status": "ACTIVE",
        "revoked_reason": None,
        "revoked_at": None,
    })
    db.certificates[cert["id"]] = cert
    db.audit("Certificate", cert["id"], "CERTIFICATE_ISSUED",
             auth["role"], auth["user_id"])

    # Enrollment -> COMPLETED
    old_status = enrollment["academic_status"]
    enrollment["academic_status"] = "COMPLETED"
    db.touch(enrollment)
    db.audit("Enrollment", enrollment["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": old_status, "to_status": "COMPLETED"})

    return success_object(_cert_to_json(cert), 201)


@bp.route("/certificates", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def list_certificates():
    limit, offset = parse_pagination()
    items = list(db.certificates.values())

    auth = request.auth

    # Student scope
    if auth["role"] == "Student":
        own_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["student_id"] == auth["user_id"]}
        items = [c for c in items if c["enrollment_id"] in own_enrollment_ids]

    # Filters
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]

    student_id = request.args.get("student_id")
    if student_id:
        student_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["student_id"] == student_id}
        items = [c for c in items if c["enrollment_id"] in student_enrollment_ids]

    status_filter = request.args.get("status")
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]

    # Director scope
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        own_course_ids = {c["id"] for c in db.courses.values() if c["school_id"] in own_school_ids}
        own_offering_ids = {o["id"] for o in db.offerings.values() if o["course_id"] in own_course_ids}
        own_enrollment_ids = {e["id"] for e in db.enrollments.values() if e["offering_id"] in own_offering_ids}
        items = [c for c in items if c["enrollment_id"] in own_enrollment_ids]

    items.sort(key=lambda c: c["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_cert_to_json(c) for c in page], limit, offset, total)


@bp.route("/certificates/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "Registrar", "ComplianceOfficer", "Student")
def get_certificate(id):
    cert = db.certificates.get(id)
    if not cert:
        errors.raise_error(errors.ERR_CERTIFICATE_NOT_FOUND,
                           f"Certificate {id} not found")
    auth = request.auth

    if auth["role"] == "Student":
        enrollment = db.enrollments.get(cert["enrollment_id"])
        if enrollment and enrollment["student_id"] != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own certificate")

    if auth["role"] == "SchoolDirector":
        enrollment = db.enrollments.get(cert["enrollment_id"])
        if enrollment:
            offering = db.offerings.get(enrollment["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    school = db.schools.get(course["school_id"])
                    if school and school.get("director_user_id") != auth["user_id"]:
                        errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")

    return success_object(_cert_to_json(cert))


@bp.route("/certificates/<id>/revoke", methods=["POST"])
@require_roles("StateCommission", "SchoolDirector")
def revoke_certificate(id):
    cert = db.certificates.get(id)
    if not cert:
        errors.raise_error(errors.ERR_CERTIFICATE_NOT_FOUND,
                           f"Certificate {id} not found")
    auth = request.auth

    body = get_json_body(required_fields=["reason"])

    # Director scope
    if auth["role"] == "SchoolDirector":
        enrollment = db.enrollments.get(cert["enrollment_id"])
        if enrollment:
            offering = db.offerings.get(enrollment["offering_id"])
            if offering:
                course = db.courses.get(offering["course_id"])
                if course:
                    school = db.schools.get(course["school_id"])
                    if school and school.get("director_user_id") != auth["user_id"]:
                        errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")

    if cert["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_GRANT_STATE_INVALID,
                           f"Certificate status is {cert['status']}, expected ACTIVE")

    revoke_certificate_cascade(cert, body["reason"], auth["role"], auth["user_id"])

    return success_object(_cert_to_json(cert))
