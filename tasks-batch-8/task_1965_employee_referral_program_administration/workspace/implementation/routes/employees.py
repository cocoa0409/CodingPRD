"""Employee roster, offboarding cascade, and 1:1 tax profiles."""

from flask import Blueprint, request, g

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_FORBIDDEN,
                    ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_ALREADY_TERMINAL)
from middleware import require_role, ALL_ROLES
import services as svc
from services import new_entity, touch
from util import (req_str, opt_str, opt_bool, req_dt, opt_int, check_enum,
                  respond_object, respond_list, parse_pagination, paginate)
from views import employee_view, tax_profile_view, referral_view, abuse_case_view

bp = Blueprint("employees", __name__)

READ_ROLES = tuple(ALL_ROLES)


def _get_employee(emp_id):
    e = store.employees.get(emp_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Employee not found")
    return e


@bp.post("/erp/employees")
def create_employee():
    body = request.get_json(silent=True) or {}
    # Pipeline step 2: shape
    employee_number = req_str(body, "employee_number")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    department = req_str(body, "department")
    job_level = body.get("job_level")
    if not isinstance(job_level, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: job_level")
    hire_date = req_dt(body, "hire_date")
    is_recruiter = opt_bool(body, "is_recruiter", False)
    # Pipeline step 3: enum membership
    check_enum(job_level, svc.JOB_LEVELS, "job_level")
    # Pipeline step 4: role
    require_role("PlatformAdmin")
    # Uniqueness of employee_number
    for e in store.employees.values():
        if e["employee_number"] == employee_number:
            raise ApiError(ERR_INVALID_REQUEST, 400, "employee_number must be unique")
    emp = new_entity(store.employees, {
        "employee_number": employee_number,
        "full_name": full_name,
        "email": email,
        "department": department,
        "job_level": job_level,
        "is_recruiter": is_recruiter,
        "hire_date": hire_date,
        "employment_status": "ACTIVE",
        "terminated_at": None,
        "fraud_strikes": 0,
    })
    return respond_object(employee_view(emp), status=201)


@bp.get("/erp/employees")
def list_employees():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.employees.values())
    department = request.args.get("department")
    job_level = request.args.get("job_level")
    employment_status = request.args.get("employment_status")
    if department is not None:
        items = [e for e in items if e["department"] == department]
    if job_level is not None:
        items = [e for e in items if e["job_level"] == job_level]
    if employment_status is not None:
        items = [e for e in items if e["employment_status"] == employment_status]
    page, total = paginate(items, limit, offset)
    return respond_list([employee_view(e) for e in page], total, limit, offset)


@bp.get("/erp/employees/<emp_id>")
def get_employee(emp_id):
    require_role(*READ_ROLES)
    emp = _get_employee(emp_id)
    return respond_object(employee_view(emp))


@bp.post("/erp/employees/<emp_id>/terminate")
def terminate_employee(emp_id):
    require_role("PlatformAdmin")
    emp = _get_employee(emp_id)
    if emp["employment_status"] == "TERMINATED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Employee is already TERMINATED")
    emp["employment_status"] = "TERMINATED"
    emp["terminated_at"] = store.clock
    touch(emp)
    # Cascade: forfeit this referrer's unpaid milestones (EARNED/APPROVED/BATCHED).
    affected_referrals = [r for r in store.referrals.values() if r["referrer_id"] == emp["id"]]
    forfeited_referrals = set()
    for r in affected_referrals:
        for m in svc.milestones_of(r["id"]):
            if m["status"] in ("EARNED", "APPROVED", "BATCHED"):
                svc.forfeit_milestone(m, r)
                forfeited_referrals.add(r["id"])
    # Each forfeiture also releases the referral's remaining campaign reservation.
    for rid in forfeited_referrals:
        svc.release_referral_reservation(store.referrals[rid])
    return respond_object(employee_view(emp))


# ---------------------------------------------------------------------------
# Tax profile (1:1 with Employee)
# ---------------------------------------------------------------------------

