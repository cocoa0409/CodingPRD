import math
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, g, request

import constants as C
import errors as E
from audit import write_audit
from clock import CLOCK, parse_iso
from db import DATA, bump, init_common, init_immutable
from instructor_calc import (
    distinct_working_dates_in_week_after,
    instructor_calendar_conflict,
    serialize_instructor,
    vehicle_calendar_conflict,
    working_minutes_this_week,
    working_minutes_today,
)
from lookups import (
    get_complaint,
    get_exam,
    get_instructor,
    get_package,
    get_practice,
    get_simulator,
    get_student,
    get_vehicle,
    occ_check,
)
from middleware import VALID_ROLES, extract_auth, get_body, require_roles, required, required_present
from response import error_response, success_array, success_object
from student_calc import (
    exam_attempts_remaining,
    has_passed_basic_practical,
    minutes_remaining_provisional,
    no_show_count_this_cycle,
    package_for_student,
    reschedule_count_this_cycle,
    serialize_student,
    simulator_sessions_remaining,
)


app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------
@app.errorhandler(E.APIError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(E.ERR_INVALID_REQUEST, "Not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(E.ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", str(err), 500)


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise E.APIError(E.ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise E.APIError(E.ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise E.APIError(E.ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise E.APIError(E.ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# STUDENTS
# ---------------------------------------------------------------------------
@app.route("/students", methods=["POST"])
def create_student():
    extract_auth()
    require_roles({"Admin"})
    body = get_body()
    required(body, "full_name", "id_number", "id_card_country")
    student = {
        "full_name": body["full_name"],
        "id_number": body["id_number"],
        "id_card_country": body["id_card_country"],
        "id_verified": False,
        "medical_cert_status": "PENDING",
        "medical_cert_expires_on": None,
        "course_package_id": None,
        "contract_signed_at": None,
        "training_stage": "THEORY",
        "enrollment_status": "PENDING_VERIFICATION",
        "cycle_start_date": None,
        "suspension_reason": None,
    }
    init_common(student)
    DATA.students[student["id"]] = student
    write_audit(g.user_role, g.user_id, "Student", student["id"], "CREATE")
    return success_object(serialize_student(student), 201)


@app.route("/students/<sid>", methods=["GET"])
def get_student_route(sid):
    extract_auth()
    require_roles({"Admin", "Student"})
    student = get_student(sid)
    if g.user_role == "Student" and g.user_id != sid:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    return success_object(serialize_student(student))


def _require_student_pending(student, expected_status):
    if student["enrollment_status"] != expected_status:
        raise E.APIError(E.ERR_STUDENT_NOT_AT_PENDING_STATE, 409,
                         f"Student must be in {expected_status}")


@app.route("/students/<sid>/verify-identity", methods=["POST"])
def verify_identity(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    body = get_body()
    occ_check(student, body)
    _require_student_pending(student, "PENDING_VERIFICATION")
    if not student.get("id_number") or not student.get("id_card_country"):
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "id_number and id_card_country must be present")
    student["id_verified"] = True
    student["enrollment_status"] = "PENDING_MEDICAL"
    bump(student)
    write_audit(g.user_role, g.user_id, "Student", student["id"], "UPDATE")
    return success_object(serialize_student(student))


@app.route("/students/<sid>/submit-medical-cert", methods=["POST"])
def submit_medical_cert(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    body = get_body()
    occ_check(student, body)
    _require_student_pending(student, "PENDING_MEDICAL")
    required(body, "medical_cert_expires_on")
    expires_on = parse_iso(body["medical_cert_expires_on"])
    if expires_on is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "medical_cert_expires_on is not a valid ISO 8601 date")
    if expires_on <= CLOCK.now():
        raise E.APIError(E.ERR_MEDICAL_CERT_EXPIRED, 409,
                         "medical_cert_expires_on must be strictly after the logical clock")
    student["medical_cert_expires_on"] = body["medical_cert_expires_on"]
    student["medical_cert_status"] = "VALID"
    student["enrollment_status"] = "PENDING_PACKAGE"
    bump(student)
    write_audit(g.user_role, g.user_id, "Student", student["id"], "UPDATE")
    return success_object(serialize_student(student))


@app.route("/students/<sid>/select-package", methods=["POST"])
def select_package(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    body = get_body()
    occ_check(student, body)
    _require_student_pending(student, "PENDING_PACKAGE")
    required(body, "course_package_id")
    pkg = get_package(body["course_package_id"])
    student["course_package_id"] = pkg["id"]
    student["enrollment_status"] = "PENDING_CONTRACT"
    bump(student)
    write_audit(g.user_role, g.user_id, "Student", student["id"], "UPDATE")
    return success_object(serialize_student(student))


@app.route("/students/<sid>/sign-contract", methods=["POST"])
def sign_contract(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    body = get_body()
    occ_check(student, body)
    _require_student_pending(student, "PENDING_CONTRACT")
    # Re-check medical cert expiry against logical clock
    expires_on = parse_iso(student.get("medical_cert_expires_on"))
    if expires_on is None or expires_on <= CLOCK.now():
        raise E.APIError(E.ERR_MEDICAL_CERT_EXPIRED, 409,
                         "Medical certificate has expired")
    if student.get("medical_cert_status") != "VALID":
        raise E.APIError(E.ERR_MEDICAL_CERT_EXPIRED, 409, "Medical certificate is not valid")
    now = CLOCK.iso()
    student["contract_signed_at"] = now
    student["cycle_start_date"] = now
    student["training_stage"] = "THEORY"
    student["enrollment_status"] = "ACTIVE"
    bump(student)
    write_audit(g.user_role, g.user_id, "Student", student["id"], "UPDATE")
    return success_object(serialize_student(student))


@app.route("/students/<sid>/suspend", methods=["POST"])
def suspend_student(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    body = get_body()
    occ_check(student, body)
    if student["enrollment_status"] != "ACTIVE":
        raise E.APIError(E.ERR_STUDENT_NOT_ACTIVE, 409, "Student is not ACTIVE")
    student["enrollment_status"] = "SUSPENDED"
    student["suspension_reason"] = "ADMIN_ACTION"
    bump(student)
    write_audit(g.user_role, g.user_id, "Student", student["id"], "UPDATE")
    return success_object(serialize_student(student))


@app.route("/students/<sid>/reinstate", methods=["POST"])
def reinstate_student(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    body = get_body()
    occ_check(student, body)
    if student["enrollment_status"] != "SUSPENDED":
        raise E.APIError(E.ERR_STUDENT_NOT_AT_PENDING_STATE, 409, "Student is not SUSPENDED")
    student["enrollment_status"] = "ACTIVE"
    student["suspension_reason"] = None
    bump(student)
    write_audit(g.user_role, g.user_id, "Student", student["id"], "UPDATE")
    return success_object(serialize_student(student))


@app.route("/students/<sid>/training-hours", methods=["GET"])
def get_training_hours(sid):
    extract_auth()
    require_roles({"Admin", "Student"})
    student = get_student(sid)
    if g.user_role == "Student" and g.user_id != sid:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    totals = {"THEORY": 0, "BASIC": 0, "HIGHWAY": 0}
    totals_validated = {"THEORY": 0, "BASIC": 0, "HIGHWAY": 0}
    records = []
    for r in DATA.training_hour_records.values():
        if r["student_id"] != sid:
            continue
        records.append(r)
        stage = r["training_stage"]
        if stage in totals:
            totals[stage] += r["minutes_recorded"]
            if r.get("gps_validated"):
                totals_validated[stage] += r["minutes_recorded"]
    records.sort(key=lambda r: r["created_at"])
    return success_object({
        "totals": totals,
        "totals_validated": totals_validated,
        "records": records,
    })


@app.route("/students/<sid>/submit-hours-to-authority", methods=["POST"])
def submit_hours_to_authority(sid):
    extract_auth()
    require_roles({"Admin"})
    student = get_student(sid)
    now_iso = CLOCK.iso()
    submitted = []
    for r in DATA.training_hour_records.values():
        if r["student_id"] != sid:
            continue
        if r["authority_submission_status"] == "PENDING":
            r["authority_submission_status"] = "SUBMITTED"
            r["submitted_at"] = now_iso
            submitted.append(r["id"])
    write_audit(g.user_role, g.user_id, "Student", sid, "SUBMIT_HOURS")
    return success_object({"student_id": sid, "submitted_count": len(submitted), "submitted_ids": submitted})


# ---------------------------------------------------------------------------
# INSTRUCTORS
# ---------------------------------------------------------------------------
@app.route("/instructors", methods=["POST"])
def create_instructor():
    extract_auth()
    require_roles({"Admin"})
    body = get_body()
    required(body, "full_name", "license_number")
    if "vehicle_qualifications" not in body or body["vehicle_qualifications"] is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "vehicle_qualifications is required")
    vq = body["vehicle_qualifications"]
    if not isinstance(vq, list):
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "vehicle_qualifications must be an array")
    for v in vq:
        if v not in C.VEHICLE_TYPES:
            raise E.APIError(E.ERR_INVALID_REQUEST, 400, f"Unknown vehicle_type: {v}")
    instructor = {
        "full_name": body["full_name"],
        "license_number": body["license_number"],
        "vehicle_qualifications": list(vq),
        "status": "ACTIVE",
    }
    init_common(instructor)
    DATA.instructors[instructor["id"]] = instructor
    write_audit(g.user_role, g.user_id, "Instructor", instructor["id"], "CREATE")
    return success_object(serialize_instructor(instructor), 201)


@app.route("/instructors/<iid>", methods=["GET"])
def get_instructor_route(iid):
    extract_auth()
    require_roles({"Admin", "Instructor"})
    inst = get_instructor(iid)
    if g.user_role == "Instructor" and g.user_id != iid:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    return success_object(serialize_instructor(inst))


@app.route("/instructors/<iid>/suspend", methods=["POST"])
def suspend_instructor(iid):
    extract_auth()
    require_roles({"Admin"})
    inst = get_instructor(iid)
    body = get_body()
    occ_check(inst, body)
    if inst["status"] != "ACTIVE":
        raise E.APIError(E.ERR_INSTRUCTOR_NOT_ACTIVE, 409, "Instructor is not ACTIVE")
    inst["status"] = "SUSPENDED"
    bump(inst)
    write_audit(g.user_role, g.user_id, "Instructor", inst["id"], "UPDATE")
    return success_object(serialize_instructor(inst))


@app.route("/instructors/<iid>/reinstate", methods=["POST"])
def reinstate_instructor(iid):
    extract_auth()
    require_roles({"Admin"})
    inst = get_instructor(iid)
    body = get_body()
    occ_check(inst, body)
    if inst["status"] != "SUSPENDED":
        raise E.APIError(E.ERR_INSTRUCTOR_NOT_ACTIVE, 409, "Instructor is not SUSPENDED")
    inst["status"] = "ACTIVE"
    bump(inst)
    write_audit(g.user_role, g.user_id, "Instructor", inst["id"], "UPDATE")
    return success_object(serialize_instructor(inst))


# ---------------------------------------------------------------------------
# VEHICLES
# ---------------------------------------------------------------------------
@app.route("/vehicles", methods=["POST"])
def create_vehicle():
    extract_auth()
    require_roles({"Admin"})
    body = get_body()
    required(body, "plate_number", "vehicle_type")
    if body["vehicle_type"] not in C.VEHICLE_TYPES:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Unknown vehicle_type")
    vehicle = {
        "plate_number": body["plate_number"],
        "vehicle_type": body["vehicle_type"],
        "status": "ACTIVE",
    }
    init_common(vehicle)
    DATA.vehicles[vehicle["id"]] = vehicle
    write_audit(g.user_role, g.user_id, "Vehicle", vehicle["id"], "CREATE")
    return success_object(vehicle, 201)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle_route(vid):
    extract_auth()
    require_roles({"Admin"})
    vehicle = get_vehicle(vid)
    return success_object(vehicle)


@app.route("/vehicles/<vid>/set-maintenance", methods=["POST"])
def set_vehicle_maintenance(vid):
    extract_auth()
    require_roles({"Admin"})
    vehicle = get_vehicle(vid)
    body = get_body()
    occ_check(vehicle, body)
    if vehicle["status"] != "ACTIVE":
        raise E.APIError(E.ERR_VEHICLE_NOT_ACTIVE, 409, "Vehicle is not ACTIVE")
    vehicle["status"] = "MAINTENANCE"
    bump(vehicle)
    write_audit(g.user_role, g.user_id, "Vehicle", vehicle["id"], "UPDATE")
    return success_object(vehicle)


@app.route("/vehicles/<vid>/restore-active", methods=["POST"])
def restore_vehicle_active(vid):
    extract_auth()
    require_roles({"Admin"})
    vehicle = get_vehicle(vid)
    body = get_body()
    occ_check(vehicle, body)
    if vehicle["status"] != "MAINTENANCE":
        raise E.APIError(E.ERR_VEHICLE_NOT_ACTIVE, 409, "Vehicle is not in MAINTENANCE")
    vehicle["status"] = "ACTIVE"
    bump(vehicle)
    write_audit(g.user_role, g.user_id, "Vehicle", vehicle["id"], "UPDATE")
    return success_object(vehicle)


# ---------------------------------------------------------------------------
# COURSE PACKAGES
# ---------------------------------------------------------------------------
@app.route("/course-packages", methods=["POST"])
def create_package():
    extract_auth()
    require_roles({"Admin"})
    body = get_body()
    required(body, "name", "total_minutes", "total_price_cents",
             "included_simulator_sessions", "included_exam_attempts",
             "per_minute_overage_price_cents", "per_simulator_session_overage_price_cents")
    pkg = {
        "name": body["name"],
        "total_minutes": int(body["total_minutes"]),
        "total_price_cents": int(body["total_price_cents"]),
        "included_simulator_sessions": int(body["included_simulator_sessions"]),
        "included_exam_attempts": int(body["included_exam_attempts"]),
        "per_minute_overage_price_cents": int(body["per_minute_overage_price_cents"]),
        "per_simulator_session_overage_price_cents": int(body["per_simulator_session_overage_price_cents"]),
    }
    init_immutable(pkg)
    DATA.course_packages[pkg["id"]] = pkg
    return success_object(pkg, 201)


@app.route("/course-packages/<pid>", methods=["GET"])
def get_package_route(pid):
    extract_auth()
    require_roles({"Admin", "Student"})
    pkg = get_package(pid)
    return success_object(pkg)


# ---------------------------------------------------------------------------
# PRACTICE APPOINTMENTS
# ---------------------------------------------------------------------------
def _practice_minutes(start_iso, end_iso):
    a = parse_iso(start_iso)
    b = parse_iso(end_iso)
    if a is None or b is None or b <= a:
        return None
    seconds = int((b - a).total_seconds())
    return seconds // 60


def _validate_practice_booking_inputs(body):
    required(body, "student_id", "instructor_id", "vehicle_id",
             "training_stage", "scheduled_start_at", "scheduled_end_at")
    if body["training_stage"] not in C.PRACTICE_STAGES:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid training_stage")
    s = parse_iso(body["scheduled_start_at"])
    e = parse_iso(body["scheduled_end_at"])
    if s is None or e is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid scheduled times")
    if e <= s:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "scheduled_end_at must be after scheduled_start_at")


def _create_practice_internal(body, actor_role, actor_id, reschedule_of_id=None, audit_create_action="CREATE"):
    """Apply the full booking validation cascade and persist a new BOOKED practice.
    Returns the new appointment.
    Validation priority (per PRD §2.8):
      4. Ownership (Student role)
      4.5 Body FK existence (student/instructor/vehicle)
      5. State (student ACTIVE, instructor ACTIVE, vehicle ACTIVE)
      6. Referential (training_stage match, qualification, vehicle type vs stage)
      7. Temporal (instructor / vehicle calendar)
      8. Safety (daily, weekly, rest-day)
      9. Constraint (reschedule limit — handled by caller for reschedule path)
      10. Fiscal (package balance)
    """
    # --- ownership (Student): must book for self
    if actor_role == "Student" and body["student_id"] != actor_id:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)

    student = get_student(body["student_id"])
    instructor = get_instructor(body["instructor_id"])
    vehicle = get_vehicle(body["vehicle_id"])

    # --- state checks
    if student["enrollment_status"] != "ACTIVE":
        raise E.APIError(E.ERR_STUDENT_NOT_ACTIVE, 409, "Student is not ACTIVE")
    if instructor["status"] != "ACTIVE":
        raise E.APIError(E.ERR_INSTRUCTOR_NOT_ACTIVE, 409, "Instructor is not ACTIVE")
    if vehicle["status"] != "ACTIVE":
        raise E.APIError(E.ERR_VEHICLE_NOT_ACTIVE, 409, "Vehicle is not ACTIVE")

    # --- referential: training_stage match
    if body["training_stage"] != student["training_stage"]:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400,
                         "training_stage in body does not match student.training_stage")
    # instructor qualified for vehicle's type
    if vehicle["vehicle_type"] not in instructor["vehicle_qualifications"]:
        raise E.APIError(E.ERR_INSTRUCTOR_NOT_QUALIFIED, 400,
                         "Instructor not qualified for this vehicle's type")
    # vehicle type compatible with student's stage
    if student["training_stage"] == "THEORY" and vehicle["vehicle_type"] in C.THEORY_FORBIDDEN_VEHICLE_TYPES:
        raise E.APIError(E.ERR_VEHICLE_TYPE_MISMATCH, 400,
                         "Vehicle type incompatible with student's training_stage")

    start_iso = body["scheduled_start_at"]
    end_iso = body["scheduled_end_at"]
    minutes = _practice_minutes(start_iso, end_iso)
    if minutes is None or minutes <= 0:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid scheduled times")

    # --- temporal: instructor then vehicle
    if instructor_calendar_conflict(instructor["id"], start_iso, end_iso):
        raise E.APIError(E.ERR_INSTRUCTOR_TIME_CONFLICT, 409, "Instructor calendar conflict")
    if vehicle_calendar_conflict(vehicle["id"], start_iso, end_iso):
        raise E.APIError(E.ERR_VEHICLE_TIME_CONFLICT, 409, "Vehicle calendar conflict (or buffer)")

    # --- safety: daily, weekly, rest-day
    proposed_start_dt = parse_iso(start_iso)
    today_existing = working_minutes_today(instructor)
    if today_existing + minutes > C.INSTRUCTOR_DAILY_LIMIT_MINUTES:
        raise E.APIError(E.ERR_INSTRUCTOR_DAILY_LIMIT_EXCEEDED, 403,
                         "Instructor daily working-minutes limit exceeded")
    week_existing = working_minutes_this_week(instructor)
    if week_existing + minutes > C.INSTRUCTOR_WEEKLY_LIMIT_MINUTES:
        raise E.APIError(E.ERR_INSTRUCTOR_WEEKLY_LIMIT_EXCEEDED, 403,
                         "Instructor weekly working-minutes limit exceeded")
    # Rest day rule (uses proposed booking's ISO week, not clock_now's)
    distinct_dates = distinct_working_dates_in_week_after(instructor["id"], start_iso, end_iso)
    if distinct_dates >= 7:
        raise E.APIError(E.ERR_INSTRUCTOR_NEEDS_REST, 403,
                         "Instructor would have no rest day in this ISO week")

    # --- fiscal: package balance gate
    pkg = package_for_student(student)
    if pkg is None:
        raise E.APIError(E.ERR_INSUFFICIENT_PACKAGE_BALANCE, 402, "Student has no package")
    used_provisional = sum(
        p["scheduled_minutes"] for p in DATA.practice_appointments.values()
        if p["student_id"] == student["id"]
        and p["status"] in ("BOOKED", "IN_PROGRESS", "COMPLETED")
    )
    remaining = pkg["total_minutes"] - used_provisional
    if remaining - minutes < 0:
        raise E.APIError(E.ERR_INSUFFICIENT_PACKAGE_BALANCE, 402,
                         "Practice booking would draw the package below zero")

    # All gates passed — persist
    appt = {
        "student_id": student["id"],
        "instructor_id": instructor["id"],
        "vehicle_id": vehicle["id"],
        "vehicle_type": vehicle["vehicle_type"],
        "training_stage": body["training_stage"],
        "scheduled_start_at": start_iso,
        "scheduled_end_at": end_iso,
        "scheduled_minutes": minutes,
        "status": "BOOKED",
        "reschedule_of_id": reschedule_of_id,
        "cancelled_at": None,
        "cancellation_actor_role": None,
        "check_in_at": None,
        "check_out_at": None,
        "gps_track_distance_km": None,
        "gps_validated": None,
        "recorded_minutes": 0,
        "late_cancellation_fee_cents": 0,
        "no_show_fee_cents": 0,
    }
    init_common(appt)
    DATA.practice_appointments[appt["id"]] = appt
    write_audit(actor_role, actor_id, "PracticeAppointment", appt["id"], audit_create_action)
    if reschedule_of_id is not None:
        write_audit(actor_role, actor_id, "PracticeAppointment", appt["id"], "RESCHEDULE")
    return appt


def _serialize_practice(appt):
    return dict(appt)


def _can_view_practice(appt):
    """Returns True if the current g.user_role/g.user_id is allowed to view appt."""
    if g.user_role == "Admin":
        return True
    if g.user_role == "Student":
        return appt["student_id"] == g.user_id
    if g.user_role == "Instructor":
        return appt["instructor_id"] == g.user_id
    return False


@app.route("/practice-appointments", methods=["POST"])
def create_practice():
    extract_auth()
    require_roles({"Admin", "Student"})
    body = get_body()
    _validate_practice_booking_inputs(body)
    # If reschedule_of_id is provided directly here (atypical but allowed by scaffold),
    # we still treat this path as a plain CREATE; reschedule path uses the dedicated endpoint
    # which both cancels and creates atomically.
    if body.get("reschedule_of_id"):
        # treat as dedicated reschedule path
        prior = DATA.practice_appointments.get(body["reschedule_of_id"])
        if prior is None:
            raise E.APIError(E.ERR_PRACTICE_NOT_FOUND, 404)
        # Note: atomic cancel-and-create is the dedicated endpoint;
        # here we accept reschedule_of_id only as a tag (must reference a CANCELLED row).
        if prior["status"] != "CANCELLED":
            raise E.APIError(E.ERR_INVALID_REQUEST, 400,
                             "reschedule_of_id must reference a CANCELLED appointment")
    appt = _create_practice_internal(
        body=body,
        actor_role=g.user_role,
        actor_id=g.user_id,
        reschedule_of_id=body.get("reschedule_of_id"),
        audit_create_action="CREATE",
    )
    return success_object(_serialize_practice(appt), 201)


@app.route("/practice-appointments/<pid>", methods=["GET"])
def get_practice_route(pid):
    extract_auth()
    require_roles({"Admin", "Student", "Instructor"})
    appt = get_practice(pid)
    if not _can_view_practice(appt):
        if g.user_role == "Student":
            raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
        if g.user_role == "Instructor":
            raise E.APIError(E.ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR, 403)
        raise E.APIError(E.ERR_INSUFFICIENT_PERMISSIONS, 403)
    return success_object(_serialize_practice(appt))


def _compute_late_cancellation_fee(appt, package):
    """Per scaffold/PRD §3.4. Returns integer cents floor."""
    sched_start = parse_iso(appt["scheduled_start_at"])
    delta_seconds = (sched_start - CLOCK.now()).total_seconds()
    delta_hours = delta_seconds / 3600.0
    base = appt["scheduled_minutes"] * package["per_minute_overage_price_cents"]
    if delta_hours <= 0:
        tier_pct = 100
    elif delta_hours < 2:
        tier_pct = 100
    elif delta_hours < 24:
        tier_pct = 50
    else:
        tier_pct = 0
    return math.floor(base * tier_pct / 100)


@app.route("/practice-appointments/<pid>/cancel", methods=["POST"])
def cancel_practice(pid):
    extract_auth()
    require_roles({"Admin", "Student"})
    appt = get_practice(pid)
    body = get_body()
    occ_check(appt, body)
    # Ownership for Student
    if g.user_role == "Student" and g.user_id != appt["student_id"]:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    if appt["status"] != "BOOKED":
        raise E.APIError(E.ERR_APPOINTMENT_NOT_CANCELLABLE, 409,
                         "PracticeAppointment is not BOOKED")
    student = DATA.students.get(appt["student_id"])
    pkg = package_for_student(student) if student else None
    fee = 0
    if pkg is not None:
        fee = _compute_late_cancellation_fee(appt, pkg)
    appt["status"] = "CANCELLED"
    appt["cancelled_at"] = CLOCK.iso()
    appt["cancellation_actor_role"] = g.user_role
    appt["late_cancellation_fee_cents"] = fee
    bump(appt)
    write_audit(g.user_role, g.user_id, "PracticeAppointment", appt["id"], "CANCEL")
    return success_object(_serialize_practice(appt))


@app.route("/practice-appointments/<pid>/check-in", methods=["POST"])
def check_in_practice(pid):
    extract_auth()
    require_roles({"Instructor", "Admin"})
    appt = get_practice(pid)
    body = get_body()
    occ_check(appt, body)
    # Ownership: Instructor
    if g.user_role == "Instructor" and g.user_id != appt["instructor_id"]:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR, 403)
    if appt["status"] != "BOOKED":
        raise E.APIError(E.ERR_APPOINTMENT_NOT_CHECK_INNABLE, 409,
                         "PracticeAppointment is not BOOKED")
    # Vehicle still ACTIVE?
    vehicle = DATA.vehicles.get(appt["vehicle_id"])
    if vehicle is None or vehicle["status"] != "ACTIVE":
        raise E.APIError(E.ERR_VEHICLE_NOT_ACTIVE, 409, "Vehicle is no longer ACTIVE")
    # Check-in window
    sched_start = parse_iso(appt["scheduled_start_at"])
    sched_end = parse_iso(appt["scheduled_end_at"])
    now = CLOCK.now()
    if not (now >= sched_start - timedelta(minutes=C.CHECK_IN_LEAD_MINUTES) and now < sched_end):
        raise E.APIError(E.ERR_OUTSIDE_CHECK_IN_WINDOW, 409,
                         "Check-in attempted outside the allowed window")
    appt["status"] = "IN_PROGRESS"
    appt["check_in_at"] = CLOCK.iso()
    bump(appt)
    write_audit(g.user_role, g.user_id, "PracticeAppointment", appt["id"], "CHECK_IN")
    return success_object(_serialize_practice(appt))


@app.route("/practice-appointments/<pid>/check-out", methods=["POST"])
def check_out_practice(pid):
    extract_auth()
    require_roles({"Instructor", "Admin"})
    appt = get_practice(pid)
    body = get_body()
    occ_check(appt, body)
    if g.user_role == "Instructor" and g.user_id != appt["instructor_id"]:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR, 403)
    if appt["status"] != "IN_PROGRESS":
        raise E.APIError(E.ERR_APPOINTMENT_NOT_CHECK_OUTTABLE, 409,
                         "PracticeAppointment is not IN_PROGRESS")
    if "gps_track_distance_km" not in body or body["gps_track_distance_km"] is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "gps_track_distance_km is required")
    try:
        gps_km = Decimal(str(body["gps_track_distance_km"]))
    except Exception:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "gps_track_distance_km must be a number")
    if gps_km < 0:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "gps_track_distance_km must be >= 0")
    validated = gps_km >= C.MIN_DRIVING_KM
    appt["status"] = "COMPLETED"
    appt["check_out_at"] = CLOCK.iso()
    appt["gps_track_distance_km"] = float(gps_km)
    appt["gps_validated"] = bool(validated)
    appt["recorded_minutes"] = appt["scheduled_minutes"] if validated else 0
    bump(appt)
    # Append TrainingHourRecord
    rec = {
        "student_id": appt["student_id"],
        "source_appointment_id": appt["id"],
        "training_stage": appt["training_stage"],
        "minutes_recorded": appt["recorded_minutes"],
        "gps_validated": appt["gps_validated"],
        "authority_submission_status": "PENDING",
        "submitted_at": None,
    }
    init_immutable(rec)
    DATA.training_hour_records[rec["id"]] = rec
    write_audit(g.user_role, g.user_id, "PracticeAppointment", appt["id"], "CHECK_OUT")
    return success_object(_serialize_practice(appt))


