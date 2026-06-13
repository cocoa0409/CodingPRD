"""Driving School & Behind-the-Wheel API — Flask entry point."""
import os
import random
import string
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import db
import clock
import models
import response
from errors import ApiError, err
from middleware import get_auth, require_role
from helpers import (
    get_body,
    get_pagination,
    paginate,
    parse_dt,
    round_half_up_int,
    round_half_up_dp,
)

app = Flask(__name__)


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return response.error("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_NOT_FOUND", 404, "Method not allowed.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return response.error(e.error_id, e.http_status, e.message)
    return response.error("ERR_INVALID_REQUEST", 400, str(e))


# ===========================================================================
# Helpers
# ===========================================================================
def get_str(body, field, required=True, allow_empty=False):
    val = body.get(field)
    if val is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return None
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    if not allow_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be non-empty.")
    return val


def get_int(body, field, required=True, minimum=None, maximum=None, default=None):
    val = body.get(field)
    if val is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum.")
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum.")
    return val


def get_num(body, field, required=True, minimum=None, default=None):
    val = body.get(field)
    if val is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number.")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum.")
    return val


def get_bool(body, field, default=None, required=False):
    val = body.get(field)
    if val is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return val


def get_enum(body, field, allowed, required=True, default=None):
    val = body.get(field)
    if val is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} has invalid value.")
    return val


def mint_dmv_reference():
    return "DMV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def lookup(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


# ===========================================================================
# Ownership helpers
# ===========================================================================
def guardian_student_id(user_id):
    """For a Guardian role, the X-User-ID is a GuardianConsent.id. Return the
    ward's student_id, or raise NOT_FOUND if no such consent."""
    consent = db.guardian_consents.get(user_id)
    if consent is None:
        raise err("ERR_NOT_RESOURCE_OWNER", "Guardian consent not found.")
    return consent["student_id"]


def check_student_owns(user_id, role, resource_student_id):
    if role == "Student" and resource_student_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Student does not own this resource.")
    if role == "Guardian":
        ward = guardian_student_id(user_id)
        if resource_student_id != ward:
            raise err("ERR_NOT_RESOURCE_OWNER", "Guardian does not own this resource.")


def check_instructor_owns(user_id, role, resource_instructor_id):
    if role == "Instructor" and resource_instructor_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Instructor does not own this resource.")


# ===========================================================================
# CoursePackage
# ===========================================================================
@app.route("/course-packages", methods=["POST"])
def create_course_package():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    code = get_str(body, "code")
    name = get_str(body, "name", allow_empty=True)
    price_cents = get_int(body, "price_cents", minimum=0)
    enrollment_fee_cents = get_int(body, "enrollment_fee_cents", minimum=0)
    if enrollment_fee_cents > price_cents:
        raise err("ERR_INVALID_REQUEST", "enrollment_fee_cents may not exceed price_cents.")
    included_classroom_hours = get_num(body, "included_classroom_hours", minimum=0)
    included_online_hours = get_num(body, "included_online_hours", minimum=0)
    included_road_hours = get_num(body, "included_road_hours", minimum=0)
    bundle_discount_cents = get_int(body, "bundle_discount_cents", required=False, minimum=0, default=0)
    active = get_bool(body, "active", default=True)

    for p in db.course_packages.values():
        if p["code"] == code:
            raise err("ERR_DUPLICATE", "CoursePackage code already exists.")

    rec = {
        "id": db.new_id(),
        "code": code,
        "name": name,
        "price_cents": price_cents,
        "enrollment_fee_cents": enrollment_fee_cents,
        "included_classroom_hours": included_classroom_hours,
        "included_online_hours": included_online_hours,
        "included_road_hours": included_road_hours,
        "bundle_discount_cents": bundle_discount_cents,
        "active": active,
    }
    models.stamp_create_ledger(rec)
    db.course_packages[rec["id"]] = rec
    return response.ok(models.ser_course_package(rec), 201)


@app.route("/course-packages/<rid>", methods=["GET"])
def get_course_package(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian", "Instructor"})
    rec = lookup(db.course_packages, rid)
    return response.ok(models.ser_course_package(rec))


@app.route("/course-packages", methods=["GET"])
def list_course_packages():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian", "Instructor"})
    limit, offset = get_pagination()
    items = list(db.course_packages.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_course_package(p) for p in page], limit, offset, total)


