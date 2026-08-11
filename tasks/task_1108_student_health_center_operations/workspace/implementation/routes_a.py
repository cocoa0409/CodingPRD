"""Routes part A: logical clock, students, insurance policies, immunization
requirements/records/doses/exemptions, providers, on-call shifts,
appointments."""
from datetime import timedelta

from flask import Blueprint

from store import db, clock, new_entity, bump
from helpers import (
    ApiError, require_auth, get_body, envelope_ok, list_response,
    req_present, req_string, req_int, req_enum, err_invalid_request,
    err_not_found, parse_dt, parse_date, fmt_dt, is_int,
)
from serializers import (
    ser_student, ser_policy, ser_requirement, ser_record, ser_provider,
    ser_shift, ser_appointment, ser_encounter,
)
import services
from services import (
    run_sweep, recompute_posture, cancel_future_electives,
    transition_record_overdue, triage_count, slot_conflict,
    ELECTIVE_VISIT_TYPES,
)

bp_a = Blueprint("routes_a", __name__)

ENROLLMENT_STATUSES = {"ENROLLED", "LEAVE", "WITHDRAWN"}
PAYER_TYPES = {"STUDENT_PLAN", "EXTERNAL"}
VISIT_TYPES = {"PRIMARY_URGENT", "SAME_DAY_TRIAGE", "FOLLOW_UP",
               "SPORTS_PHYSICAL", "TRAVEL_CLINIC"}
PROVIDER_TYPES = {"CLINICIAN", "NURSE"}


def get_or_404(table, entity_id):
    e = db[table].get(entity_id)
    if e is None:
        raise err_not_found("Resource not found: %s" % entity_id)
    return e


# ==========================================================================
# Logical clock
# ==========================================================================

@bp_a.route("/shc/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"HealthAdmin"})
    body = get_body()
    to = parse_dt(req_present(body, "to_iso8601"), "to_iso8601")
    clock.set(to)
    run_sweep()
    return envelope_ok({"current_utc": fmt_dt(clock.now())})


# ==========================================================================
# Students
# ==========================================================================

@bp_a.route("/shc/students", methods=["POST"])
def create_student():
    require_auth({"HealthAdmin"})
    body = get_body()
    external_ref = req_string(body, "external_ref")
    full_name = req_string(body, "full_name")
    enrollment_status = body.get("enrollment_status", "ENROLLED")
    if enrollment_status is None:
        enrollment_status = "ENROLLED"
    if enrollment_status not in ENROLLMENT_STATUSES:
        raise err_invalid_request("enrollment_status must be one of "
                                  "['ENROLLED', 'LEAVE', 'WITHDRAWN']")
    for s in db["students"].values():
        if s["external_ref"] == external_ref:
            raise ApiError("ERR_DUPLICATE_STUDENT_REF", 409,
                           "external_ref already registered")
    student = new_entity()
    student.update({
        "external_ref": external_ref,
        "full_name": full_name,
        "enrollment_status": enrollment_status,
        "compliance_posture": "CLEAR",
        "active_hold_types": [],
    })
    db["students"][student["id"]] = student
    return envelope_ok(ser_student(student), status=201)


@bp_a.route("/shc/students/<sid>", methods=["GET"])
def get_student(sid):
    require_auth()
    return envelope_ok(ser_student(get_or_404("students", sid)))


# ==========================================================================
# Insurance policies
# ==========================================================================

@bp_a.route("/shc/insurance-policies", methods=["POST"])
def create_policy():
    require_auth({"BillingOfficer"})
    body = get_body()
    student_id = req_string(body, "student_id")
    payer_type = req_enum(body, "payer_type", PAYER_TYPES)
    policy_number = req_string(body, "policy_number")
    coverage_start = parse_dt(req_present(body, "coverage_start"), "coverage_start")
    coverage_end = parse_dt(req_present(body, "coverage_end"), "coverage_end")
    copay_cents = req_int(body, "copay_cents")
    deductible_cents = req_int(body, "deductible_cents")
    coinsurance_pct = req_present(body, "coinsurance_pct")
    expected_student_version = req_int(body, "expected_student_version")
    if copay_cents < 0:
        raise err_invalid_request("copay_cents must be >= 0")
    if deductible_cents < 0:
        raise err_invalid_request("deductible_cents must be >= 0")
    if isinstance(coinsurance_pct, bool) or not isinstance(coinsurance_pct, (int, float)):
        raise err_invalid_request("coinsurance_pct must be a number")
    if not (0 <= coinsurance_pct <= 1):
        raise err_invalid_request("coinsurance_pct must be in [0, 1]")
    # Existence
    student = db["students"].get(student_id)
    if student is None:
        raise err_not_found("student_id does not reference an existing student")
    # OCC (before any business rule)
    if expected_student_version != student["version"]:
        raise ApiError("ERR_STALE_STUDENT_VERSION", 412,
                       "expected_student_version does not match Student.version")
    # Temporal
    if coverage_end <= coverage_start:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "coverage_end must be after coverage_start")
    # Supersede the student's existing UNVERIFIED/VERIFIED policy.
    for p in db["policies"].values():
        if p["student_id"] == student_id and p["status"] in ("UNVERIFIED", "VERIFIED"):
            p["status"] = "SUPERSEDED"
            bump(p)
    policy = new_entity()
    policy.update({
        "student_id": student_id,
        "payer_type": payer_type,
        "policy_number": policy_number,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "copay_cents": copay_cents,
        "deductible_cents": deductible_cents,
        "deductible_met_cents": 0,
        "coinsurance_pct": coinsurance_pct,
        "status": "UNVERIFIED",
        "verified_at": None,
    })
    db["policies"][policy["id"]] = policy
    # Policy creation is a mutation on the student aggregate.
    bump(student)
    return envelope_ok(ser_policy(policy), status=201)