@app.route("/practice-appointments/<pid>/reschedule", methods=["POST"])
def reschedule_practice(pid):
    extract_auth()
    require_roles({"Admin", "Student"})
    appt = get_practice(pid)
    body = get_body()
    occ_check(appt, body)
    # Ownership for Student
    if g.user_role == "Student" and g.user_id != appt["student_id"]:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    if appt["status"] != "BOOKED":
        raise E.APIError(E.ERR_APPOINTMENT_NOT_CANCELLABLE, 409,
                         "PracticeAppointment is not BOOKED")
    required(body, "new_scheduled_start_at", "new_scheduled_end_at")
    new_start = parse_iso(body["new_scheduled_start_at"])
    new_end = parse_iso(body["new_scheduled_end_at"])
    if new_start is None or new_end is None or new_end <= new_start:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid new scheduled times")
    new_instructor_id = body.get("new_instructor_id") or appt["instructor_id"]
    new_vehicle_id = body.get("new_vehicle_id") or appt["vehicle_id"]

    # --- Reschedule limit check (cycle counter)
    student = DATA.students.get(appt["student_id"])
    if student is None:
        raise E.APIError(E.ERR_STUDENT_NOT_FOUND, 404)
    rcount = reschedule_count_this_cycle(student)
    if rcount >= C.RESCHEDULE_LIMIT_PER_CYCLE:
        raise E.APIError(E.ERR_RESCHEDULE_LIMIT_EXCEEDED, 409,
                         "Reschedule limit per cycle reached")

    # Snapshot for rollback in case the new-booking gates fail
    snapshot = {
        "status": appt["status"],
        "cancelled_at": appt["cancelled_at"],
        "cancellation_actor_role": appt["cancellation_actor_role"],
        "late_cancellation_fee_cents": appt["late_cancellation_fee_cents"],
        "version": appt["version"],
        "updated_at": appt["updated_at"],
    }

    # Cancel half (no fee per PRD §3.4)
    appt["status"] = "CANCELLED"
    appt["cancelled_at"] = CLOCK.iso()
    appt["cancellation_actor_role"] = g.user_role
    appt["late_cancellation_fee_cents"] = 0
    bump(appt)
    cancel_audit = write_audit(g.user_role, g.user_id, "PracticeAppointment", appt["id"], "CANCEL")

    new_body = {
        "student_id": appt["student_id"],
        "instructor_id": new_instructor_id,
        "vehicle_id": new_vehicle_id,
        "training_stage": appt["training_stage"],
        "scheduled_start_at": body["new_scheduled_start_at"],
        "scheduled_end_at": body["new_scheduled_end_at"],
    }
    try:
        new_appt = _create_practice_internal(
            body=new_body,
            actor_role=g.user_role,
            actor_id=g.user_id,
            reschedule_of_id=appt["id"],
            audit_create_action="CREATE",
        )
    except E.APIError:
        # Restore the original record exactly
        for k, v in snapshot.items():
            appt[k] = v
        DATA.audit_logs.pop(cancel_audit["id"], None)
        raise
    return success_object(_serialize_practice(new_appt), 201)


