"""All HTTP route handlers."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

import db
import clock
import calculations
import services
import serializers as S
import validators as V
import response as R
import middleware as M
from errors import APIError
import errors as E


bp = Blueprint("leave", __name__)


# ---------------------------------------------------------------------------
# Constants / enums
# ---------------------------------------------------------------------------

STATE_CODES = {"CA", "NY", "NJ", "MA", "WA", "CT", "RI", "CO", "OR", "FED"}
FMLA_METHODS = {"ROLLING_BACKWARD", "CALENDAR_YEAR"}
QUALIFYING_REASONS = {
    "OWN_SERIOUS_HEALTH_CONDITION",
    "FAMILY_SERIOUS_HEALTH_CONDITION",
    "NEW_CHILD_BONDING",
    "MILITARY_CAREGIVER",
    "QUALIFYING_EXIGENCY",
}
PFL_CONCURRENT_REASONS = {
    "OWN_SERIOUS_HEALTH_CONDITION",
    "FAMILY_SERIOUS_HEALTH_CONDITION",
    "NEW_CHILD_BONDING",
}
LEAVE_TYPES = {"CONTINUOUS", "INTERMITTENT", "REDUCED_SCHEDULE"}
INTERMITTENT_TYPES = {"INTERMITTENT", "REDUCED_SCHEDULE"}
NOTICE_TYPES = {
    "ELIGIBILITY_NOTICE",
    "RIGHTS_RESPONSIBILITIES_NOTICE",
    "DESIGNATION_NOTICE",
    "CERTIFICATION_DEMAND",
    "RECERTIFICATION_REQUEST",
}
CASE_STATUSES = {
    "SUBMITTED", "ELIGIBILITY_PENDING", "CERTIFICATION_PENDING", "APPROVED",
    "DENIED", "ACTIVE", "COMPLETED", "JOB_RESTORED", "JOB_FORFEITED",
}


def _get_entity(table, ent_id):
    ent = table.get(ent_id)
    if ent is None:
        raise APIError(E.ERR_NOT_FOUND, "Entity not found.", 404)
    return ent


def _check_fk(table, ent_id, label):
    if ent_id not in table:
        raise APIError(E.ERR_REFERENCED_ENTITY_NOT_FOUND,
                       f"Referenced {label} not found.", 404)
    return table[ent_id]


# ===========================================================================
# Employer
# ===========================================================================

@bp.route("/leave/employers", methods=["POST"])
def create_employer():
    M.require_roles("PlatformAdmin")
    body = V.require_json(request)
    legal_name = V.require_field(body, "legal_name", str)
    state_code = V.require_enum(body, "state_code", STATE_CODES)
    fmla_method = V.optional_enum(body, "fmla_method", FMLA_METHODS, default="ROLLING_BACKWARD")
    employer_premium_share_pct = V.require_field(body, "employer_premium_share_pct", (int, float))
    if isinstance(employer_premium_share_pct, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "employer_premium_share_pct must be numeric.", 400)
    monthly_premium_total_cents = V.require_field(body, "monthly_premium_total_cents", int)
    if isinstance(monthly_premium_total_cents, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "monthly_premium_total_cents must be integer.", 400)
    if not (0.0 <= employer_premium_share_pct <= 1.0):
        raise APIError(E.ERR_INVALID_REQUEST,
                       "employer_premium_share_pct must be between 0.00 and 1.00.", 400)
    if monthly_premium_total_cents < 0:
        raise APIError(E.ERR_INVALID_REQUEST,
                       "monthly_premium_total_cents must be >= 0.", 400)
    pfl_enabled = state_code in services.PFL_ENABLED_STATES
    employer = {
        "legal_name": legal_name,
        "state_code": state_code,
        "fmla_method": fmla_method,
        "pfl_enabled": pfl_enabled,
        "employer_premium_share_pct": float(employer_premium_share_pct),
        "monthly_premium_total_cents": int(monthly_premium_total_cents),
    }
    services.init_common(employer)
    db.employers[employer["id"]] = employer
    return R.success(S.serialize_employer(employer), status=201)


@bp.route("/leave/employers/<eid>", methods=["GET"])
def get_employer(eid):
    M.require_roles("PlatformAdmin", "HRAdmin")
    employer = _get_entity(db.employers, eid)
    return R.success(S.serialize_employer(employer))


# ===========================================================================
# Employee
# ===========================================================================

@bp.route("/leave/employees", methods=["POST"])
def create_employee():
    M.require_roles("HRAdmin")
    body = V.require_json(request)
    employer_id = V.require_field(body, "employer_id", str)
    email = V.require_field(body, "email", str)
    full_name = V.require_field(body, "full_name", str)
    hire_date = V.parse_dt_field(body, "hire_date")
    hours = V.require_field(body, "hours_worked_trailing_12mo", int)
    if isinstance(hours, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "hours_worked_trailing_12mo must be integer.", 400)
    if hours < 0:
        raise APIError(E.ERR_INVALID_REQUEST, "hours_worked_trailing_12mo must be >= 0.", 400)
    home_state_code = V.require_enum(body, "home_state_code", STATE_CODES)
    health_plan_enrolled = V.optional_field(body, "health_plan_enrolled", bool, default=True)
    # FK check
    _check_fk(db.employers, employer_id, "employer")
    employee = {
        "employer_id": employer_id,
        "email": email,
        "full_name": full_name,
        "hire_date": hire_date,
        "hours_worked_trailing_12mo": hours,
        "home_state_code": home_state_code,
        "health_plan_enrolled": health_plan_enrolled,
        "employment_status": "ACTIVE",
        "job_restoration_deadline": None,
    }
    services.init_common(employee)
    db.employees[employee["id"]] = employee
    return R.success(S.serialize_employee(employee), status=201)


@bp.route("/leave/employees/<eid>", methods=["GET"])
def get_employee(eid):
    M.require_roles("HRAdmin", "Employee")
    employee = _get_entity(db.employees, eid)
    if g.user_role == "Employee" and g.user_id != employee["id"]:
        raise APIError(E.ERR_FORBIDDEN, "Employees can only access their own record.", 403)
    return R.success(S.serialize_employee(employee))


@bp.route("/leave/employees", methods=["GET"])
def list_employees():
    M.require_roles("HRAdmin")
    limit, offset = M.pagination_params()
    employer_filter = request.args.get("employer_id")
    rows = list(db.employees.values())
    if employer_filter:
        rows = [r for r in rows if r["employer_id"] == employer_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return R.success_list([S.serialize_employee(r) for r in page], limit, offset, total)


@bp.route("/leave/employees/<eid>/health-enrollment", methods=["PATCH"])
def patch_health_enrollment(eid):
    M.require_roles("HRAdmin")
    employee = _get_entity(db.employees, eid)
    body = V.require_json(request)
    new_val = V.require_field(body, "health_plan_enrolled", bool)
    expected_version = V.require_field(body, "expected_employee_version", int)
    if isinstance(expected_version, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "expected_employee_version must be integer.", 400)
    if expected_version != employee["version"]:
        raise APIError(E.ERR_STALE_VERSION,
                       "expected_employee_version does not match live version.", 412)
    if employee["health_plan_enrolled"] != new_val:
        employee["health_plan_enrolled"] = new_val
        services.touch(employee)
    return R.success(S.serialize_employee(employee))


@bp.route("/leave/employees/<eid>/terminate", methods=["POST"])
def terminate_employee(eid):
    M.require_roles("HRAdmin")
    employee = _get_entity(db.employees, eid)
    # State precondition: ERR_INVALID_STATE if currently ON_LEAVE with job_restoration_protected
    # or if already TERMINATED.
    if employee["employment_status"] == "TERMINATED":
        raise APIError(E.ERR_INVALID_STATE, "Employee already TERMINATED.", 409)
    if employee["employment_status"] == "ON_LEAVE":
        # Check whether any of their active cases is still protected.
        for case in db.leave_cases.values():
            if case["employee_id"] == eid and case["status"] in ("APPROVED", "ACTIVE"):
                if case.get("job_restoration_protected", False):
                    raise APIError(E.ERR_INVALID_STATE,
                                   "Cannot terminate while ON_LEAVE with job_restoration_protected.",
                                   409)
    employee["employment_status"] = "TERMINATED"
    services.touch(employee)
    return R.success(S.serialize_employee(employee))


# ===========================================================================
# HealthcareProvider
# ===========================================================================

@bp.route("/leave/providers", methods=["POST"])
def create_provider():
    M.require_roles("PlatformAdmin", "HRAdmin")
    body = V.require_json(request)
    license_id = V.require_field(body, "license_id", str)
    full_name = V.require_field(body, "full_name", str)
    specialty = V.require_field(body, "specialty", str)
    provider = {
        "license_id": license_id,
        "full_name": full_name,
        "specialty": specialty,
    }
    services.init_common(provider)
    db.providers[provider["id"]] = provider
    return R.success(S.serialize_provider(provider), status=201)


@bp.route("/leave/providers/<pid>", methods=["GET"])
def get_provider(pid):
    M.require_roles("PlatformAdmin", "HRAdmin", "HealthcareProvider")
    provider = _get_entity(db.providers, pid)
    if g.user_role == "HealthcareProvider" and g.user_id != provider["id"]:
        raise APIError(E.ERR_FORBIDDEN, "Providers can only view their own record.", 403)
    return R.success(S.serialize_provider(provider))


# ===========================================================================
# LeaveCase
# ===========================================================================

@bp.route("/leave/cases", methods=["POST"])
def submit_leave_case():
    M.require_roles("Employee", "HRAdmin")
    body = V.require_json(request)
    employee_id = V.require_field(body, "employee_id", str)
    qualifying_reason = V.require_enum(body, "qualifying_reason", QUALIFYING_REASONS)
    leave_type = V.require_enum(body, "leave_type", LEAVE_TYPES)
    requested_start_at = V.parse_dt_field(body, "requested_start_at")
    requested_end_at = V.parse_dt_field(body, "requested_end_at")
    employee = _check_fk(db.employees, employee_id, "employee")
    # Acting Employee not TERMINATED (priority 6)
    if employee["employment_status"] == "TERMINATED":
        raise APIError(E.ERR_EMPLOYEE_TERMINATED,
                       "Acting employee is TERMINATED.", 409)
    # If acting as Employee, ownership check
    if g.user_role == "Employee" and g.user_id != employee_id:
        raise APIError(E.ERR_FORBIDDEN, "Employees can only submit cases for themselves.", 403)
    # Submission preconditions (state-style)
    if employee["employment_status"] != "ACTIVE":
        raise APIError(E.ERR_INVALID_STATE,
                       "Employee must be ACTIVE to submit a leave case.", 409)
    now = clock.now_utc()
    if not (requested_start_at > now):
        raise APIError(E.ERR_INVALID_STATE,
                       "requested_start_at must be in the future of now.", 409)
    case = {
        "employee_id": employee_id,
        "qualifying_reason": qualifying_reason,
        "leave_type": leave_type,
        "requested_start_at": requested_start_at,
        "requested_end_at": requested_end_at,
        "status": "ELIGIBILITY_PENDING",  # auto-transitions from SUBMITTED within the same request
        "eligibility_evaluated": False,
        "tenure_months_at_request": None,
        "hours_at_request": None,
        "pfl_concurrent": False,
        "fmla_hours_charged": Decimal("0.0"),
        "pfl_hours_charged": Decimal("0.0"),
        "job_restoration_protected": False,
    }
    services.init_common(case)
    db.leave_cases[case["id"]] = case
    # Issue ELIGIBILITY_NOTICE (response_due_at = sent_at + 5 days)
    services.create_notice(case, "ELIGIBILITY_NOTICE", response_window_days=5)
    # Issue RIGHTS_RESPONSIBILITIES_NOTICE (no response window)
    services.create_notice(case, "RIGHTS_RESPONSIBILITIES_NOTICE")
    return R.success(S.serialize_leave_case(case), status=201)


@bp.route("/leave/cases/<cid>", methods=["GET"])
def get_case(cid):
    M.require_roles("HRAdmin", "Employee")
    case = _get_entity(db.leave_cases, cid)
    if g.user_role == "Employee" and g.user_id != case["employee_id"]:
        raise APIError(E.ERR_FORBIDDEN, "Employees can only view their own cases.", 403)
    return R.success(S.serialize_leave_case(case))


@bp.route("/leave/cases", methods=["GET"])
def list_cases():
    M.require_roles("HRAdmin", "Employee")
    limit, offset = M.pagination_params()
    employee_filter = request.args.get("employee_id")
    status_filter = request.args.get("status")
    rows = list(db.leave_cases.values())
    if g.user_role == "Employee":
        rows = [r for r in rows if r["employee_id"] == g.user_id]
    if employee_filter:
        rows = [r for r in rows if r["employee_id"] == employee_filter]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return R.success_list([S.serialize_leave_case(r) for r in page], limit, offset, total)


@bp.route("/leave/cases/<cid>/evaluate-eligibility", methods=["POST"])
def evaluate_eligibility(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    if case["status"] != "ELIGIBILITY_PENDING":
        raise APIError(E.ERR_INVALID_STATE,
                       "Case must be ELIGIBILITY_PENDING to evaluate eligibility.", 409)
    employee = db.employees.get(case["employee_id"])
    if employee is None:
        raise APIError(E.ERR_NOT_FOUND, "Employee for case not found.", 404)
    if employee["employment_status"] == "TERMINATED":
        raise APIError(E.ERR_EMPLOYEE_TERMINATED,
                       "Acting employee is TERMINATED.", 409)
    eligible, tenure_months, hours_at = calculations.fmla_eligibility(employee, case)
    case["eligibility_evaluated"] = True
    case["tenure_months_at_request"] = tenure_months
    case["hours_at_request"] = hours_at
    if not eligible:
        case["status"] = "DENIED"
        services.touch(case)
        # Per PRD §3.3: "threshold-failure branch returns ERR_INELIGIBLE to the caller
        # when the call was driven against an employee who fails one or both checks
        # at the moment of evaluation." The case is moved to DENIED, but the response
        # is the error.
        raise APIError(E.ERR_INELIGIBLE,
                       "Employee does not meet eligibility thresholds.", 422)
    case["status"] = "CERTIFICATION_PENDING"
    services.touch(case)
    services.create_notice(case, "CERTIFICATION_DEMAND", response_window_days=15)
    return R.success(S.serialize_leave_case(case))


@bp.route("/leave/cases/<cid>/approve", methods=["POST"])
def approve_case(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    body = V.require_json(request)
    expected_version = V.require_field(body, "expected_leave_case_version", int)
    if isinstance(expected_version, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "expected_leave_case_version must be integer.", 400)
    if case["status"] != "CERTIFICATION_PENDING":
        raise APIError(E.ERR_INVALID_STATE,
                       "Case must be CERTIFICATION_PENDING to approve.", 409)
    employee = db.employees.get(case["employee_id"])
    if employee is None:
        raise APIError(E.ERR_NOT_FOUND, "Employee for case not found.", 404)
    if employee["employment_status"] == "TERMINATED":
        raise APIError(E.ERR_EMPLOYEE_TERMINATED,
                       "Acting employee is TERMINATED.", 409)
    latest_cert = services.latest_certification_for_case(cid)
    if latest_cert is None or latest_cert["certification_status"] != "COMPLETE":
        raise APIError(E.ERR_CERTIFICATION_INCOMPLETE,
                       "Most-recent certification is not COMPLETE.", 409)
    if expected_version != case["version"]:
        raise APIError(E.ERR_STALE_VERSION,
                       "expected_leave_case_version does not match live version.", 412)
    employer = db.employers.get(employee["employer_id"])
    if employer is None:
        raise APIError(E.ERR_NOT_FOUND, "Employer for case not found.", 404)
    # Stamp pfl_concurrent
    case["pfl_concurrent"] = services.compute_pfl_concurrent(employer, employee, case)
    case["status"] = "APPROVED"
    case["job_restoration_protected"] = True
    services.touch(case)
    # DESIGNATION_NOTICE
    services.create_notice(case, "DESIGNATION_NOTICE")
    # Initial benefit ledger if health_plan_enrolled
    if employee["health_plan_enrolled"]:
        period_start = case["requested_start_at"]
        # one month later, naive add — using 30-day approximation would mis-align;
        # use calendar-month add.
        period_end = _add_one_month(period_start)
        employer_share, employee_share = calculations.benefit_continuation_premium(
            period_start, period_end,
            employer["monthly_premium_total_cents"],
            employer["employer_premium_share_pct"],
            services.intervals_for_case(case["id"]),
        )
        ledger = {
            "employee_id": employee["id"],
            "leave_case_id": case["id"],
            "period_start": period_start,
            "period_end": period_end,
            "employer_premium_share_cents": employer_share,
            "employee_premium_share_cents": employee_share,
            "employee_owes_cents": employee_share,
            "payments_received_cents": 0,
            "payment_status": "PENDING",
        }
        services.init_common(ledger)
        db.ledgers[ledger["id"]] = ledger
    return R.success(S.serialize_leave_case(case))


def _add_one_month(dt):
    """Add one calendar month to dt (keeping UTC tz). Handles month-end overflow."""
    year = dt.year
    month = dt.month + 1
    if month > 12:
        month = 1
        year += 1
    day = dt.day
    # Find last day of target month
    import calendar as cal
    last_day = cal.monthrange(year, month)[1]
    if day > last_day:
        day = last_day
    return dt.replace(year=year, month=month, day=day)


@bp.route("/leave/cases/<cid>/deny", methods=["POST"])
def deny_case(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    if case["status"] != "CERTIFICATION_PENDING":
        raise APIError(E.ERR_INVALID_STATE,
                       "Case must be CERTIFICATION_PENDING to deny.", 409)
    # Permitted when either: (a) cert window expired without COMPLETE; or
    # (b) an INSUFFICIENT cert exists with no successor.
    now = clock.now_utc()
    certs = services.all_certifications_for_case(cid)
    # find certification demand notice
    notices_for = [n for n in db.notices.values()
                   if n["leave_case_id"] == cid and n["notice_type"] == "CERTIFICATION_DEMAND"]
    notices_for.sort(key=lambda n: n["sent_at"])
    cert_demand = notices_for[-1] if notices_for else None

    branch_a = False
    if cert_demand is not None and cert_demand["response_due_at"] is not None:
        if now > cert_demand["response_due_at"]:
            any_complete = any(c["certification_status"] == "COMPLETE" for c in certs)
            if not any_complete:
                branch_a = True
    branch_b = False
    if certs:
        last = certs[-1]
        if last["certification_status"] == "INSUFFICIENT":
            branch_b = True
    if not (branch_a or branch_b):
        raise APIError(E.ERR_INVALID_STATE,
                       "Denial preconditions not met.", 409)
    case["status"] = "DENIED"
    services.touch(case)
    return R.success(S.serialize_leave_case(case))


@bp.route("/leave/cases/<cid>/complete", methods=["POST"])
def complete_case(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    if case["status"] != "ACTIVE":
        raise APIError(E.ERR_INVALID_STATE, "Case must be ACTIVE to complete.", 409)
    has_recorded = any(i["leave_case_id"] == cid and i["status"] == "RECORDED"
                       for i in db.intervals.values())
    if not has_recorded:
        raise APIError(E.ERR_INVALID_STATE,
                       "At least one RECORDED interval required to complete.", 409)
    case["status"] = "COMPLETED"
    services.touch(case)
    # Employee returns to ACTIVE
    employee = db.employees.get(case["employee_id"])
    if employee is not None:
        services.set_employment_status(employee, "ACTIVE")
    return R.success(S.serialize_leave_case(case))


@bp.route("/leave/cases/<cid>/restore", methods=["POST"])
def restore_case(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    if case["status"] != "COMPLETED":
        raise APIError(E.ERR_INVALID_STATE, "Case must be COMPLETED to restore.", 409)
    if not case.get("job_restoration_protected", False):
        raise APIError(E.ERR_INVALID_STATE,
                       "job_restoration_protected is false; cannot restore.", 409)
    employee = db.employees.get(case["employee_id"])
    now = clock.now_utc()
    if employee is not None and employee.get("job_restoration_deadline") is not None:
        if now > employee["job_restoration_deadline"]:
            raise APIError(E.ERR_INVALID_STATE,
                           "Restoration deadline has passed.", 409)
    case["status"] = "JOB_RESTORED"
    services.touch(case)
    if employee is not None:
        services.set_employment_status(employee, "ACTIVE")
        services.set_job_restoration_deadline(employee, None)
    return R.success(S.serialize_leave_case(case))


@bp.route("/leave/cases/<cid>/forfeit-restoration", methods=["POST"])
def forfeit_case(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    if case["status"] != "COMPLETED":
        raise APIError(E.ERR_INVALID_STATE, "Case must be COMPLETED to forfeit.", 409)
    employee = db.employees.get(case["employee_id"])
    now = clock.now_utc()
    protected = case.get("job_restoration_protected", False)
    deadline_passed = False
    if employee is not None and employee.get("job_restoration_deadline") is not None:
        deadline_passed = now > employee["job_restoration_deadline"]
    if not (not protected or deadline_passed):
        raise APIError(E.ERR_INVALID_STATE,
                       "Forfeit only permitted when protection lapsed or deadline passed.",
                       409)
    case["status"] = "JOB_FORFEITED"
    services.touch(case)
    if employee is not None:
        services.set_job_restoration_deadline(employee, None)
    return R.success(S.serialize_leave_case(case))


@bp.route("/leave/cases/<cid>/request-recertification", methods=["POST"])
def request_recertification(cid):
    M.require_roles("HRAdmin")
    case = _get_entity(db.leave_cases, cid)
    if case["status"] not in ("APPROVED", "ACTIVE"):
        raise APIError(E.ERR_INVALID_STATE,
                       "Case must be APPROVED or ACTIVE to request recertification.", 409)
    certs = services.all_certifications_for_case(cid)
    # Find latest COMPLETE cert
    prior_complete = None
    for c in reversed(certs):
        if c["certification_status"] == "COMPLETE":
            prior_complete = c
            break
    if prior_complete is None or prior_complete.get("received_at") is None:
        raise APIError(E.ERR_INVALID_STATE,
                       "No prior COMPLETE certification with received_at to gate recertification.",
                       409)
    now = clock.now_utc()
    days_elapsed = (now - prior_complete["received_at"]).total_seconds() / 86400.0
    if days_elapsed < 30:
        raise APIError(E.ERR_RECERT_TOO_SOON,
                       "Recertification requested fewer than 30 days after prior COMPLETE.received_at.",
                       409)
    # Create new PENDING certification on same case, same provider as the prior complete.
    # The recert cycle prose (PRD §3.5) explicitly requires the new record to walk
    # PENDING -> RECEIVED -> COMPLETE; receive requires provider_attestation_signed_at,
    # so inherit it from the prior COMPLETE record.
    new_cert = {
        "leave_case_id": case["id"],
        "provider_id": prior_complete["provider_id"],
        "certification_status": "PENDING",
        "expected_duration_weeks": prior_complete.get("expected_duration_weeks"),
        "intermittent_frequency_per_month": prior_complete.get("intermittent_frequency_per_month"),
        "intermittent_hours_per_episode": prior_complete.get("intermittent_hours_per_episode"),
        "provider_attestation_signed_at": prior_complete.get("provider_attestation_signed_at"),
        "received_at": None,
        "insufficient_reason": None,
    }
    services.init_common(new_cert)
    db.certifications[new_cert["id"]] = new_cert
    # Previous COMPLETE -> RECERTIFICATION_REQUESTED
    prior_complete["certification_status"] = "RECERTIFICATION_REQUESTED"
    services.touch(prior_complete)
    # RECERTIFICATION_REQUEST notice
    services.create_notice(case, "RECERTIFICATION_REQUEST", response_window_days=15)
    # Bump case version
    services.touch(case)
    return R.success(S.serialize_certification(new_cert), status=201)


# ===========================================================================
# CertificationRecord
# ===========================================================================

@bp.route("/leave/certifications", methods=["POST"])
def create_certification():
    M.require_roles("HealthcareProvider", "HRAdmin")
    body = V.require_json(request)
    leave_case_id = V.require_field(body, "leave_case_id", str)
    provider_id = V.require_field(body, "provider_id", str)
    expected_duration_weeks = V.require_field(body, "expected_duration_weeks", (int, float))
    if isinstance(expected_duration_weeks, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "expected_duration_weeks must be numeric.", 400)
    intermittent_freq = V.optional_field(body, "intermittent_frequency_per_month", int)
    if intermittent_freq is not None and isinstance(intermittent_freq, bool):
        raise APIError(E.ERR_INVALID_REQUEST,
                       "intermittent_frequency_per_month must be integer.", 400)
    intermittent_hours = V.optional_field(body, "intermittent_hours_per_episode", (int, float))
    if intermittent_hours is not None and isinstance(intermittent_hours, bool):
        raise APIError(E.ERR_INVALID_REQUEST,
                       "intermittent_hours_per_episode must be numeric.", 400)
    provider_signed = V.parse_dt_field(body, "provider_attestation_signed_at", required=True)
    # FKs
    case = _check_fk(db.leave_cases, leave_case_id, "leave_case")
    provider = _check_fk(db.providers, provider_id, "provider")
    # If acting as HealthcareProvider, ownership check
    if g.user_role == "HealthcareProvider" and g.user_id != provider_id:
        raise APIError(E.ERR_FORBIDDEN,
                       "Providers can only submit certifications under their own id.", 403)
    cert = {
        "leave_case_id": leave_case_id,
        "provider_id": provider_id,
        "certification_status": "PENDING",
        "expected_duration_weeks": expected_duration_weeks,
        "intermittent_frequency_per_month": intermittent_freq,
        "intermittent_hours_per_episode": intermittent_hours,
        "provider_attestation_signed_at": provider_signed,
        "received_at": None,
        "insufficient_reason": None,
    }
    services.init_common(cert)
    db.certifications[cert["id"]] = cert
    return R.success(S.serialize_certification(cert), status=201)


@bp.route("/leave/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    M.require_roles("HRAdmin", "Employee", "HealthcareProvider")
    cert = _get_entity(db.certifications, cid)
    if g.user_role == "Employee":
        case = db.leave_cases.get(cert["leave_case_id"])
        if case is None or g.user_id != case["employee_id"]:
            raise APIError(E.ERR_FORBIDDEN, "Employees can only view their own certifications.", 403)
    elif g.user_role == "HealthcareProvider":
        if g.user_id != cert["provider_id"]:
            raise APIError(E.ERR_FORBIDDEN, "Providers can only view their own certifications.", 403)
    return R.success(S.serialize_certification(cert))


@bp.route("/leave/certifications", methods=["GET"])
def list_certifications():
    M.require_roles("HRAdmin", "HealthcareProvider")
    limit, offset = M.pagination_params()
    case_filter = request.args.get("leave_case_id")
    provider_filter = request.args.get("provider_id")
    rows = list(db.certifications.values())
    if g.user_role == "HealthcareProvider":
        rows = [r for r in rows if r["provider_id"] == g.user_id]
    if case_filter:
        rows = [r for r in rows if r["leave_case_id"] == case_filter]
    if provider_filter:
        rows = [r for r in rows if r["provider_id"] == provider_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return R.success_list([S.serialize_certification(r) for r in page],
                          limit, offset, total)


@bp.route("/leave/certifications/<cid>/receive", methods=["POST"])
def receive_certification(cid):
    M.require_roles("HRAdmin")
    cert = _get_entity(db.certifications, cid)
    if cert["certification_status"] != "PENDING":
        raise APIError(E.ERR_INVALID_STATE, "Certification must be PENDING to receive.", 409)
    case = db.leave_cases.get(cert["leave_case_id"])
    if case is None:
        raise APIError(E.ERR_NOT_FOUND, "Leave case for certification not found.", 404)
    # PRD §3.5: receive applies to a PENDING cert. The initial cert path runs while
    # the case is CERTIFICATION_PENDING; the recertification cycle prose (PRD §3.5)
    # also walks the new record PENDING -> RECEIVED -> COMPLETE while the case is
    # APPROVED/ACTIVE. Allow receive in any of these case states.
    if case["status"] not in ("CERTIFICATION_PENDING", "APPROVED", "ACTIVE"):
        raise APIError(E.ERR_INVALID_STATE,
                       "Parent case must be CERTIFICATION_PENDING (or APPROVED/ACTIVE for recert).",
                       409)
    if cert.get("provider_attestation_signed_at") is None:
        raise APIError(E.ERR_INVALID_STATE,
                       "provider_attestation_signed_at must be set.", 409)
    cert["certification_status"] = "RECEIVED"
    cert["received_at"] = clock.now_utc()
    services.touch(cert)
    # Refresh notices
    services.update_response_received_for_case(case["id"])
    return R.success(S.serialize_certification(cert))


@bp.route("/leave/certifications/<cid>/mark-complete", methods=["POST"])
def mark_complete(cid):
    M.require_roles("HRAdmin")
    cert = _get_entity(db.certifications, cid)
    if cert["certification_status"] != "RECEIVED":
        raise APIError(E.ERR_INVALID_STATE,
                       "Certification must be RECEIVED to mark complete.", 409)
    case = db.leave_cases.get(cert["leave_case_id"])
    if case is None:
        raise APIError(E.ERR_NOT_FOUND, "Leave case for certification not found.", 404)
    # Intermittent fields validation (priority 8)
    if case["leave_type"] in INTERMITTENT_TYPES:
        freq = cert.get("intermittent_frequency_per_month")
        hrs = cert.get("intermittent_hours_per_episode")
        if (freq is None or freq < 1 or hrs is None or hrs <= 0):
            raise APIError(E.ERR_INTERMITTENT_CERT_REQUIRED,
                           "Intermittent fields required: frequency >= 1 AND hours_per_episode > 0.",
                           422)
    else:  # CONTINUOUS
        if cert.get("expected_duration_weeks") is None or cert["expected_duration_weeks"] <= 0:
            raise APIError(E.ERR_INVALID_STATE,
                           "expected_duration_weeks must be > 0 for CONTINUOUS leave.", 409)
    # There must be no later record on the same case.
    siblings = services.all_certifications_for_case(case["id"])
    later = [c for c in siblings if c["created_at"] > cert["created_at"]]
    if later:
        raise APIError(E.ERR_INVALID_STATE,
                       "A later CertificationRecord exists; this is not the most recent.", 409)
    cert["certification_status"] = "COMPLETE"
    services.touch(cert)
    return R.success(S.serialize_certification(cert))


@bp.route("/leave/certifications/<cid>/mark-insufficient", methods=["POST"])
def mark_insufficient(cid):
    M.require_roles("HRAdmin")
    cert = _get_entity(db.certifications, cid)
    if cert["certification_status"] != "RECEIVED":
        raise APIError(E.ERR_INVALID_STATE,
                       "Certification must be RECEIVED to mark insufficient.", 409)
    body = V.require_json(request)
    reason = V.require_field(body, "insufficient_reason", str)
    if not reason.strip():
        raise APIError(E.ERR_INVALID_REQUEST,
                       "insufficient_reason must be non-empty.", 400)
    cert["certification_status"] = "INSUFFICIENT"
    cert["insufficient_reason"] = reason
    services.touch(cert)
    case = db.leave_cases.get(cert["leave_case_id"])
    if case is not None:
        services.create_notice(case, "RECERTIFICATION_REQUEST", response_window_days=15)
    return R.success(S.serialize_certification(cert))


# ===========================================================================
# LeaveInterval
# ===========================================================================

def _record_interval_charges(case, raw_hours):
    """Compute and record the per-interval FMLA/PFL charges; update case totals."""
    employee = db.employees.get(case["employee_id"])
    home_state = employee["home_state_code"] if employee else "FED"
    fmla_charge, pfl_charge = calculations.compute_pool_charge(
        raw_hours,
        case["fmla_hours_charged"],
        case["pfl_hours_charged"],
        case["pfl_concurrent"],
        home_state,
    )
    case["fmla_hours_charged"] = case["fmla_hours_charged"] + fmla_charge
    case["pfl_hours_charged"] = case["pfl_hours_charged"] + pfl_charge
    return fmla_charge, pfl_charge


@bp.route("/leave/intervals", methods=["POST"])
def create_interval():
    M.require_roles("HRAdmin")
    body = V.require_json(request)
    leave_case_id = V.require_field(body, "leave_case_id", str)
    start_dt = V.parse_dt_field(body, "start_datetime")
    end_dt = V.parse_dt_field(body, "end_datetime")
    hours_taken_raw = V.require_field(body, "hours_taken", (int, float))
    if isinstance(hours_taken_raw, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "hours_taken must be numeric.", 400)
    if hours_taken_raw <= 0:
        raise APIError(E.ERR_INVALID_REQUEST, "hours_taken must be > 0.", 400)
    if end_dt <= start_dt:
        raise APIError(E.ERR_INVALID_REQUEST,
                       "end_datetime must be strictly after start_datetime.", 400)
    case = _check_fk(db.leave_cases, leave_case_id, "leave_case")
    # State precondition (priority 5)
    if case["status"] not in ("APPROVED", "ACTIVE"):
        raise APIError(E.ERR_INVALID_STATE,
                       "Case must be APPROVED or ACTIVE to record intervals.", 409)
    # First-interval timing precondition: now >= requested_start_at
    if case["status"] == "APPROVED":
        if clock.now_utc() < case["requested_start_at"]:
            raise APIError(E.ERR_INVALID_STATE,
                           "Cannot record first interval before requested_start_at.", 409)
    # Overlap check (priority 11)
    existing = [i for i in db.intervals.values()
                if i["leave_case_id"] == leave_case_id and i["status"] == "RECORDED"]
    for other in existing:
        if start_dt < other["end_datetime"] and end_dt > other["start_datetime"]:
            raise APIError(E.ERR_INTERVAL_OVERLAP,
                           "Interval overlaps another RECORDED interval on this case.", 409)
    # Intermittent checks (priority 12, 13)
    if case["leave_type"] in INTERMITTENT_TYPES:
        # Use the authoritative (COMPLETE) certification for intermittent params.
        complete_cert = None
        for c in services.all_certifications_for_case(case["id"]):
            if c["certification_status"] == "COMPLETE":
                complete_cert = c
        # If no current COMPLETE (e.g., during recertification cycle), fall back to the
        # most recent record that has the intermittent fields populated.
        if complete_cert is None:
            for c in reversed(services.all_certifications_for_case(case["id"])):
                if c.get("intermittent_frequency_per_month") is not None:
                    complete_cert = c
                    break
        if complete_cert is not None:
            freq = complete_cert.get("intermittent_frequency_per_month")
            hrs_per = complete_cert.get("intermittent_hours_per_episode")
            # Frequency
            if freq is not None:
                month_count = 1  # this new interval
                for iv in existing:
                    if (iv["start_datetime"].year == start_dt.year and
                            iv["start_datetime"].month == start_dt.month):
                        month_count += 1
                if month_count > freq:
                    raise APIError(E.ERR_INTERMITTENT_FREQUENCY_EXCEEDED,
                                   "Monthly episode count exceeds certified frequency.", 409)
            # Hours per episode (priority 13)
            if hrs_per is not None and hours_taken_raw > hrs_per:
                raise APIError(E.ERR_INTERMITTENT_HOURS_EXCEEDED,
                               "hours_taken exceeds certified hours_per_episode.", 422)
    # Compute charges
    employee = db.employees.get(case["employee_id"])
    home_state = employee["home_state_code"] if employee else "FED"
    fmla_charge, pfl_charge = calculations.compute_pool_charge(
        hours_taken_raw,
        case["fmla_hours_charged"],
        case["pfl_hours_charged"],
        case["pfl_concurrent"],
        home_state,
    )
    interval = {
        "leave_case_id": leave_case_id,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "hours_taken": hours_taken_raw,
        "fmla_hours_charged": fmla_charge,
        "pfl_hours_charged": pfl_charge,
        "status": "RECORDED",
    }
    services.init_common(interval)
    db.intervals[interval["id"]] = interval
    # Update case totals
    case["fmla_hours_charged"] = case["fmla_hours_charged"] + fmla_charge
    case["pfl_hours_charged"] = case["pfl_hours_charged"] + pfl_charge
    # First-interval transitions
    was_approved = case["status"] == "APPROVED"
    if was_approved:
        case["status"] = "ACTIVE"
        if employee is not None:
            services.set_employment_status(employee, "ON_LEAVE")
            new_deadline = case["requested_start_at"] + timedelta(days=84)
            services.set_job_restoration_deadline(employee, new_deadline)
    # Cumulative-quota check: if fmla_hours_charged hits 480, flip job_restoration_protected false
    if case["fmla_hours_charged"] >= Decimal(calculations.FMLA_ANNUAL_QUOTA_HOURS):
        case["job_restoration_protected"] = False
    services.touch(case)
    # PRD §3.7: recompute the case's ledger rows after the set of RECORDED
    # intervals changes (the leave-fraction depends on them).
    services.recompute_ledger_rows_for_case(case["id"])
    return R.success(S.serialize_interval(interval), status=201)


@bp.route("/leave/intervals/<iid>", methods=["GET"])
def get_interval(iid):
    M.require_roles("HRAdmin", "Employee")
    interval = _get_entity(db.intervals, iid)
    if g.user_role == "Employee":
        case = db.leave_cases.get(interval["leave_case_id"])
        if case is None or g.user_id != case["employee_id"]:
            raise APIError(E.ERR_FORBIDDEN,
                           "Employees can only view their own intervals.", 403)
    return R.success(S.serialize_interval(interval))


@bp.route("/leave/intervals", methods=["GET"])
def list_intervals():
    M.require_roles("HRAdmin", "Employee")
    limit, offset = M.pagination_params()
    case_filter = request.args.get("leave_case_id")
    rows = list(db.intervals.values())
    if g.user_role == "Employee":
        # restrict to intervals whose parent case belongs to user
        rows = [r for r in rows
                if (db.leave_cases.get(r["leave_case_id"]) or {}).get("employee_id") == g.user_id]
    if case_filter:
        rows = [r for r in rows if r["leave_case_id"] == case_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return R.success_list([S.serialize_interval(r) for r in page],
                          limit, offset, total)


@bp.route("/leave/intervals/<iid>/reverse", methods=["POST"])
def reverse_interval(iid):
    M.require_roles("HRAdmin")
    interval = _get_entity(db.intervals, iid)
    if interval["status"] != "RECORDED":
        raise APIError(E.ERR_INVALID_STATE, "Interval must be RECORDED to reverse.", 409)
    case = db.leave_cases.get(interval["leave_case_id"])
    if case is None:
        raise APIError(E.ERR_NOT_FOUND, "Case for interval not found.", 404)
    if case["status"] != "ACTIVE":
        raise APIError(E.ERR_INVALID_STATE,
                       "Parent case must be ACTIVE to reverse an interval.", 409)
    now = clock.now_utc()
    if (now - interval["created_at"]).days > 14:
        raise APIError(E.ERR_INVALID_STATE,
                       "Interval can only be reversed within 14 days of being recorded.", 409)
    interval["status"] = "REVERSED"
    services.touch(interval)
    case["fmla_hours_charged"] = case["fmla_hours_charged"] - interval["fmla_hours_charged"]
    case["pfl_hours_charged"] = case["pfl_hours_charged"] - interval["pfl_hours_charged"]
    if case["fmla_hours_charged"] < Decimal(calculations.FMLA_ANNUAL_QUOTA_HOURS):
        case["job_restoration_protected"] = True
    services.touch(case)
    # PRD §3.7: recompute ledger rows after the set of RECORDED intervals changes.
    services.recompute_ledger_rows_for_case(case["id"])
    return R.success(S.serialize_interval(interval))


# ===========================================================================
# BenefitContinuationLedger
# ===========================================================================

@bp.route("/leave/benefit-ledgers/<lid>", methods=["GET"])
def get_ledger(lid):
    M.require_roles("HRAdmin", "Employee")
    ledger = _get_entity(db.ledgers, lid)
    if g.user_role == "Employee" and g.user_id != ledger["employee_id"]:
        raise APIError(E.ERR_FORBIDDEN,
                       "Employees can only view their own ledgers.", 403)
    return R.success(S.serialize_ledger(ledger))


@bp.route("/leave/benefit-ledgers", methods=["GET"])
def list_ledgers():
    M.require_roles("HRAdmin", "Employee")
    limit, offset = M.pagination_params()
    employee_filter = request.args.get("employee_id")
    case_filter = request.args.get("leave_case_id")
    rows = list(db.ledgers.values())
    if g.user_role == "Employee":
        rows = [r for r in rows if r["employee_id"] == g.user_id]
    if employee_filter:
        rows = [r for r in rows if r["employee_id"] == employee_filter]
    if case_filter:
        rows = [r for r in rows if r["leave_case_id"] == case_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return R.success_list([S.serialize_ledger(r) for r in page],
                          limit, offset, total)


@bp.route("/leave/benefit-ledgers/<lid>/apply-payment", methods=["POST"])
def apply_payment(lid):
    M.require_roles("HRAdmin")
    ledger = _get_entity(db.ledgers, lid)
    if ledger["payment_status"] in ("PAID", "DELINQUENT"):
        raise APIError(E.ERR_INVALID_STATE,
                       "Ledger is in a terminal state.", 409)
    body = V.require_json(request)
    amount = V.require_field(body, "amount_cents", int)
    if isinstance(amount, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "amount_cents must be integer.", 400)
    outstanding = ledger["employee_premium_share_cents"] - ledger["payments_received_cents"]
    if amount <= 0 or amount > outstanding:
        raise APIError(E.ERR_INVALID_PAYMENT_AMOUNT,
                       "amount_cents must be > 0 and <= outstanding balance.", 422)
    ledger["payments_received_cents"] += amount
    ledger["employee_owes_cents"] = (ledger["employee_premium_share_cents"]
                                     - ledger["payments_received_cents"])
    if ledger["employee_owes_cents"] == 0:
        ledger["payment_status"] = "PAID"
    else:
        ledger["payment_status"] = "PARTIAL"
    services.touch(ledger)
    return R.success(S.serialize_ledger(ledger))


# ===========================================================================
# Notices
# ===========================================================================

@bp.route("/leave/notices/<nid>", methods=["GET"])
def get_notice(nid):
    M.require_roles("HRAdmin", "Employee")
    notice = _get_entity(db.notices, nid)
    if g.user_role == "Employee":
        case = db.leave_cases.get(notice["leave_case_id"])
        if case is None or g.user_id != case["employee_id"]:
            raise APIError(E.ERR_FORBIDDEN,
                           "Employees can only view their own notices.", 403)
    return R.success(S.serialize_notice(notice))


@bp.route("/leave/notices", methods=["GET"])
def list_notices():
    M.require_roles("HRAdmin", "Employee")
    limit, offset = M.pagination_params()
    case_filter = request.args.get("leave_case_id")
    type_filter = request.args.get("notice_type")
    rows = list(db.notices.values())
    if g.user_role == "Employee":
        rows = [r for r in rows
                if (db.leave_cases.get(r["leave_case_id"]) or {}).get("employee_id") == g.user_id]
    if case_filter:
        rows = [r for r in rows if r["leave_case_id"] == case_filter]
    if type_filter:
        rows = [r for r in rows if r["notice_type"] == type_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return R.success_list([S.serialize_notice(r) for r in page],
                          limit, offset, total)


# ===========================================================================
# Test-driving endpoints
# ===========================================================================

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    M.require_roles("PlatformAdmin")
    body = V.require_json(request)
    to_iso = V.require_field(body, "to_iso8601", str)
    try:
        dt = clock.parse_iso8601(to_iso)
    except ValueError:
        raise APIError(E.ERR_INVALID_REQUEST, "to_iso8601 must be valid ISO 8601.", 400)
    clock.set_now(dt)
    flipped = services.auto_delinquency_sweep()
    return R.success({
        "current_utc": clock.iso8601_ms(clock.now_utc()),
        "delinquent_ledger_ids": flipped,
    })


@bp.route("/_intervals/seed-historic", methods=["POST"])
def seed_historic_interval():
    M.require_roles("PlatformAdmin")
    body = V.require_json(request)
    leave_case_id = V.require_field(body, "leave_case_id", str)
    start_dt = V.parse_dt_field(body, "start_datetime")
    end_dt = V.parse_dt_field(body, "end_datetime")
    hours_taken = V.require_field(body, "hours_taken", (int, float))
    if isinstance(hours_taken, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "hours_taken must be numeric.", 400)
    fmla_charged = V.require_field(body, "fmla_hours_charged", (int, float))
    if isinstance(fmla_charged, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "fmla_hours_charged must be numeric.", 400)
    pfl_charged = V.require_field(body, "pfl_hours_charged", (int, float))
    if isinstance(pfl_charged, bool):
        raise APIError(E.ERR_INVALID_REQUEST, "pfl_hours_charged must be numeric.", 400)
    case = _check_fk(db.leave_cases, leave_case_id, "leave_case")
    interval = {
        "leave_case_id": leave_case_id,
        "start_datetime": start_dt,
        "end_datetime": end_dt,
        "hours_taken": hours_taken,
        "fmla_hours_charged": Decimal(str(fmla_charged)),
        "pfl_hours_charged": Decimal(str(pfl_charged)),
        "status": "RECORDED",
    }
    services.init_common(interval)
    db.intervals[interval["id"]] = interval
    case["fmla_hours_charged"] = case["fmla_hours_charged"] + interval["fmla_hours_charged"]
    case["pfl_hours_charged"] = case["pfl_hours_charged"] + interval["pfl_hours_charged"]
    services.touch(case)
    return R.success(S.serialize_interval(interval), status=201)