@bp_a.route("/shc/insurance-policies/<pid>/verify", methods=["POST"])
def verify_policy(pid):
    require_auth({"BillingOfficer"})
    get_body()
    policy = get_or_404("policies", pid)
    if policy["status"] != "UNVERIFIED":
        raise ApiError("ERR_POLICY_NOT_UNVERIFIED", 409,
                       "verify requires status UNVERIFIED")
    now = clock.now()
    if policy["coverage_end"] < now:
        raise ApiError("ERR_POLICY_EXPIRED", 422,
                       "coverage_end has passed the current logical time")
    if policy["payer_type"] == "STUDENT_PLAN":
        student = db["students"].get(policy["student_id"])
        if student is None or student["enrollment_status"] != "ENROLLED":
            raise ApiError("ERR_POLICY_NOT_ELIGIBLE", 422,
                           "STUDENT_PLAN policy requires an ENROLLED student")
    policy["status"] = "VERIFIED"
    policy["verified_at"] = now
    bump(policy)
    return envelope_ok(ser_policy(policy))


@bp_a.route("/shc/students/<sid>/insurance-policies", methods=["GET"])
def list_student_policies(sid):
    require_auth()
    get_or_404("students", sid)
    items = [p for p in db["policies"].values() if p["student_id"] == sid]
    return list_response(items, ser_policy)


# ==========================================================================
# Immunization requirements and records
# ==========================================================================

@bp_a.route("/shc/immunization-requirements", methods=["POST"])
def create_requirement():
    require_auth({"HealthAdmin"})
    body = get_body()
    vaccine_code = req_string(body, "vaccine_code")
    required_doses = req_int(body, "required_doses")
    min_interval_days = req_int(body, "min_interval_days")
    deadline_date = parse_date(req_present(body, "deadline_date"), "deadline_date")
    grace_period_days = req_int(body, "grace_period_days")
    if not (1 <= required_doses <= 3):
        raise err_invalid_request("required_doses must be in 1..3")
    if min_interval_days < 0:
        raise err_invalid_request("min_interval_days must be >= 0")
    if grace_period_days < 0:
        raise err_invalid_request("grace_period_days must be >= 0")
    for r in db["requirements"].values():
        if r["vaccine_code"] == vaccine_code:
            raise ApiError("ERR_DUPLICATE_REQUIREMENT", 409,
                           "vaccine_code already defined")
    req = new_entity()
    req.update({
        "vaccine_code": vaccine_code,
        "required_doses": required_doses,
        "min_interval_days": min_interval_days,
        "deadline_date": deadline_date,
        "grace_period_days": grace_period_days,
    })
    db["requirements"][req["id"]] = req
    return envelope_ok(ser_requirement(req), status=201)