# ===========================================================================
# Student
# ===========================================================================
@app.route("/students", methods=["POST"])
def create_student():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    full_name = get_str(body, "full_name", allow_empty=True)
    email = get_str(body, "email")
    dob = get_str(body, "date_of_birth")
    parse_dt(dob)  # validate format
    permit_number = get_str(body, "permit_number", required=False)

    for s in db.students.values():
        if s["email"] == email:
            raise err("ERR_DUPLICATE", "Student email already exists.")

    rec = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "date_of_birth": dob,
        "is_minor": models.compute_is_minor(dob),
        "permit_number": permit_number,
        "status": "PROSPECT",
        "completed_classroom_hours": 0,
        "completed_online_hours": 0,
        "completed_road_hours": 0,
        "scheduled_road_hours": 0,
        "readiness_score": 0,
        "no_show_count": 0,
        "wallet_balance_cents": 0,
    }
    models.stamp_create_full(rec)
    db.students[rec["id"]] = rec
    return response.ok(models.ser_student(rec), 201)


@app.route("/students/<rid>", methods=["GET"])
def get_student(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian", "Instructor"})
    rec = lookup(db.students, rid)
    if role in ("Student", "Guardian"):
        check_student_owns(user_id, role, rec["id"])
    return response.ok(models.ser_student(rec))


@app.route("/students", methods=["GET"])
def list_students():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin", "Instructor"})
    limit, offset = get_pagination()
    items = list(db.students.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_student(s) for s in page], limit, offset, total)