# ---------------------------------------------------------------------------
# EXAM APPOINTMENTS
# ---------------------------------------------------------------------------
def _retake_count(student_id, exam_type):
    """Count student's prior exam appointments of same type in any non-fresh state."""
    return sum(
        1 for e in DATA.exam_appointments.values()
        if e["student_id"] == student_id
        and e["exam_type"] == exam_type
        and e["status"] in ("BOOKED", "PASSED", "FAILED", "NO_SHOW", "CANCELLED")
    )


def _attested_minutes(student_id, attested_stage):
    return sum(
        r["minutes_recorded"] for r in DATA.training_hour_records.values()
        if r["student_id"] == student_id
        and r["training_stage"] == attested_stage
        and r.get("gps_validated") is True
    )


def _serialize_exam(exam):
    return dict(exam)


def _can_view_exam(exam):
    if g.user_role == "Admin":
        return True
    if g.user_role == "Examiner":
        return True
    if g.user_role == "Student":
        return exam["student_id"] == g.user_id
    return False


@app.route("/exam-appointments", methods=["POST"])
def create_exam():
    extract_auth()
    require_roles({"Admin"})
    body = get_body()
    required(body, "student_id", "exam_type", "scheduled_at", "examiner_id")
    if body["exam_type"] not in C.EXAM_TYPES:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid exam_type")
    student = get_student(body["student_id"])
    sched_at = parse_iso(body["scheduled_at"])
    if sched_at is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "scheduled_at must be valid ISO 8601")

    # State (priority 5): student must be ACTIVE
    if student["enrollment_status"] != "ACTIVE":
        raise E.APIError(E.ERR_STUDENT_NOT_ACTIVE, 409, "Student is not ACTIVE")

    # Referential (priority 6): prerequisite stage
    prereq = C.PREREQUISITE_STAGE[body["exam_type"]]
    if student["training_stage"] != prereq:
        raise E.APIError(E.ERR_PREREQUISITE_STAGE_NOT_MET, 400,
                         f"Student's training_stage must be {prereq}")
    if body["exam_type"] == "FINAL_TEST" and not has_passed_basic_practical(student):
        raise E.APIError(E.ERR_PREREQUISITE_STAGE_NOT_MET, 400,
                         "FINAL_TEST requires has_passed_basic_practical=true")

    # Constraint (priority 9): retake limit, stage min hours
    prior_count = _retake_count(student["id"], body["exam_type"])
    if prior_count >= C.RETAKE_LIMIT:
        raise E.APIError(E.ERR_RETAKE_LIMIT_EXCEEDED, 409,
                         "Exam retake limit reached for this exam_type")
    attested_stage = C.ATTESTED_STAGE[body["exam_type"]]
    required_minutes = C.REQUIRED_MINUTES_BY_STAGE[attested_stage]
    if _attested_minutes(student["id"], attested_stage) < required_minutes:
        raise E.APIError(E.ERR_STAGE_MIN_HOURS_NOT_MET, 409,
                         f"Required {required_minutes} validated minutes for stage {attested_stage}")

    # Fiscal (priority 10): exam attempts remaining
    if exam_attempts_remaining(student) is not None and exam_attempts_remaining(student) <= 0:
        raise E.APIError(E.ERR_NO_EXAM_ATTEMPTS_REMAINING, 402,
                         "No exam attempts remaining")

    retake_index = prior_count + 1
    exam = {
        "student_id": student["id"],
        "exam_type": body["exam_type"],
        "scheduled_at": body["scheduled_at"],
        "examiner_id": body["examiner_id"],
        "status": "BOOKED",
        "score": None,
        "passing_score": C.PASSING_SCORES[body["exam_type"]],
        "retake_index": retake_index,
        "prerequisite_stage": prereq,
    }
    init_common(exam)
    DATA.exam_appointments[exam["id"]] = exam
    write_audit(g.user_role, g.user_id, "ExamAppointment", exam["id"], "CREATE")
    return success_object(_serialize_exam(exam), 201)