@bp_a.route("/shc/immunization-records", methods=["POST"])
def create_record():
    require_auth({"Nurse"})
    body = get_body()
    student_id = req_string(body, "student_id")
    requirement_id = req_string(body, "requirement_id")
    student = db["students"].get(student_id)
    if student is None:
        raise err_not_found("student_id does not reference an existing student")
    req = db["requirements"].get(requirement_id)
    if req is None:
        raise err_not_found("requirement_id does not reference an existing requirement")
    # At most one non-terminal record per (student, requirement).
    for r in db["records"].values():
        if (r["student_id"] == student_id and r["requirement_id"] == requirement_id
                and r["status"] not in ("IN_COMPLIANCE", "EXEMPTED")):
            raise ApiError("ERR_DUPLICATE_IMMUNIZATION_RECORD", 409,
                           "a non-terminal record already exists for this "
                           "student and requirement")
    rec = new_entity()
    rec.update({
        "student_id": student_id,
        "requirement_id": requirement_id,
        "doses_received": 0,
        "dose_dates": [],
        "status": "PENDING",
        "exemption_reason": None,
    })
    db["records"][rec["id"]] = rec
    # If deadline and grace have both already passed, the record enters
    # OVERDUE immediately, with posture recompute and elective cancellation.
    today = clock.now().date()
    overdue_boundary = req["deadline_date"] + timedelta(days=req["grace_period_days"])
    if today > overdue_boundary:
        rec["status"] = "OVERDUE"
        recompute_posture(student_id)
        cancel_future_electives(student_id)
    return envelope_ok(ser_record(rec), status=201)


@bp_a.route("/shc/immunization-records", methods=["GET"])
def list_records():
    require_auth()
    student_id = request_arg("student_id")
    requirement_id = request_arg("requirement_id")
    status = request_arg("status")
    items = db["records"].values()
    if student_id is not None:
        items = [r for r in items if r["student_id"] == student_id]
    if requirement_id is not None:
        items = [r for r in items if r["requirement_id"] == requirement_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, ser_record)


def request_arg(name):
    from flask import request
    return request.args.get(name)


@bp_a.route("/shc/immunization-records/<rid>", methods=["GET"])
def get_record(rid):
    require_auth()
    return envelope_ok(ser_record(get_or_404("records", rid)))


@bp_a.route("/shc/immunization-records/<rid>/doses", methods=["POST"])
def record_dose(rid):
    require_auth({"Nurse"})
    body = get_body()
    dose_date = parse_date(req_present(body, "dose_date"), "dose_date")
    expected_record_version = req_int(body, "expected_record_version")
    rec = get_or_404("records", rid)
    # OCC before business rules.
    if expected_record_version != rec["version"]:
        raise ApiError("ERR_STALE_RECORD_VERSION", 412,
                       "expected_record_version does not match record version")
    if rec["status"] not in ("PENDING", "GRACE", "OVERDUE"):
        raise ApiError("ERR_RECORD_NOT_DOSEABLE", 409,
                       "record is not in a doseable state")
    today = clock.now().date()
    if dose_date > today:
        raise ApiError("ERR_DOSE_DATE_IN_FUTURE", 422,
                       "dose_date is after the current logical date")
    req = db["requirements"][rec["requirement_id"]]
    if rec["dose_dates"]:
        prev = rec["dose_dates"][-1]
        if dose_date < prev + timedelta(days=req["min_interval_days"]):
            raise ApiError("ERR_DOSE_INTERVAL_VIOLATION", 422,
                           "dose_date precedes previous dose + min_interval_days")
    rec["dose_dates"].append(dose_date)
    rec["doses_received"] += 1
    if rec["doses_received"] == req["required_doses"]:
        rec["status"] = "IN_COMPLIANCE"
    bump(rec)
    recompute_posture(rec["student_id"])
    return envelope_ok(ser_record(rec))


