"""Employee routes + employee-scoped lookups (eligibility, quota, leave-cases)."""
from __future__ import annotations

from datetime import date
from flask import Blueprint, jsonify, request

from ..auth import ensure_employee_owns, require_roles
from ..clock import format_datetime_ms, get_clock, parse_iso_date, parse_iso_datetime
from ..common import (
    optional_str,
    parse_json_body,
    require_enum,
    require_int,
    require_str,
    strip_internal,
)
from ..errors import (
    err_employee_terminated,
    err_invalid_state,
    err_not_eligible_hours,
    err_not_eligible_tenure,
    err_not_eligible_worksite,
    err_not_found,
    err_pfl_mismatch,
    err_pfl_not_available,
    err_validation,
)
from ..pagination import parse_pagination, slice_page
from ..response import make_array_envelope, make_object_envelope
from ..services import calculations as calc
from ..services.leave_case_service import (
    bump_version,
    cert_deadline_iso,
    compute_leave_year_anchor,
    view_case,
)
from ..audit import emit_audit
from ..store import get_store, new_id


bp_employees = Blueprint("employees", __name__)


# -----------------------------------------------------------------------------
# Employee CRUD
# -----------------------------------------------------------------------------
@bp_employees.route("/employers/<employer_id>/employees", methods=["POST"])
@require_roles("ComplianceOfficer", "HRSpecialist")
def create_employee(user_id: str, role: str, employer_id: str):
    store = get_store()
    if employer_id not in store.employers:
        raise err_not_found("Employer not found.")
    body = parse_json_body()
    worksite_id = require_str(body, "worksite_id")
    worksite = store.worksites.get(worksite_id)
    if worksite is None or worksite["employer_id"] != employer_id:
        raise err_not_found("Worksite not found under this employer.")
    full_name = require_str(body, "full_name")
    hire_date = require_str(body, "hire_date")
    try:
        parse_iso_date(hire_date)
    except Exception:
        raise err_validation("hire_date must be ISO 8601 date.")
    hours = require_int(body, "hours_worked_trailing_12mo", minimum=0)
    wage = require_int(body, "monthly_wage_cents", minimum=0)

    now_iso = format_datetime_ms(get_clock().get())
    eid = new_id()
    row = {
        "id": eid,
        "employer_id": employer_id,
        "worksite_id": worksite_id,
        "full_name": full_name,
        "hire_date": hire_date,
        "hours_worked_trailing_12mo": hours,
        "monthly_wage_cents": wage,
        "employment_status": "ACTIVE",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.employees[eid] = row
    return jsonify(make_object_envelope(strip_internal(row))), 201


@bp_employees.route("/employees/<employee_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "HRSpecialist", "Employee")
def get_employee(user_id: str, role: str, employee_id: str):
    store = get_store()
    row = store.employees.get(employee_id)
    if row is None:
        raise err_not_found("Employee not found.")
    ensure_employee_owns(user_id, role, employee_id)
    return jsonify(make_object_envelope(strip_internal(row))), 200


@bp_employees.route("/employees/<employee_id>/hours-snapshot", methods=["POST"])
@require_roles("HRSpecialist")
def hours_snapshot(user_id: str, role: str, employee_id: str):
    store = get_store()
    row = store.employees.get(employee_id)
    if row is None:
        raise err_not_found("Employee not found.")
    body = parse_json_body()
    hours = require_int(body, "hours_worked_trailing_12mo", minimum=0)
    row["hours_worked_trailing_12mo"] = hours
    bump_version(row)
    return jsonify(make_object_envelope(strip_internal(row))), 200


# -----------------------------------------------------------------------------
# Eligibility snapshot
# -----------------------------------------------------------------------------
@bp_employees.route("/employees/<employee_id>/eligibility-snapshot", methods=["GET"])
@require_roles("HRSpecialist", "Employee")
def eligibility_snapshot(user_id: str, role: str, employee_id: str):
    store = get_store()
    emp = store.employees.get(employee_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    ensure_employee_owns(user_id, role, employee_id)
    worksite = store.worksites.get(emp["worksite_id"])
    if worksite is None:
        raise err_not_found("Worksite not found.")
    eligible, reason_code, details = calc.evaluate_eligibility(emp, worksite, get_clock().get())
    payload = {
        "eligible": eligible,
        "reason_code": reason_code,
        "months_of_service": details["months_of_service"],
        "hours_trailing": details["hours_trailing"],
        "worksite_headcount": details["worksite_headcount"],
    }
    return jsonify(make_object_envelope(payload)), 200


# -----------------------------------------------------------------------------
# Quota balance
# -----------------------------------------------------------------------------
@bp_employees.route("/employees/<employee_id>/quota-balance", methods=["GET"])
@require_roles("HRSpecialist", "Employee")
def quota_balance(user_id: str, role: str, employee_id: str):
    store = get_store()
    emp = store.employees.get(employee_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    ensure_employee_owns(user_id, role, employee_id)
    employer = store.employers.get(emp["employer_id"])
    if employer is None:
        raise err_not_found("Employer not found.")
    raw_as_of = request.args.get("as_of_date")
    if raw_as_of:
        try:
            anchor = parse_iso_date(raw_as_of)
        except Exception:
            raise err_validation("as_of_date must be an ISO 8601 date.")
    else:
        anchor = get_clock().get().date()
    consumed, remaining, win_start, win_end = calc.remaining_hours_for_employee(
        store, employee_id, employer["leave_year_basis"], anchor
    )
    payload = {
        "basis": employer["leave_year_basis"],
        "window_start": win_start.isoformat(),
        "window_end": win_end.isoformat(),
        "consumed_hours": consumed,
        "remaining_hours": remaining,
    }
    return jsonify(make_object_envelope(payload)), 200


# -----------------------------------------------------------------------------
# Leave-case submission + list
# -----------------------------------------------------------------------------
LEAVE_REASONS = {"OWN_SERIOUS_HEALTH", "FAMILY_SERIOUS_HEALTH", "BABY_BONDING", "MILITARY_EXIGENCY"}
LEAVE_PATTERNS = {"CONTINUOUS", "INTERMITTENT", "REDUCED_SCHEDULE"}


@bp_employees.route("/employees/<employee_id>/leave-cases", methods=["POST"])
@require_roles("Employee", "HRSpecialist")
def submit_leave_case(user_id: str, role: str, employee_id: str):
    store = get_store()
    emp = store.employees.get(employee_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    ensure_employee_owns(user_id, role, employee_id)

    # State guard (priority 9): not TERMINATED
    if emp["employment_status"] == "TERMINATED":
        raise err_employee_terminated()
    # Also require ACTIVE per state machine precondition (employment_status == ACTIVE)
    if emp["employment_status"] != "ACTIVE":
        raise err_invalid_state("Employee employment_status must be ACTIVE for new submissions.")

    employer = store.employers.get(emp["employer_id"])
    worksite = store.worksites.get(emp["worksite_id"])
    if employer is None or worksite is None:
        raise err_not_found("Employer/worksite reference broken.")

    # Body parsing (priority 23 — last)
    body = parse_json_body()
    reason = require_enum(body, "reason", LEAVE_REASONS)
    leave_pattern = require_enum(body, "leave_pattern", LEAVE_PATTERNS)
    req_start = require_str(body, "requested_start_date")
    exp_end = require_str(body, "expected_end_date")
    try:
        req_start_date = parse_iso_date(req_start)
        exp_end_date = parse_iso_date(exp_end)
    except Exception:
        raise err_validation("requested_start_date and expected_end_date must be ISO 8601 dates.")
    today = get_clock().get().date()
    if req_start_date < today:
        raise err_validation("requested_start_date must be at or after today.")
    if exp_end_date < req_start_date:
        raise err_validation("expected_end_date must be at or after requested_start_date.")
    pfl_claim_id = optional_str(body, "pfl_claim_id", None)

    # Eligibility — priority 10/11/12 (after schema parsing? PRD §2.6 places body schema last)
    eligible, reason_code, details = calc.evaluate_eligibility(emp, worksite, get_clock().get())
    if not eligible:
        if reason_code == "ERR_NOT_ELIGIBLE_TENURE":
            raise err_not_eligible_tenure()
        if reason_code == "ERR_NOT_ELIGIBLE_HOURS":
            raise err_not_eligible_hours()
        if reason_code == "ERR_NOT_ELIGIBLE_WORKSITE":
            raise err_not_eligible_worksite()

    # PFL linkage validation (priority 18, 19)
    if pfl_claim_id is not None:
        claim = store.pfl_claims.get(pfl_claim_id)
        if claim is None:
            raise err_not_found("Referenced PfLClaim not found.")
        if employer.get("state_pfl_program") != "STATE_PFL_8WEEK":
            raise err_pfl_not_available()
        if claim["employee_id"] != employee_id:
            raise err_pfl_mismatch()
        # Alignment: FAMILY_CARE↔FAMILY_SERIOUS_HEALTH, BABY_BONDING↔BABY_BONDING
        alignment = {
            "FAMILY_CARE": "FAMILY_SERIOUS_HEALTH",
            "BABY_BONDING": "BABY_BONDING",
        }
        if alignment.get(claim["claim_type"]) != reason:
            raise err_pfl_mismatch()

    # Create the case
    now_iso = format_datetime_ms(get_clock().get())
    cid = new_id()
    cert_status = "AWAITING_DOC" if reason in {"OWN_SERIOUS_HEALTH", "FAMILY_SERIOUS_HEALTH"} else "NOT_REQUIRED"
    leave_year_anchor = compute_leave_year_anchor(employer["leave_year_basis"], req_start)
    case = {
        "id": cid,
        "employee_id": employee_id,
        "reason": reason,
        "leave_pattern": leave_pattern,
        "case_status": "PENDING_CERTIFICATION",
        "certification_status": cert_status,
        "requested_start_date": req_start,
        "expected_end_date": exp_end,
        "leave_year_anchor": leave_year_anchor,
        "pfl_claim_id": pfl_claim_id,
        "cert_deadline": cert_deadline_iso(now_iso),
        "hours_charged": 0,
        "job_restoration_status": "PROTECTED",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.leave_cases[cid] = case

    emit_audit(cid, "ELIGIBILITY_CHECKED", role, {"eligible": True, "details": details})
    emit_audit(cid, "CASE_CREATED", role, {"reason": reason, "leave_pattern": leave_pattern})

    return jsonify(make_object_envelope(view_case(case))), 201


@bp_employees.route("/employees/<employee_id>/leave-cases", methods=["GET"])
@require_roles("Employee", "HRSpecialist", "ComplianceOfficer")
def list_employee_leave_cases(user_id: str, role: str, employee_id: str):
    store = get_store()
    emp = store.employees.get(employee_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    ensure_employee_owns(user_id, role, employee_id)
    limit, offset = parse_pagination()
    case_status_filter = request.args.get("case_status")
    rows = [c for c in store.leave_cases.values() if c["employee_id"] == employee_id]
    if case_status_filter:
        rows = [c for c in rows if c["case_status"] == case_status_filter]
    rows.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
    total = len(rows)
    page = slice_page(rows, limit, offset)
    items = [view_case(c) for c in page]
    return jsonify(make_array_envelope(items, limit=limit, offset=offset, total_count=total)), 200