@app.route("/exam-appointments/<eid>", methods=["GET"])
def get_exam_route(eid):
    extract_auth()
    require_roles({"Admin", "Student", "Examiner"})
    exam = get_exam(eid)
    if not _can_view_exam(exam):
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    return success_object(_serialize_exam(exam))


@app.route("/exam-appointments/<eid>/record-result", methods=["POST"])
def record_exam_result(eid):
    extract_auth()
    require_roles({"Examiner"})
    exam = get_exam(eid)
    body = get_body()
    occ_check(exam, body)
    if exam["status"] != "BOOKED":
        raise E.APIError(E.ERR_EXAM_NOT_BOOKABLE, 409, "Exam is not BOOKED")
    if "score" not in body or body["score"] is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "score is required")
    try:
        score = int(body["score"])
    except (TypeError, ValueError):
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "score must be an integer")
    if score < 0 or score > 100:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "score must be between 0 and 100")
    exam["score"] = score
    if score >= exam["passing_score"]:
        exam["status"] = "PASSED"
        bump(exam)
        # Cascade onto student
        student = DATA.students.get(exam["student_id"])
        if student is not None:
            if exam["exam_type"] == "THEORY_TEST" and student["training_stage"] == "THEORY":
                student["training_stage"] = "BASIC"
                bump(student)
            elif exam["exam_type"] == "BASIC_TEST" and student["training_stage"] == "BASIC":
                student["training_stage"] = "HIGHWAY"
                bump(student)
            elif exam["exam_type"] == "FINAL_TEST" and student["training_stage"] == "HIGHWAY":
                student["training_stage"] = "COMPLETED"
                if student["enrollment_status"] == "ACTIVE":
                    student["enrollment_status"] = "COMPLETED"
                # Bulk submit PENDING TrainingHourRecord rows
                now_iso = CLOCK.iso()
                for r in DATA.training_hour_records.values():
                    if r["student_id"] == student["id"] and r["authority_submission_status"] == "PENDING":
                        r["authority_submission_status"] = "SUBMITTED"
                        r["submitted_at"] = now_iso
                bump(student)
    else:
        exam["status"] = "FAILED"
        bump(exam)
    write_audit(g.user_role, g.user_id, "ExamAppointment", exam["id"], "RECORD_RESULT")
    return success_object(_serialize_exam(exam))