@bp_a.route("/shc/immunization-records/<rid>/exempt", methods=["POST"])
def exempt_record(rid):
    require_auth({"Clinician"})
    body = get_body()
    reason = req_string(body, "exemption_reason")
    rec = get_or_404("records", rid)
    if rec["status"] not in ("PENDING", "GRACE", "OVERDUE"):
        raise ApiError("ERR_RECORD_NOT_DOSEABLE", 409,
                       "record is not in a doseable state")
    rec["status"] = "EXEMPTED"
    rec["exemption_reason"] = reason
    bump(rec)
    recompute_posture(rec["student_id"])
    return envelope_ok(ser_record(rec))


# ==========================================================================
# Providers and on-call shifts
# ==========================================================================

@bp_a.route("/shc/providers", methods=["POST"])
def create_provider():
    require_auth({"HealthAdmin"})
    body = get_body()
    full_name = req_string(body, "full_name")
    provider_type = req_enum(body, "provider_type", PROVIDER_TYPES)
    active = body.get("active", True)
    if active is None:
        active = True
    if not isinstance(active, bool):
        raise err_invalid_request("active must be a boolean")
    prov = new_entity()
    prov.update({
        "full_name": full_name,
        "provider_type": provider_type,
        "active": active,
    })
    db["providers"][prov["id"]] = prov
    return envelope_ok(ser_provider(prov), status=201)


@bp_a.route("/shc/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_auth()
    return envelope_ok(ser_provider(get_or_404("providers", pid)))


@bp_a.route("/shc/on-call-shifts", methods=["POST"])
def create_shift():
    require_auth({"HealthAdmin"})
    body = get_body()
    provider_id = req_string(body, "provider_id")
    shift_start = parse_dt(req_present(body, "shift_start"), "shift_start")
    shift_end = parse_dt(req_present(body, "shift_end"), "shift_end")
    if db["providers"].get(provider_id) is None:
        raise err_not_found("provider_id does not reference an existing provider")
    if shift_end <= shift_start:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "shift_end must be after shift_start")
    existing = [s for s in db["shifts"].values() if s["provider_id"] == provider_id]
    # Overlap first: CLOSED-interval semantics -- adjacent shifts conflict.
    for ex in existing:
        if shift_start <= ex["shift_end"] and ex["shift_start"] <= shift_end:
            raise ApiError("ERR_ONCALL_OVERLAP", 409,
                           "on-call shift overlaps another shift of the same provider")
    # Rest: any two shifts of the same provider must be separated by >= 12h;
    # a gap of exactly 12h is allowed.
    for ex in existing:
        if shift_end < ex["shift_start"]:
            gap = ex["shift_start"] - shift_end
        elif ex["shift_end"] < shift_start:
            gap = shift_start - ex["shift_end"]
        else:
            gap = timedelta(0)
        if gap < timedelta(hours=12):
            raise ApiError("ERR_ONCALL_REST_VIOLATION", 409,
                           "less than 12 hours between two shifts of the same provider")
    shift = new_entity()
    shift.update({
        "provider_id": provider_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
    })
    db["shifts"][shift["id"]] = shift
    return envelope_ok(ser_shift(shift), status=201)


@bp_a.route("/shc/providers/<pid>/on-call-shifts", methods=["GET"])
def list_provider_shifts(pid):
    require_auth()
    get_or_404("providers", pid)
    items = [s for s in db["shifts"].values() if s["provider_id"] == pid]
    return list_response(items, ser_shift)


# ==========================================================================
# Appointments
# ==========================================================================