@bp.put("/erp/employees/<emp_id>/tax-profile")
def upsert_tax_profile(emp_id):
    body = request.get_json(silent=True) or {}
    # Step 2: shape
    filing_status = body.get("filing_status")
    if not isinstance(filing_status, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: filing_status")
    withholding_method = body.get("withholding_method")
    if not isinstance(withholding_method, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: withholding_method")
    supplemental_rate_bps = opt_int(body, "supplemental_rate_bps", None)
    ytd_carryover_cents = opt_int(body, "ytd_carryover_cents", 0)
    # Step 3: enums
    check_enum(filing_status, svc.FILING_STATUSES, "filing_status")
    check_enum(withholding_method, svc.WITHHOLDING_METHODS, "withholding_method")
    # Step 4: role
    require_role("Employee", "PayrollProcessor")
    # Step 5: ownership (Employee acts only on its own record)
    if g.role == "Employee" and g.user_id != emp_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Employee may only update its own tax profile")
    # Step 6: existence
    _get_employee(emp_id)
    profile = store.tax_profiles.get(emp_id)
    if profile is None:
        # tax_profiles is keyed by employee_id (1:1 with Employee)
        holder = {}
        profile = new_entity(holder, {
            "employee_id": emp_id,
            "filing_status": filing_status,
            "withholding_method": withholding_method,
            "supplemental_rate_bps": supplemental_rate_bps,
            "ytd_carryover_cents": ytd_carryover_cents,
            "status": "SUBMITTED",
        })
        store.tax_profiles[emp_id] = profile
    else:
        profile["filing_status"] = filing_status
        profile["withholding_method"] = withholding_method
        profile["supplemental_rate_bps"] = supplemental_rate_bps
        profile["ytd_carryover_cents"] = ytd_carryover_cents
        # Any update re-opens verification; ytd_paid_gross_cents is derived
        # from milestone payment history and preserved.
        profile["status"] = "SUBMITTED"
        touch(profile)
    return respond_object(tax_profile_view(profile))


@bp.post("/erp/employees/<emp_id>/tax-profile/verify")
def verify_tax_profile(emp_id):
    require_role("PayrollProcessor")
    _get_employee(emp_id)
    profile = store.tax_profiles.get(emp_id)
    if profile is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Tax profile not found")
    if profile["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Tax profile cannot be verified from status %s" % profile["status"])
    profile["status"] = "VERIFIED"
    touch(profile)
    return respond_object(tax_profile_view(profile))


@bp.get("/erp/employees/<emp_id>/tax-profile")
def get_tax_profile(emp_id):
    require_role("Employee", "PayrollProcessor", "TalentAdmin")
    if g.role == "Employee" and g.user_id != emp_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Employee may only read its own tax profile")
    _get_employee(emp_id)
    limit, offset = parse_pagination(request.args)
    profile = store.tax_profiles.get(emp_id)
    items = [profile] if profile is not None else []
    page, total = paginate(items, limit, offset)
    return respond_list([tax_profile_view(p) for p in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Employee subordinate views
# ---------------------------------------------------------------------------

@bp.get("/erp/employees/<emp_id>/referrals")
def employee_referrals(emp_id):
    require_role(*READ_ROLES)
    if g.role == "Employee" and g.user_id != emp_id:
        raise ApiError(ERR_FORBIDDEN, 403, "Employee may only read its own referrals")
    _get_employee(emp_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [r for r in svc.sort_by_created(store.referrals.values())
             if r["referrer_id"] == emp_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([referral_view(r) for r in page], total, limit, offset)


@bp.get("/erp/employees/<emp_id>/abuse-cases")
def employee_abuse_cases(emp_id):
    require_role("PlatformAdmin", "TalentAdmin", "ComplianceOfficer")
    _get_employee(emp_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [c for c in svc.sort_by_created(store.abuse_cases.values())
             if c["employee_id"] == emp_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([abuse_case_view(c) for c in page], total, limit, offset)