@app.route("/exam-appointments/<eid>/cancel", methods=["POST"])
def cancel_exam(eid):
    extract_auth()
    require_roles({"Admin"})
    exam = get_exam(eid)
    body = get_body()
    occ_check(exam, body)
    if exam["status"] != "BOOKED":
        raise E.APIError(E.ERR_EXAM_NOT_BOOKABLE, 409, "Exam is not BOOKED")
    exam["status"] = "CANCELLED"
    bump(exam)
    write_audit(g.user_role, g.user_id, "ExamAppointment", exam["id"], "CANCEL")
    return success_object(_serialize_exam(exam))


# ---------------------------------------------------------------------------
# SIMULATOR SESSIONS
# ---------------------------------------------------------------------------
@app.route("/simulator-sessions", methods=["POST"])
def create_simulator():
    extract_auth()
    require_roles({"Admin", "Student"})
    body = get_body()
    required(body, "student_id", "scheduled_start_at", "scheduled_end_at")
    if g.user_role == "Student" and body["student_id"] != g.user_id:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    student = get_student(body["student_id"])
    if student["enrollment_status"] != "ACTIVE":
        raise E.APIError(E.ERR_STUDENT_NOT_ACTIVE, 409, "Student is not ACTIVE")
    s = parse_iso(body["scheduled_start_at"])
    e = parse_iso(body["scheduled_end_at"])
    if s is None or e is None or e <= s:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid scheduled times")
    pkg = package_for_student(student)
    remaining_before = simulator_sessions_remaining(student)
    if remaining_before is not None and remaining_before > 0:
        charged = True
        overage = 0
    else:
        charged = False
        overage = pkg["per_simulator_session_overage_price_cents"] if pkg else 0
    sess = {
        "student_id": student["id"],
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "status": "BOOKED",
        "charged_to_package": charged,
        "overage_cents": overage,
    }
    init_common(sess)
    DATA.simulator_sessions[sess["id"]] = sess
    write_audit(g.user_role, g.user_id, "SimulatorSession", sess["id"], "CREATE")
    return success_object(sess, 201)