@app.route("/students/<rid>/record-permit", methods=["POST"])
def record_permit(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    rec = lookup(db.students, rid)
    permit_number = get_str(body, "permit_number")  # non-empty enforced

    if rec["status"] != "ENROLLED":
        raise err("ERR_INVALID_STATE", "Student must be ENROLLED to record a permit.")

    rec["permit_number"] = permit_number
    rec["status"] = "PERMITTED"
    models.touch(rec)
    return response.ok(models.ser_student(rec))


@app.route("/students/<rid>/certificate", methods=["POST"])
def issue_certificate(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    student = lookup(db.students, rid)
    enrollment_id = get_str(body, "enrollment_id")
    enrollment = lookup(db.enrollments, enrollment_id)

    if student["status"] != "ROAD_READY":
        raise err("ERR_INVALID_STATE", "Student must be ROAD_READY for certification.")
    if student["readiness_score"] != 1.0:
        raise err("ERR_READINESS_NOT_MET", "Student readiness_score must be 1.0.")

    cert = {
        "id": db.new_id(),
        "student_id": student["id"],
        "enrollment_id": enrollment["id"],
        "dmv_reference": None,
        "readiness_score_at_issue": student["readiness_score"],
        "status": "ISSUED",
    }
    models.stamp_create_full(cert)
    db.certificates[cert["id"]] = cert

    student["status"] = "CERTIFIED"
    models.touch(student)
    return response.ok(models.ser_certificate(cert), 201)


# ===========================================================================
# GuardianConsent
# ===========================================================================
@app.route("/guardian-consents", methods=["POST"])
def create_guardian_consent():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin", "Guardian"})
    body = get_body()

    student_id = get_str(body, "student_id")
    guardian_name = get_str(body, "guardian_name", allow_empty=True)
    guardian_email = get_str(body, "guardian_email")
    relationship = get_enum(body, "relationship", {"PARENT", "LEGAL_GUARDIAN"})

    lookup(db.students, student_id)

    rec = {
        "id": db.new_id(),
        "student_id": student_id,
        "guardian_name": guardian_name,
        "guardian_email": guardian_email,
        "relationship": relationship,
        "status": "PENDING",
    }
    models.stamp_create_full(rec)
    db.guardian_consents[rec["id"]] = rec
    return response.ok(models.ser_guardian_consent(rec), 201)


@app.route("/guardian-consents/<rid>", methods=["GET"])
def get_guardian_consent(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Guardian"})
    rec = lookup(db.guardian_consents, rid)
    if role == "Guardian":
        ward = guardian_student_id(user_id)
        if rec["student_id"] != ward:
            raise err("ERR_NOT_RESOURCE_OWNER", "Guardian does not own this consent.")
    return response.ok(models.ser_guardian_consent(rec))


@app.route("/guardian-consents", methods=["GET"])
def list_guardian_consents():
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Guardian"})
    limit, offset = get_pagination()
    items = list(db.guardian_consents.values())
    if role == "Guardian":
        ward = guardian_student_id(user_id)
        items = [g for g in items if g["student_id"] == ward]
    sid = request.args.get("student_id")
    if sid is not None:
        items = [g for g in items if g["student_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_guardian_consent(g) for g in page], limit, offset, total)


@app.route("/guardian-consents/<rid>/grant", methods=["POST"])
def grant_guardian_consent(rid):
    user_id, role = get_auth()
    require_role(role, {"Guardian"})
    rec = lookup(db.guardian_consents, rid)
    # Guardian identity is the consent row itself.
    if rec["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Guardian may only act on own consent.")
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Consent must be PENDING to grant.")
    rec["status"] = "GRANTED"
    models.touch(rec)
    return response.ok(models.ser_guardian_consent(rec))


@app.route("/guardian-consents/<rid>/revoke", methods=["POST"])
def revoke_guardian_consent(rid):
    user_id, role = get_auth()
    require_role(role, {"Guardian"})
    rec = lookup(db.guardian_consents, rid)
    if rec["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Guardian may only act on own consent.")
    if rec["status"] != "GRANTED":
        raise err("ERR_INVALID_STATE", "Consent must be GRANTED to revoke.")
    rec["status"] = "REVOKED"
    models.touch(rec)
    return response.ok(models.ser_guardian_consent(rec))


# ===========================================================================
# Enrollment
# ===========================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    student_id = get_str(body, "student_id")
    package_id = get_str(body, "package_id")
    promo_code = get_str(body, "promo_code", required=False)

    lookup(db.students, student_id)
    lookup(db.course_packages, package_id)

    rec = {
        "id": db.new_id(),
        "student_id": student_id,
        "package_id": package_id,
        "promo_code": promo_code,
        "status": "DRAFT",
        "final_price_cents": 0,
        "amount_paid_cents": 0,
        "refund_method": None,
        "refunded_cents": 0,
        "activated_at": None,
    }
    models.stamp_create_full(rec)
    db.enrollments[rec["id"]] = rec
    return response.ok(models.ser_enrollment(rec), 201)


@app.route("/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    rec = lookup(db.enrollments, rid)
    if role in ("Student", "Guardian"):
        check_student_owns(user_id, role, rec["student_id"])
    return response.ok(models.ser_enrollment(rec))


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    limit, offset = get_pagination()
    items = list(db.enrollments.values())
    if role == "Student":
        items = [e for e in items if e["student_id"] == user_id]
    elif role == "Guardian":
        ward = guardian_student_id(user_id)
        items = [e for e in items if e["student_id"] == ward]
    sid = request.args.get("student_id")
    if sid is not None:
        items = [e for e in items if e["student_id"] == sid]
    pid = request.args.get("package_id")
    if pid is not None:
        items = [e for e in items if e["package_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_enrollment(e) for e in page], limit, offset, total)


def _compute_final_price(enrollment, package, student):
    subtotal = Decimal(package["price_cents"])
    if student["is_minor"]:
        subtotal = subtotal * (Decimal(1) - models.TEEN_DISCOUNT_PCT)
    if enrollment["promo_code"] == "FLAT10":
        subtotal = subtotal * (Decimal(1) - models.PROMO_FLAT10_PCT)
    if package["included_classroom_hours"] > 0 and package["included_road_hours"] > 0:
        subtotal = subtotal - Decimal(package["bundle_discount_cents"])
    cents = int(subtotal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(0, cents)


@app.route("/enrollments/<rid>/activate", methods=["POST"])
def activate_enrollment(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    rec = lookup(db.enrollments, rid)
    package = lookup(db.course_packages, rec["package_id"])
    student = lookup(db.students, rec["student_id"])

    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Enrollment must be DRAFT to activate.")
    if not package["active"]:
        raise err("ERR_VALIDATION", "Course package is not active.")
    if student["is_minor"]:
        granted = any(
            g["student_id"] == student["id"] and g["status"] == "GRANTED"
            for g in db.guardian_consents.values()
        )
        if not granted:
            raise err("ERR_GUARDIAN_CONSENT_REQUIRED", "Minor requires a GRANTED guardian consent.")

    final_price = _compute_final_price(rec, package, student)
    rec["final_price_cents"] = final_price
    rec["amount_paid_cents"] = final_price
    rec["activated_at"] = clock.iso_now()
    rec["status"] = "ACTIVE"
    models.touch(rec)

    if student["status"] == "PROSPECT":
        student["status"] = "ENROLLED"
        models.touch(student)

    return response.ok(models.ser_enrollment(rec))


@app.route("/enrollments/<rid>/complete", methods=["POST"])
def complete_enrollment(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    rec = lookup(db.enrollments, rid)

    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to complete.")
    has_cert = any(
        c["enrollment_id"] == rec["id"]
        and c["student_id"] == rec["student_id"]
        and c["status"] in ("ISSUED", "SUBMITTED", "ACCEPTED")
        for c in db.certificates.values()
    )
    if not has_cert:
        raise err("ERR_INVALID_STATE", "Enrollment requires a certificate to complete.")

    rec["status"] = "COMPLETED"
    models.touch(rec)
    return response.ok(models.ser_enrollment(rec))


def _cascade_cancel_scheduled_lessons(enrollment, student):
    """Cancel every SCHEDULED lesson under the enrollment. Releases scheduled
    road hours back to the student ledger. Returns whether the student changed."""
    student_changed = False
    for lesson in db.lessons.values():
        if lesson["enrollment_id"] == enrollment["id"] and lesson["status"] == "SCHEDULED":
            lesson["status"] = "CANCELLED"
            models.touch(lesson)
            if lesson["lesson_type"] == "ROAD":
                student["scheduled_road_hours"] = round(
                    student["scheduled_road_hours"] - lesson["duration_hours"], 2
                )
                student_changed = True
    return student_changed


@app.route("/enrollments/<rid>/cancel", methods=["POST"])
def cancel_enrollment(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    rec = lookup(db.enrollments, rid)
    student = lookup(db.students, rec["student_id"])

    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to cancel.")
    completed_exists = any(
        l["enrollment_id"] == rec["id"] and l["status"] == "COMPLETED"
        for l in db.lessons.values()
    )
    if completed_exists:
        raise err("ERR_INVALID_STATE", "Cannot cancel an enrollment with completed lessons.")

    changed = _cascade_cancel_scheduled_lessons(rec, student)
    if changed:
        models.touch(student)

    rec["status"] = "CANCELLED"
    models.touch(rec)
    return response.ok(models.ser_enrollment(rec))


def _compute_refund(enrollment, package, student, method):
    refundable_base = enrollment["final_price_cents"] - package["enrollment_fee_cents"]
    if refundable_base < 0:
        refundable_base = 0
    if method == "PRO_RATA":
        consumed = student["completed_road_hours"]
        remaining = package["included_road_hours"] - consumed
        if remaining < 0:
            remaining = 0
        included = package["included_road_hours"]
        if included <= 0:
            ratio = Decimal(0)
        else:
            ratio = Decimal(str(remaining)) / Decimal(str(included))
        amount = Decimal(refundable_base) * ratio
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:  # SCHEDULE_TIER
        activated = parse_dt(enrollment["activated_at"])
        elapsed_days = (clock.now() - activated).total_seconds() / 86400.0
        import math
        elapsed_days = math.floor(elapsed_days)
        if elapsed_days <= models.TIER1_DAYS:
            pct = Decimal("1.00")
        elif elapsed_days <= models.TIER2_DAYS:
            pct = Decimal("0.75")
        elif elapsed_days <= models.TIER3_DAYS:
            pct = Decimal("0.50")
        else:
            pct = Decimal("0.00")
        amount = Decimal(refundable_base) * pct
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@app.route("/enrollments/<rid>/refund", methods=["POST"])
def refund_enrollment(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    rec = lookup(db.enrollments, rid)
    package = lookup(db.course_packages, rec["package_id"])
    student = lookup(db.students, rec["student_id"])

    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment must be ACTIVE to refund.")

    refund_method = get_enum(body, "refund_method", {"PRO_RATA", "SCHEDULE_TIER"})
    get_enum(body, "refund_destination", {"WALLET"})

    changed = _cascade_cancel_scheduled_lessons(rec, student)

    refunded = _compute_refund(rec, package, student, refund_method)
    rec["refund_method"] = refund_method
    rec["refunded_cents"] = refunded

    wallet = {
        "id": db.new_id(),
        "student_id": student["id"],
        "amount_cents": refunded,
        "reason": "REFUND_CREDIT",
        "enrollment_id": rec["id"],
    }
    models.stamp_create_ledger(wallet)
    db.wallet_entries[wallet["id"]] = wallet
    models.recompute_wallet(student)

    if changed or True:
        models.touch(student)

    rec["status"] = "REFUNDED"
    models.touch(rec)
    return response.ok(models.ser_enrollment(rec))


# ===========================================================================
# Instructor
# ===========================================================================
@app.route("/instructors", methods=["POST"])
def create_instructor():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    full_name = get_str(body, "full_name", allow_empty=True)
    email = get_str(body, "email")
    certified_road = get_bool(body, "certified_road", default=False)
    hourly_rate_cents = get_int(body, "hourly_rate_cents", minimum=0)
    active = get_bool(body, "active", default=True)

    for i in db.instructors.values():
        if i["email"] == email:
            raise err("ERR_DUPLICATE", "Instructor email already exists.")

    rec = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "certified_road": certified_road,
        "hourly_rate_cents": hourly_rate_cents,
        "active": active,
    }
    models.stamp_create_full(rec)
    db.instructors[rec["id"]] = rec
    return response.ok(models.ser_instructor(rec), 201)


@app.route("/instructors/<rid>", methods=["GET"])
def get_instructor(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Instructor"})
    rec = lookup(db.instructors, rid)
    if role == "Instructor" and rec["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Instructor does not own this resource.")
    return response.ok(models.ser_instructor(rec))


@app.route("/instructors", methods=["GET"])
def list_instructors():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    limit, offset = get_pagination()
    items = list(db.instructors.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [i for i in items if i["active"] == want]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_instructor(i) for i in page], limit, offset, total)


@app.route("/instructors/<rid>/payout-summary", methods=["GET"])
def instructor_payout_summary(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Instructor"})
    rec = lookup(db.instructors, rid)
    if role == "Instructor" and rec["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Instructor does not own this resource.")

    period_start_raw = request.args.get("period_start")
    period_end_raw = request.args.get("period_end")
    if period_start_raw is None or period_end_raw is None:
        raise err("ERR_INVALID_REQUEST", "period_start and period_end are required.")
    period_start = parse_dt(period_start_raw)
    period_end = parse_dt(period_end_raw)

    total = 0
    count = 0
    for l in db.lessons.values():
        if l["instructor_id"] != rec["id"]:
            continue
        if l["status"] != "COMPLETED":
            continue
        start_at = parse_dt(l["start_at"])
        if period_start <= start_at < period_end:
            total += l["instructor_payout_cents"]
            count += 1

    return response.ok({"period_total_cents": total, "lesson_count": count})


# ===========================================================================
# Vehicle
# ===========================================================================
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    plate = get_str(body, "plate")
    dual_control = get_bool(body, "dual_control", default=False)
    prep_buffer_minutes = get_int(body, "prep_buffer_minutes", required=False, minimum=0, default=0)
    out_of_service = get_bool(body, "out_of_service", default=False)

    for v in db.vehicles.values():
        if v["plate"] == plate:
            raise err("ERR_DUPLICATE", "Vehicle plate already exists.")

    rec = {
        "id": db.new_id(),
        "plate": plate,
        "dual_control": dual_control,
        "prep_buffer_minutes": prep_buffer_minutes,
        "out_of_service": out_of_service,
    }
    models.stamp_create_full(rec)
    db.vehicles[rec["id"]] = rec
    return response.ok(models.ser_vehicle(rec), 201)


@app.route("/vehicles/<rid>", methods=["GET"])
def get_vehicle(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin", "Instructor"})
    rec = lookup(db.vehicles, rid)
    return response.ok(models.ser_vehicle(rec))


@app.route("/vehicles", methods=["GET"])
def list_vehicles():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    limit, offset = get_pagination()
    items = list(db.vehicles.values())
    oos = request.args.get("out_of_service")
    if oos is not None:
        want = oos.lower() == "true"
        items = [v for v in items if v["out_of_service"] == want]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_vehicle(v) for v in page], limit, offset, total)


# ===========================================================================
# Lesson
# ===========================================================================
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: true overlap, adjacency allowed."""
    return a_start < b_end and b_start < a_end


@app.route("/lessons", methods=["POST"])
def create_lesson():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    # --- request well-formedness for the structural fields needed to resolve ---
    student_id = get_str(body, "student_id")
    enrollment_id = get_str(body, "enrollment_id")
    lesson_type = get_enum(body, "lesson_type", {"CLASSROOM", "ONLINE", "ROAD"})
    start_at_raw = get_str(body, "start_at")
    end_at_raw = get_str(body, "end_at")
    expected_version = get_int(body, "expected_student_version")
    instructor_id = body.get("instructor_id")
    vehicle_id = body.get("vehicle_id")

    # --- existence resolution: path/body left-to-right (§2.5) ---
    student = lookup(db.students, student_id)
    enrollment = lookup(db.enrollments, enrollment_id)
    instructor = None
    if instructor_id is not None:
        instructor = lookup(db.instructors, instructor_id)
    vehicle = None
    if vehicle_id is not None:
        vehicle = lookup(db.vehicles, vehicle_id)

    # --- OCC (priority 6) ---
    if expected_version != student["version"]:
        raise err("ERR_STALE_STUDENT_VERSION", "Stale student version.")

    # --- parse interval (needed for several checks) ---
    start_at = parse_dt(start_at_raw)
    end_at = parse_dt(end_at_raw)
    duration_hours = round((end_at - start_at).total_seconds() / 3600.0, 2)

    # An instructor is required for CLASSROOM and ROAD; a vehicle for ROAD.
    if lesson_type in ("CLASSROOM", "ROAD") and instructor is None:
        raise err("ERR_INVALID_REQUEST", "instructor_id required for this lesson type.")
    if lesson_type == "ROAD" and vehicle is None:
        raise err("ERR_INVALID_REQUEST", "vehicle_id required for ROAD lessons.")

    # --- guardian consent (priority 7) for minor ROAD ---
    if lesson_type == "ROAD" and student["is_minor"]:
        granted = any(
            g["student_id"] == student["id"] and g["status"] == "GRANTED"
            for g in db.guardian_consents.values()
        )
        if not granted:
            raise err("ERR_GUARDIAN_CONSENT_REQUIRED", "Minor requires GRANTED guardian consent for ROAD.")

    # --- road prerequisites (priority 8) ---
    if lesson_type == "ROAD":
        if student["status"] not in ("PERMITTED", "ROAD_READY"):
            raise err("ERR_ROAD_PREREQUISITE_NOT_MET", "Student lacks recorded permit.")
        if not instructor["certified_road"]:
            raise err("ERR_ROAD_PREREQUISITE_NOT_MET", "Instructor not certified for road.")
        if not vehicle["dual_control"]:
            raise err("ERR_ROAD_PREREQUISITE_NOT_MET", "Vehicle lacks dual control.")

    # --- referential availability (priority 9) ---
    if instructor is not None and not instructor["active"]:
        raise err("ERR_RESOURCE_UNAVAILABLE", "Instructor is inactive.")
    if vehicle is not None and vehicle["out_of_service"]:
        raise err("ERR_RESOURCE_UNAVAILABLE", "Vehicle is out of service.")
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_UNAVAILABLE", "Funding enrollment is not ACTIVE.")

    # --- interval well-formedness (priority 10) ---
    if not (end_at > start_at):
        raise err("ERR_INVALID_INTERVAL", "end_at must be strictly after start_at.")
    if not (start_at > clock.now()):
        raise err("ERR_INVALID_INTERVAL", "start_at must be in the future.")

    # --- instructor double-booking (priority 11) ---
    if instructor is not None:
        for l in db.lessons.values():
            if l["status"] != "SCHEDULED":
                continue
            if l["instructor_id"] != instructor["id"]:
                continue
            ls = parse_dt(l["start_at"])
            le = parse_dt(l["end_at"])
            if _intervals_overlap(start_at, end_at, ls, le):
                raise err("ERR_INSTRUCTOR_DOUBLE_BOOKED", "Instructor double-booked.")

    # --- vehicle double-booking with prep buffer (priority 12), ROAD only ---
    if lesson_type == "ROAD" and vehicle is not None:
        from datetime import timedelta
        buffer = timedelta(minutes=vehicle["prep_buffer_minutes"])
        for l in db.lessons.values():
            if l["status"] != "SCHEDULED":
                continue
            if l["vehicle_id"] != vehicle["id"]:
                continue
            ls = parse_dt(l["start_at"])
            le = parse_dt(l["end_at"]) + buffer
            if _intervals_overlap(start_at, end_at, ls, le):
                raise err("ERR_VEHICLE_DOUBLE_BOOKED", "Vehicle double-booked.")

    # --- road-hour ceiling (priority 13) ---
    if lesson_type == "ROAD":
        package = db.course_packages.get(enrollment["package_id"])
        included = package["included_road_hours"] if package else 0
        projected = student["scheduled_road_hours"] + student["completed_road_hours"] + duration_hours
        if round(projected, 2) > included:
            raise err("ERR_ROAD_HOURS_EXCEEDED", "Scheduling exceeds included road hours.")

    # --- create ---
    rec = {
        "id": db.new_id(),
        "student_id": student["id"],
        "enrollment_id": enrollment["id"],
        "instructor_id": instructor["id"] if instructor else None,
        "vehicle_id": vehicle["id"] if vehicle else None,
        "lesson_type": lesson_type,
        "start_at": start_at_raw,
        "end_at": end_at_raw,
        "duration_hours": duration_hours,
        "status": "SCHEDULED",
        "instructor_payout_cents": 0,
    }
    models.stamp_create_full(rec)
    db.lessons[rec["id"]] = rec

    if lesson_type == "ROAD":
        student["scheduled_road_hours"] = round(
            student["scheduled_road_hours"] + duration_hours, 2
        )
    models.touch(student)

    return response.ok(models.ser_lesson(rec), 201)


@app.route("/lessons/<rid>", methods=["GET"])
def get_lesson(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Instructor", "Guardian"})
    rec = lookup(db.lessons, rid)
    if role == "Student":
        check_student_owns(user_id, role, rec["student_id"])
    elif role == "Guardian":
        check_student_owns(user_id, role, rec["student_id"])
    elif role == "Instructor":
        check_instructor_owns(user_id, role, rec["instructor_id"])
    return response.ok(models.ser_lesson(rec))


@app.route("/lessons", methods=["GET"])
def list_lessons():
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Instructor", "Guardian"})
    limit, offset = get_pagination()
    items = list(db.lessons.values())
    if role == "Student":
        items = [l for l in items if l["student_id"] == user_id]
    elif role == "Guardian":
        ward = guardian_student_id(user_id)
        items = [l for l in items if l["student_id"] == ward]
    elif role == "Instructor":
        items = [l for l in items if l["instructor_id"] == user_id]

    for key in ("student_id", "enrollment_id", "instructor_id", "vehicle_id", "status", "lesson_type"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l[key] == val]

    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_lesson(l) for l in page], limit, offset, total)


@app.route("/lessons/<rid>/complete", methods=["POST"])
def complete_lesson(rid):
    user_id, role = get_auth()
    require_role(role, {"Instructor"})
    rec = lookup(db.lessons, rid)
    if rec["instructor_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Instructor may only complete own lessons.")

    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Lesson must be SCHEDULED to complete.")
    end_at = parse_dt(rec["end_at"])
    if clock.now() < end_at:
        raise err("ERR_INVALID_STATE", "Lesson cannot be completed before its end.")

    student = db.students[rec["student_id"]]
    rec["status"] = "COMPLETED"
    models.touch(rec)

    dur = rec["duration_hours"]
    if rec["lesson_type"] == "CLASSROOM":
        student["completed_classroom_hours"] = round(student["completed_classroom_hours"] + dur, 2)
    elif rec["lesson_type"] == "ONLINE":
        student["completed_online_hours"] = round(student["completed_online_hours"] + dur, 2)
    elif rec["lesson_type"] == "ROAD":
        student["completed_road_hours"] = round(student["completed_road_hours"] + dur, 2)
        student["scheduled_road_hours"] = round(student["scheduled_road_hours"] - dur, 2)

    # instructor payout per-line
    instructor = db.instructors.get(rec["instructor_id"])
    rate = instructor["hourly_rate_cents"] if instructor else 0
    rec["instructor_payout_cents"] = round_half_up_int(Decimal(rate) * Decimal(str(dur)))

    models.recompute_readiness(student)
    if rec["lesson_type"] == "ROAD":
        models.maybe_regress_or_advance_milestone(student)
    models.touch(student)

    return response.ok(models.ser_lesson(rec))


@app.route("/lessons/<rid>/no-show", methods=["POST"])
def no_show_lesson(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    rec = lookup(db.lessons, rid)

    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Lesson must be SCHEDULED to mark no-show.")
    start_at = parse_dt(rec["start_at"])
    if clock.now() < start_at:
        raise err("ERR_INVALID_STATE", "Cannot mark no-show before start_at.")

    student = db.students[rec["student_id"]]
    rec["status"] = "NO_SHOW"
    models.touch(rec)

    strike_index = student["no_show_count"] + 1
    if strike_index <= models.FORGIVE_STRIKES:
        fee = 0
    elif strike_index == models.FORGIVE_STRIKES + 1:
        fee = models.BASE_NO_SHOW_FEE_CENTS
    else:
        fee = models.BASE_NO_SHOW_FEE_CENTS * models.ESCALATION_MULTIPLIER

    strike = {
        "id": db.new_id(),
        "student_id": student["id"],
        "lesson_id": rec["id"],
        "strike_index": strike_index,
        "fee_charged_cents": fee,
    }
    models.stamp_create_ledger(strike)
    db.no_show_strikes[strike["id"]] = strike

    if fee > 0:
        wallet = {
            "id": db.new_id(),
            "student_id": student["id"],
            "amount_cents": -fee,
            "reason": "NO_SHOW_DEBIT",
            "enrollment_id": rec["enrollment_id"],
        }
        models.stamp_create_ledger(wallet)
        db.wallet_entries[wallet["id"]] = wallet

    if rec["lesson_type"] == "ROAD":
        student["scheduled_road_hours"] = round(
            student["scheduled_road_hours"] - rec["duration_hours"], 2
        )

    models.recompute_no_show_count(student)
    models.recompute_wallet(student)
    models.touch(student)

    return response.ok(models.ser_lesson(rec))


@app.route("/lessons/<rid>/cancel", methods=["POST"])
def cancel_lesson(rid):
    user_id, role = get_auth()
    require_role(role, {"Student"})
    rec = lookup(db.lessons, rid)
    if rec["student_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Student may only cancel own lessons.")

    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Lesson must be SCHEDULED to cancel.")
    from datetime import timedelta
    start_at = parse_dt(rec["start_at"])
    cutoff = start_at - timedelta(hours=models.CANCEL_CUTOFF_HOURS)
    if not (clock.now() < cutoff):
        raise err("ERR_INVALID_STATE", "Cannot cancel inside the cutoff window.")

    student = db.students[rec["student_id"]]
    rec["status"] = "CANCELLED"
    models.touch(rec)

    if rec["lesson_type"] == "ROAD":
        student["scheduled_road_hours"] = round(
            student["scheduled_road_hours"] - rec["duration_hours"], 2
        )
    models.touch(student)

    return response.ok(models.ser_lesson(rec))


# ===========================================================================
# NoShowStrike
# ===========================================================================
@app.route("/no-show-strikes/<rid>", methods=["GET"])
def get_no_show_strike(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    rec = lookup(db.no_show_strikes, rid)
    if role in ("Student", "Guardian"):
        check_student_owns(user_id, role, rec["student_id"])
    return response.ok(models.ser_no_show_strike(rec))


@app.route("/no-show-strikes", methods=["GET"])
def list_no_show_strikes():
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    limit, offset = get_pagination()
    items = list(db.no_show_strikes.values())
    if role == "Student":
        items = [n for n in items if n["student_id"] == user_id]
    elif role == "Guardian":
        ward = guardian_student_id(user_id)
        items = [n for n in items if n["student_id"] == ward]
    sid = request.args.get("student_id")
    if sid is not None:
        items = [n for n in items if n["student_id"] == sid]
    lid = request.args.get("lesson_id")
    if lid is not None:
        items = [n for n in items if n["lesson_id"] == lid]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_no_show_strike(n) for n in page], limit, offset, total)


# ===========================================================================
# WalletEntry
# ===========================================================================
@app.route("/wallet-entries/<rid>", methods=["GET"])
def get_wallet_entry(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    rec = lookup(db.wallet_entries, rid)
    if role in ("Student", "Guardian"):
        check_student_owns(user_id, role, rec["student_id"])
    return response.ok(models.ser_wallet_entry(rec))


@app.route("/wallet-entries", methods=["GET"])
def list_wallet_entries():
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    limit, offset = get_pagination()
    items = list(db.wallet_entries.values())
    if role == "Student":
        items = [w for w in items if w["student_id"] == user_id]
    elif role == "Guardian":
        ward = guardian_student_id(user_id)
        items = [w for w in items if w["student_id"] == ward]
    sid = request.args.get("student_id")
    if sid is not None:
        items = [w for w in items if w["student_id"] == sid]
    eid = request.args.get("enrollment_id")
    if eid is not None:
        items = [w for w in items if w["enrollment_id"] == eid]
    reason = request.args.get("reason")
    if reason is not None:
        items = [w for w in items if w["reason"] == reason]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_wallet_entry(w) for w in page], limit, offset, total)


@app.route("/wallet-entries", methods=["POST"])
def create_wallet_entry():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()

    student_id = get_str(body, "student_id")
    amount_cents = get_int(body, "amount_cents")
    reason = get_enum(body, "reason", {"REFUND_CREDIT", "NO_SHOW_DEBIT", "ADMIN_ADJUSTMENT"})
    enrollment_id = body.get("enrollment_id")

    student = lookup(db.students, student_id)
    if enrollment_id is not None:
        lookup(db.enrollments, enrollment_id)

    rec = {
        "id": db.new_id(),
        "student_id": student_id,
        "amount_cents": amount_cents,
        "reason": reason,
        "enrollment_id": enrollment_id,
    }
    models.stamp_create_ledger(rec)
    db.wallet_entries[rec["id"]] = rec
    models.recompute_wallet(student)
    models.touch(student)
    return response.ok(models.ser_wallet_entry(rec), 201)


# ===========================================================================
# Certificate
# ===========================================================================
@app.route("/certificates/<rid>", methods=["GET"])
def get_certificate(rid):
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    rec = lookup(db.certificates, rid)
    if role in ("Student", "Guardian"):
        check_student_owns(user_id, role, rec["student_id"])
    return response.ok(models.ser_certificate(rec))


@app.route("/certificates", methods=["GET"])
def list_certificates():
    user_id, role = get_auth()
    require_role(role, {"SchoolAdmin", "Student", "Guardian"})
    limit, offset = get_pagination()
    items = list(db.certificates.values())
    if role == "Student":
        items = [c for c in items if c["student_id"] == user_id]
    elif role == "Guardian":
        ward = guardian_student_id(user_id)
        items = [c for c in items if c["student_id"] == ward]
    sid = request.args.get("student_id")
    if sid is not None:
        items = [c for c in items if c["student_id"] == sid]
    eid = request.args.get("enrollment_id")
    if eid is not None:
        items = [c for c in items if c["enrollment_id"] == eid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return response.ok_list([models.ser_certificate(c) for c in page], limit, offset, total)


@app.route("/certificates/<rid>/submit", methods=["POST"])
def submit_certificate(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    rec = lookup(db.certificates, rid)
    if rec["status"] not in ("ISSUED", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Certificate must be ISSUED or REJECTED to submit.")
    rec["dmv_reference"] = mint_dmv_reference()
    rec["status"] = "SUBMITTED"
    models.touch(rec)
    return response.ok(models.ser_certificate(rec))


@app.route("/certificates/<rid>/dmv-callback", methods=["POST"])
def dmv_callback(rid):
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    rec = lookup(db.certificates, rid)
    outcome = get_enum(body, "outcome", {"ACCEPTED", "REJECTED"})

    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Certificate must be SUBMITTED to record a decision.")

    if outcome == "ACCEPTED":
        rec["status"] = "ACCEPTED"
        models.touch(rec)
        student = db.students.get(rec["student_id"])
        if student is not None and student["status"] == "CERTIFIED":
            student["status"] = "LICENSED"
            models.touch(student)
    else:
        rec["status"] = "REJECTED"
        models.touch(rec)

    return response.ok(models.ser_certificate(rec))


# ===========================================================================
# Clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    to_iso = get_str(body, "to_iso8601")
    dt = parse_dt(to_iso)
    clock.set_now(dt)
    return response.ok({})


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