@bp_a.route("/shc/appointments", methods=["POST"])
def create_appointment():
    uid, role = require_auth({"Student", "FrontDeskStaff"})
    body = get_body()
    student_id = req_string(body, "student_id")
    provider_id = req_string(body, "provider_id")
    visit_type = req_enum(body, "visit_type", VISIT_TYPES)
    scheduled_start = parse_dt(req_present(body, "scheduled_start"), "scheduled_start")
    scheduled_end = parse_dt(req_present(body, "scheduled_end"), "scheduled_end")
    # Student actors may only book for themselves.
    if role == "Student" and student_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Student actors may only book their own appointments")
    student = db["students"].get(student_id)
    if student is None:
        raise err_not_found("student_id does not reference an existing student")
    if db["providers"].get(provider_id) is None:
        raise err_not_found("provider_id does not reference an existing provider")
    # Compliance gate (before temporal rules per validation order).
    if (visit_type in ELECTIVE_VISIT_TYPES
            and student["compliance_posture"] == "REGISTRATION_HOLD"):
        raise ApiError("ERR_COMPLIANCE_HOLD_ACTIVE", 403,
                       "elective booking blocked by REGISTRATION_HOLD posture")
    # Temporal rules.
    if scheduled_end <= scheduled_start:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "scheduled_end must be after scheduled_start")
    now = clock.now()
    if scheduled_start <= now:
        raise ApiError("ERR_APPOINTMENT_IN_PAST", 422,
                       "scheduled_start must be in the future")
    if visit_type == "SAME_DAY_TRIAGE" and scheduled_start.date() != now.date():
        raise ApiError("ERR_SAME_DAY_ONLY", 422,
                       "SAME_DAY_TRIAGE must be scheduled on the current date")
    if slot_conflict(provider_id, scheduled_start, scheduled_end):
        raise ApiError("ERR_SLOT_CONFLICT", 409,
                       "provider already has an overlapping appointment")
    # Cardinality: triage daily quota.
    if (visit_type == "SAME_DAY_TRIAGE"
            and triage_count(provider_id, scheduled_start.date()) >= services.TRIAGE_DAILY_QUOTA):
        raise ApiError("ERR_TRIAGE_QUOTA_EXHAUSTED", 409,
                       "provider daily triage quota exhausted")
    # Fiscal gate: TRAVEL_CLINIC requires a VERIFIED policy.
    if visit_type == "TRAVEL_CLINIC" and services.find_verified_policy(student_id) is None:
        raise ApiError("ERR_INSURANCE_NOT_VERIFIED", 402,
                       "TRAVEL_CLINIC booking requires a VERIFIED insurance policy")
    appt = new_entity()
    appt.update({
        "student_id": student_id,
        "provider_id": provider_id,
        "visit_type": visit_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "BOOKED",
        "cancel_reason": "NONE",
    })
    db["appointments"][appt["id"]] = appt
    return envelope_ok(ser_appointment(appt), status=201)


@bp_a.route("/shc/appointments", methods=["GET"])
def list_appointments():
    require_auth()
    student_id = request_arg("student_id")
    provider_id = request_arg("provider_id")
    date_f = request_arg("date")
    status = request_arg("status")
    items = db["appointments"].values()
    if student_id is not None:
        items = [a for a in items if a["student_id"] == student_id]
    if provider_id is not None:
        items = [a for a in items if a["provider_id"] == provider_id]
    if date_f is not None:
        items = [a for a in items if a["scheduled_start"].date().isoformat() == date_f]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser_appointment)


@bp_a.route("/shc/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    require_auth()
    return envelope_ok(ser_appointment(get_or_404("appointments", aid)))


@bp_a.route("/shc/appointments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    require_auth({"FrontDeskStaff"})
    get_body()
    appt = get_or_404("appointments", aid)
    if appt["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_BOOKED", 409,
                       "check-in requires status BOOKED")
    now = clock.now()
    appt["status"] = "CHECKED_IN"
    bump(appt)
    student = db["students"][appt["student_id"]]
    enc = new_entity()
    enc.update({
        "appointment_id": appt["id"],
        "student_id": appt["student_id"],
        "provider_id": appt["provider_id"],
        "visit_type": appt["visit_type"],
        "status": "OPEN",
        "clearance_outcome": "NONE",
        "fee_covered": services.compute_fee_covered(appt["visit_type"], student),
        "opened_at": now,
        "closed_at": None,
    })
    db["encounters"][enc["id"]] = enc
    return envelope_ok(ser_encounter(enc), status=201)


@bp_a.route("/shc/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    uid, role = require_auth({"Student", "FrontDeskStaff"})
    get_body()
    appt = get_or_404("appointments", aid)
    if role == "Student" and appt["student_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Student actors may only cancel their own appointments")
    if appt["status"] != "BOOKED":
        raise ApiError("ERR_APPOINTMENT_NOT_CANCELLABLE", 409,
                       "cancel requires status BOOKED")
    appt["status"] = "CANCELLED"
    appt["cancel_reason"] = "CLIENT"
    bump(appt)
    return envelope_ok(ser_appointment(appt))