@app.route("/simulator-sessions/<sid>/cancel", methods=["POST"])
def cancel_simulator(sid):
    extract_auth()
    require_roles({"Admin", "Student"})
    sess = get_simulator(sid)
    body = get_body()
    occ_check(sess, body)
    if g.user_role == "Student" and g.user_id != sess["student_id"]:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    if sess["status"] != "BOOKED":
        raise E.APIError(E.ERR_SIMULATOR_NOT_BOOKED, 409, "SimulatorSession is not BOOKED")
    sess["status"] = "CANCELLED"
    bump(sess)
    write_audit(g.user_role, g.user_id, "SimulatorSession", sess["id"], "CANCEL")
    return success_object(sess)


@app.route("/simulator-sessions/<sid>/complete", methods=["POST"])
def complete_simulator(sid):
    extract_auth()
    require_roles({"Admin"})
    sess = get_simulator(sid)
    body = get_body()
    occ_check(sess, body)
    if sess["status"] != "BOOKED":
        raise E.APIError(E.ERR_SIMULATOR_NOT_BOOKED, 409, "SimulatorSession is not BOOKED")
    sched_start = parse_iso(sess["scheduled_start_at"])
    if CLOCK.now() < sched_start:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400,
                         "Simulator session cannot be completed before scheduled_start_at")
    sess["status"] = "COMPLETED"
    bump(sess)
    write_audit(g.user_role, g.user_id, "SimulatorSession", sess["id"], "UPDATE")
    return success_object(sess)


# ---------------------------------------------------------------------------
# COMPLAINTS
# ---------------------------------------------------------------------------
def _can_view_complaint(c):
    if g.user_role == "Admin":
        return True
    if g.user_role == "ComplaintHandler":
        return True
    if g.user_role == "Student":
        return c["student_id"] == g.user_id
    return False


@app.route("/complaints", methods=["POST"])
def create_complaint():
    extract_auth()
    require_roles({"Student", "Admin"})
    body = get_body()
    required(body, "student_id", "category", "description")
    if g.user_role == "Student" and body["student_id"] != g.user_id:
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    student = get_student(body["student_id"])
    if body["category"] not in C.COMPLAINT_CATEGORIES:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid category")
    instructor_id = body.get("instructor_id")
    if body["category"] == "INSTRUCTOR_CONDUCT":
        if not instructor_id:
            raise E.APIError(E.ERR_INVALID_REQUEST, 400,
                             "instructor_id is required for INSTRUCTOR_CONDUCT")
        get_instructor(instructor_id)
    else:
        instructor_id = None
    c = {
        "student_id": student["id"],
        "instructor_id": instructor_id,
        "category": body["category"],
        "description": body["description"],
        "level": 1,
        "status": "OPEN",
        "assigned_handler_id": None,
        "assigned_handler_role": None,
        "response_text": None,
        "resolution_summary": None,
        "escalated_at": None,
        "resolved_at": None,
    }
    init_common(c)
    DATA.complaints[c["id"]] = c
    write_audit(g.user_role, g.user_id, "Complaint", c["id"], "CREATE")
    return success_object(c, 201)


@app.route("/complaints/<cid>", methods=["GET"])
def get_complaint_route(cid):
    extract_auth()
    require_roles({"Admin", "Student", "ComplaintHandler"})
    c = get_complaint(cid)
    if not _can_view_complaint(c):
        raise E.APIError(E.ERR_FORBIDDEN_NOT_OWNER, 403)
    return success_object(c)


@app.route("/complaints/<cid>/assign-handler", methods=["POST"])
def assign_complaint_handler(cid):
    extract_auth()
    require_roles({"Admin"})
    c = get_complaint(cid)
    body = get_body()
    occ_check(c, body)
    if c["status"] not in ("OPEN", "ESCALATED"):
        raise E.APIError(E.ERR_COMPLAINT_NOT_ASSIGNABLE, 409,
                         "Complaint is not in {OPEN, ESCALATED}")
    required(body, "handler_id", "handler_role")
    handler_role = body["handler_role"]
    if handler_role not in {"Admin", "ComplaintHandler"}:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Invalid handler_role")
    if c["category"] == "INSTRUCTOR_CONDUCT" and handler_role != "Admin":
        raise E.APIError(E.ERR_INSTRUCTOR_COMPLAINT_REQUIRES_ADMIN, 400,
                         "INSTRUCTOR_CONDUCT complaints require Admin handler")
    if c["level"] >= 3 and handler_role != "Admin":
        raise E.APIError(E.ERR_LEVEL3_REQUIRES_ADMIN, 400,
                         "Level-3 complaints require Admin handler")
    c["status"] = "IN_REVIEW"
    c["assigned_handler_id"] = body["handler_id"]
    c["assigned_handler_role"] = handler_role
    bump(c)
    write_audit(g.user_role, g.user_id, "Complaint", c["id"], "ASSIGN_HANDLER")
    return success_object(c)


@app.route("/complaints/<cid>/escalate", methods=["POST"])
def escalate_complaint(cid):
    extract_auth()
    require_roles({"ComplaintHandler", "Admin"})
    c = get_complaint(cid)
    body = get_body()
    occ_check(c, body)
    # Ownership-equivalent: handler identity match
    if g.user_role == "ComplaintHandler" and g.user_id != c.get("assigned_handler_id"):
        raise E.APIError(E.ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER, 403)
    if c["status"] != "IN_REVIEW":
        raise E.APIError(E.ERR_COMPLAINT_NOT_RESOLVABLE, 409,
                         "Complaint is not IN_REVIEW")
    if c["level"] >= 3:
        raise E.APIError(E.ERR_ESCALATION_LIMIT_REACHED, 409,
                         "Complaint already at maximum escalation level")
    # Admin escalation also needs to know who they are escalating; PRD says Admin or
    # ComplaintHandler may escalate. For Admin we don't compare identity (Admin opaque).
    c["level"] += 1
    c["status"] = "ESCALATED"
    c["escalated_at"] = CLOCK.iso()
    c["assigned_handler_id"] = None
    c["assigned_handler_role"] = None
    bump(c)
    write_audit(g.user_role, g.user_id, "Complaint", c["id"], "ESCALATE")
    return success_object(c)


@app.route("/complaints/<cid>/resolve", methods=["POST"])
def resolve_complaint(cid):
    extract_auth()
    require_roles({"ComplaintHandler", "Admin"})
    c = get_complaint(cid)
    body = get_body()
    occ_check(c, body)
    if g.user_role == "ComplaintHandler" and g.user_id != c.get("assigned_handler_id"):
        raise E.APIError(E.ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER, 403)
    if c["status"] != "IN_REVIEW":
        raise E.APIError(E.ERR_COMPLAINT_NOT_RESOLVABLE, 409,
                         "Complaint is not IN_REVIEW")
    required(body, "response_text", "resolution_summary")
    c["response_text"] = body["response_text"]
    c["resolution_summary"] = body["resolution_summary"]
    c["status"] = "RESOLVED"
    c["resolved_at"] = CLOCK.iso()
    bump(c)
    write_audit(g.user_role, g.user_id, "Complaint", c["id"], "RESOLVE")
    return success_object(c)


@app.route("/complaints/<cid>/reject", methods=["POST"])
def reject_complaint(cid):
    extract_auth()
    require_roles({"ComplaintHandler", "Admin"})
    c = get_complaint(cid)
    body = get_body()
    occ_check(c, body)
    if g.user_role == "ComplaintHandler" and g.user_id != c.get("assigned_handler_id"):
        raise E.APIError(E.ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER, 403)
    if c["status"] != "IN_REVIEW":
        raise E.APIError(E.ERR_COMPLAINT_NOT_RESOLVABLE, 409,
                         "Complaint is not IN_REVIEW")
    required(body, "response_text")
    c["response_text"] = body["response_text"]
    c["status"] = "REJECTED"
    c["resolved_at"] = CLOCK.iso()
    bump(c)
    write_audit(g.user_role, g.user_id, "Complaint", c["id"], "REJECT")
    return success_object(c)


# ---------------------------------------------------------------------------
# AUDIT LOGS
# ---------------------------------------------------------------------------
@app.route("/audit-logs", methods=["GET"])
def list_audit_logs():
    extract_auth()
    require_roles({"Admin"})
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    limit, offset = parse_pagination()
    rows = list(DATA.audit_logs.values())
    if entity_type is not None:
        rows = [r for r in rows if r["entity_type"] == entity_type]
    if entity_id is not None:
        rows = [r for r in rows if r["entity_id"] == entity_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    sliced = rows[offset: offset + limit]
    return success_array(sliced, limit, offset, total)


# ---------------------------------------------------------------------------
# CLOCK + SWEEP
# ---------------------------------------------------------------------------
@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    extract_auth()
    require_roles({"Admin"})
    body = get_body()
    required_present(body, "minutes")
    try:
        minutes = int(body["minutes"])
    except (TypeError, ValueError):
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "minutes must be an integer")
    CLOCK.advance_minutes(minutes)
    return success_object({"clock_now": CLOCK.iso(), "advanced_minutes": minutes})


def _sweep_practice_no_show(actor_role, actor_id):
    """Transition expired BOOKED practice appointments to NO_SHOW.
    Returns list of appointments transitioned."""
    transitioned = []
    now = CLOCK.now()
    for p in list(DATA.practice_appointments.values()):
        if p["status"] != "BOOKED":
            continue
        sched_end = parse_iso(p["scheduled_end_at"])
        if sched_end is None:
            continue
        if sched_end + timedelta(minutes=C.NO_SHOW_GRACE_MINUTES) < now:
            student = DATA.students.get(p["student_id"])
            pkg = package_for_student(student) if student else None
            base = p["scheduled_minutes"] * (pkg["per_minute_overage_price_cents"] if pkg else 0)
            p["status"] = "NO_SHOW"
            p["no_show_fee_cents"] = base
            bump(p)
            write_audit(actor_role, actor_id, "PracticeAppointment", p["id"], "NO_SHOW_SWEEP")
            transitioned.append(p)
    # Cascade: if any student has reached the no-show threshold this cycle, suspend
    for p in transitioned:
        student = DATA.students.get(p["student_id"])
        if student is None:
            continue
        if student["enrollment_status"] != "ACTIVE":
            continue
        cnt = no_show_count_this_cycle(student)
        if cnt >= C.NO_SHOW_THRESHOLD_PER_CYCLE:
            student["enrollment_status"] = "SUSPENDED"
            student["suspension_reason"] = "NO_SHOW_THRESHOLD_BREACH"
            bump(student)
            write_audit("system", "system", "Student", student["id"], "UPDATE")
            # Cascade: auto-cancel future BOOKED practices for this student
            for q in DATA.practice_appointments.values():
                if q["student_id"] != student["id"]:
                    continue
                if q["status"] != "BOOKED":
                    continue
                q["status"] = "CANCELLED"
                q["cancelled_at"] = CLOCK.iso()
                q["cancellation_actor_role"] = "system"
                q["late_cancellation_fee_cents"] = 0
                bump(q)
                write_audit("system", "system", "PracticeAppointment", q["id"], "CANCEL")


def _sweep_exam_no_show(actor_role, actor_id):
    now = CLOCK.now()
    for e in DATA.exam_appointments.values():
        if e["status"] != "BOOKED":
            continue
        sched_at = parse_iso(e["scheduled_at"])
        if sched_at is None:
            continue
        deadline = sched_at + timedelta(minutes=C.EXAM_DURATION_MINUTES + C.NO_SHOW_GRACE_MINUTES)
        if deadline < now:
            e["status"] = "NO_SHOW"
            bump(e)
            write_audit(actor_role, actor_id, "ExamAppointment", e["id"], "NO_SHOW_SWEEP")


def _sweep_simulator_no_show(actor_role, actor_id):
    now = CLOCK.now()
    for s in DATA.simulator_sessions.values():
        if s["status"] != "BOOKED":
            continue
        sched_end = parse_iso(s["scheduled_end_at"])
        if sched_end is None:
            continue
        if sched_end + timedelta(minutes=C.NO_SHOW_GRACE_MINUTES) < now:
            s["status"] = "NO_SHOW"
            bump(s)
            write_audit(actor_role, actor_id, "SimulatorSession", s["id"], "NO_SHOW_SWEEP")


def _sweep_cycle_reset(actor_role, actor_id):
    now_date = CLOCK.now().date()
    now_iso = CLOCK.iso()
    for student in DATA.students.values():
        if student["enrollment_status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        cycle_start_iso = student.get("cycle_start_date")
        if cycle_start_iso is None:
            continue
        cycle_dt = parse_iso(cycle_start_iso)
        if cycle_dt is None:
            continue
        days_elapsed = (now_date - cycle_dt.date()).days
        if days_elapsed >= C.CYCLE_DAYS:
            student["cycle_start_date"] = now_iso
            bump(student)
            write_audit(actor_role, actor_id, "Student", student["id"], "UPDATE")


@app.route("/_sweep/run", methods=["POST"])
def sweep_run():
    extract_auth()
    require_roles({"Admin"})
    actor_role = g.user_role
    actor_id = g.user_id
    _sweep_practice_no_show(actor_role, actor_id)
    _sweep_exam_no_show(actor_role, actor_id)
    _sweep_simulator_no_show(actor_role, actor_id)
    _sweep_cycle_reset(actor_role, actor_id)
    return success_object({"clock_now": CLOCK.iso()})


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def root():
    return success_object({"service": "driving-school-api", "clock_now": CLOCK.iso()})


@app.route("/healthz", methods=["GET"])
def healthz():
    return success_object({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)
