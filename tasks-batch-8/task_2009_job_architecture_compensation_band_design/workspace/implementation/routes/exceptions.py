"""ExceptionRequest lifecycle (§3.8)."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, program_state_forbids, segregation_of_duties,
    ownership_mismatch, referenced_entity_state, department_pool_exhausted,
    reverse_window_expired, exception_rolling_cap, exception_cap_exceeded,
)
from services.common import (
    now_iso, require_fields, parse_int, parse_pagination, sort_by_created_at,
    paginate, bump, round4, round_cents,
    CAP_TIER_LOW, CAP_TIER_MID, CAP_TIER_HIGH,
)
from services import clock
from services.employee_health import (
    recompute_employee_health, recompute_department_payroll,
    recompute_program_payroll, current_program,
)
from services.pricing import _to_date

bp = Blueprint("exceptions", __name__)

ER_STATES = ["SUBMITTED", "HRBP_PASSED", "FINANCE_REVIEW", "APPROVED", "DENIED",
             "RETURNED", "RESCINDED"]
ER_TERMINAL = {"DENIED", "RESCINDED"}
ER_TYPES = ["ABOVE_MAX_HIRE", "BELOW_MIN_RETENTION", "OFF_CYCLE_INCREASE", "GEO_MISMATCH"]
IN_FLIGHT_OR_APPROVED = {"SUBMITTED", "HRBP_PASSED", "FINANCE_REVIEW", "RETURNED", "APPROVED"}


def er_view(r):
    return {k: r[k] for k in ("id", "employee_id", "pay_band_id", "type",
                              "requested_salary_cents", "justification", "status",
                              "finance_required", "pre_exception_salary_cents",
                              "applied_delta_cents", "created_by_user_id",
                              "comp_gate_by_user_id", "applied_at",
                              "created_at", "updated_at", "version")}


def get_er_or_404(rid):
    r = store.exception_requests.get(rid)
    if r is None:
        raise not_found("exception request not found")
    return r


def _check_ownership(user_id, employee):
    if employee["department_id"] != user_id:
        raise ownership_mismatch()


def _rolling_cap_check(employee_id, excluding_id=None):
    """< 2 in-flight-or-approved in trailing 365 days; reject when count would reach 2."""
    now_d = clock.now().date()
    window_start = now_d - timedelta(days=365)
    count = 0
    for r in store.exception_requests.values():
        if r["employee_id"] != employee_id:
            continue
        if excluding_id is not None and r["id"] == excluding_id:
            continue
        if r["status"] not in IN_FLIGHT_OR_APPROVED:
            continue
        created_d = _to_date(r["created_at"])
        if window_start <= created_d <= now_d:
            count += 1
    if count >= 2:
        raise exception_rolling_cap()


def _cap_cents(employee, band):
    r_pre = round4(Decimal(employee["base_salary_cents"]) / Decimal(band["midpoint_cents"]))
    if r_pre < Decimal("1.0000"):
        m = CAP_TIER_LOW
    elif r_pre < Decimal("1.2000"):
        m = CAP_TIER_MID
    else:
        m = CAP_TIER_HIGH
    return round_cents(Decimal(band["max_cents"]) * m)


def _apply_exception(r, employee, user_id):
    """Apply salary: snapshot, set, delta, pool debit, rollups, applied_at."""
    dept = store.departments.get(employee["department_id"])
    band = store.pay_bands.get(r["pay_band_id"])
    cap = _cap_cents(employee, band)
    if r["requested_salary_cents"] > cap:
        raise exception_cap_exceeded()
    delta = r["requested_salary_cents"] - employee["base_salary_cents"]
    positive_delta = max(0, delta)
    if positive_delta > 0:
        headroom = dept["adjustment_pool_cents"] - dept["committed_pool_cents"]
        if positive_delta > headroom:
            raise department_pool_exhausted()
    r["pre_exception_salary_cents"] = employee["base_salary_cents"]
    employee["base_salary_cents"] = r["requested_salary_cents"]
    r["applied_delta_cents"] = delta
    recompute_employee_health(employee)
    bump(employee)
    if dept is not None:
        dept["committed_pool_cents"] += positive_delta
        recompute_department_payroll(dept)
        bump(dept)
    prog = current_program()
    if prog is not None:
        recompute_program_payroll(prog)
        bump(prog)
    r["status"] = "APPROVED"
    r["applied_at"] = clock.now_iso()
    r["comp_gate_by_user_id"] = r.get("comp_gate_by_user_id") or user_id
    bump(r)


@bp.route("/comp/exception-requests", methods=["POST"])
def create_exception():
    user_id, _ = require_roles("DepartmentManager")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["employee_id", "pay_band_id", "type",
                          "requested_salary_cents", "justification"])
    employee_id = body["employee_id"]
    pay_band_id = body["pay_band_id"]
    type_ = body["type"]
    if type_ not in ER_TYPES:
        raise invalid_enum("type is not a declared member")
    requested = parse_int(body["requested_salary_cents"], "requested_salary_cents", minimum=0)
    justification = body["justification"]
    if not isinstance(justification, str) or not justification:
        raise invalid_request("justification must be a non-empty string")
    employee = store.employees.get(employee_id)
    if employee is None:
        raise not_found("employee not found")
    band = store.pay_bands.get(pay_band_id)
    if band is None:
        raise not_found("pay band not found")
    # Ownership (tier 2)
    _check_ownership(user_id, employee)
    # Posture (tier 6)
    prog = store.programs.get(band["comp_program_id"])
    if prog is None:
        raise not_found("comp program not found")
    if prog["status"] != "PUBLISHED":
        raise program_state_forbids("exception create requires program PUBLISHED")
    # Referenced state (tier 10): band PUBLISHED + matches employee family/level/geo
    if band["status"] != "PUBLISHED":
        raise referenced_entity_state("pay band must be PUBLISHED")
    profile = store.job_profiles.get(employee["job_profile_id"])
    if profile is None:
        raise referenced_entity_state("employee profile missing")
    if (band["job_family_id"] != profile["job_family_id"]
            or band["job_level_id"] != profile["job_level_id"]
            or band["geo_zone_id"] != employee["geo_zone_id"]):
        raise referenced_entity_state("band does not match employee family/level/geo")
    # Rolling cap + salary cap (tier 11 / tier 12). Rolling cap is tier 11 (temporal).
    _rolling_cap_check(employee_id)
    cap = _cap_cents(employee, band)
    if requested > cap:
        raise exception_cap_exceeded()
    now = now_iso()
    r = {"id": new_id(), "employee_id": employee_id, "pay_band_id": pay_band_id,
         "type": type_, "requested_salary_cents": requested,
         "justification": justification, "status": "SUBMITTED",
         "finance_required": type_ == "ABOVE_MAX_HIRE",
         "pre_exception_salary_cents": None, "applied_delta_cents": None,
         "created_by_user_id": user_id, "comp_gate_by_user_id": None,
         "applied_at": None,
         "created_at": now, "updated_at": now, "version": 1}
    store.exception_requests[r["id"]] = r
    return success_object(er_view(r), 201)


@bp.route("/comp/exception-requests", methods=["GET"])
def list_exceptions():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.exception_requests.values())
    for arg in ("employee_id", "pay_band_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [r for r in rows if r[arg] == v]
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in ER_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [r for r in rows if r["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([er_view(r) for r in page], limit, offset, total)


@bp.route("/comp/exception-requests/<rid>", methods=["GET"])
def get_exception(rid):
    get_auth()
    return success_object(er_view(get_er_or_404(rid)))


@bp.route("/comp/exception-requests/<rid>/hrbp-pass", methods=["POST"])
def hrbp_pass(rid):
    require_roles("HRBP")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    if r["status"] != "SUBMITTED":
        raise invalid_state_transition("hrbp-pass declared only from SUBMITTED")
    r["status"] = "HRBP_PASSED"
    bump(r)
    return success_object(er_view(r))


@bp.route("/comp/exception-requests/<rid>/comp-pass", methods=["POST"])
def comp_pass(rid):
    user_id, _ = require_roles("CompManager")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    if r["status"] != "HRBP_PASSED":
        raise invalid_state_transition("comp-pass declared only from HRBP_PASSED")
    # SoD (tier 9)
    if r["created_by_user_id"] is not None and user_id == r["created_by_user_id"]:
        raise segregation_of_duties()
    r["comp_gate_by_user_id"] = user_id
    if r["type"] == "ABOVE_MAX_HIRE":
        r["status"] = "FINANCE_REVIEW"
        bump(r)
        return success_object(er_view(r))
    # Non-finance branch: apply directly (cap + fiscal inside)
    employee = store.employees.get(r["employee_id"])
    if employee is None:
        raise not_found("employee not found")
    _apply_exception(r, employee, user_id)
    return success_object(er_view(r))


@bp.route("/comp/exception-requests/<rid>/finance-pass", methods=["POST"])
def finance_pass(rid):
    user_id, _ = require_roles("FinancePartner")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    if r["status"] != "FINANCE_REVIEW":
        raise invalid_state_transition("finance-pass declared only from FINANCE_REVIEW")
    employee = store.employees.get(r["employee_id"])
    if employee is None:
        raise not_found("employee not found")
    _apply_exception(r, employee, user_id)
    return success_object(er_view(r))


@bp.route("/comp/exception-requests/<rid>/deny", methods=["POST"])
def deny_exception(rid):
    user_id, role = require_roles("HRBP", "CompManager", "FinancePartner")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    allowed = False
    if role == "HRBP" and r["status"] == "SUBMITTED":
        allowed = True
    elif role == "CompManager" and r["status"] == "HRBP_PASSED":
        allowed = True
    elif role == "FinancePartner" and r["status"] == "FINANCE_REVIEW":
        allowed = True
    if not allowed:
        raise invalid_state_transition("deny not declared for current state/role")
    r["status"] = "DENIED"
    bump(r)
    return success_object(er_view(r))


@bp.route("/comp/exception-requests/<rid>/return", methods=["POST"])
def return_exception(rid):
    user_id, role = require_roles("HRBP", "CompManager")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    allowed = False
    if role == "HRBP" and r["status"] == "SUBMITTED":
        allowed = True
    elif role == "CompManager" and r["status"] == "HRBP_PASSED":
        allowed = True
    if not allowed:
        raise invalid_state_transition("return not declared for current state/role")
    r["status"] = "RETURNED"
    bump(r)
    return success_object(er_view(r))


@bp.route("/comp/exception-requests/<rid>/resubmit", methods=["POST"])
def resubmit_exception(rid):
    user_id, _ = require_roles("DepartmentManager")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    if r["status"] != "RETURNED":
        raise invalid_state_transition("resubmit declared only from RETURNED")
    employee = store.employees.get(r["employee_id"])
    if employee is None:
        raise not_found("employee not found")
    _check_ownership(user_id, employee)
    # gate history cleared; original created_at retained
    r["comp_gate_by_user_id"] = None
    r["status"] = "SUBMITTED"
    bump(r)
    return success_object(er_view(r))


@bp.route("/comp/exception-requests/<rid>/rescind", methods=["POST"])
def rescind_exception(rid):
    require_roles("CompManager")
    r = get_er_or_404(rid)
    if r["status"] in ER_TERMINAL:
        raise already_terminal("exception request is terminal")
    if r["status"] != "APPROVED":
        raise invalid_state_transition("rescind declared only from APPROVED")
    anchor = _to_date(r["applied_at"])
    now_date = clock.now().date()
    if now_date > anchor + timedelta(days=30):
        raise reverse_window_expired()
    employee = store.employees.get(r["employee_id"])
    if employee is None:
        raise not_found("employee not found")
    employee["base_salary_cents"] = r["pre_exception_salary_cents"]
    recompute_employee_health(employee)
    bump(employee)
    dept = store.departments.get(employee["department_id"])
    if dept is not None:
        delta = r.get("applied_delta_cents") or 0
        if delta > 0:
            dept["committed_pool_cents"] -= delta
        recompute_department_payroll(dept)
        bump(dept)
    prog = current_program()
    if prog is not None:
        recompute_program_payroll(prog)
        bump(prog)
    r["status"] = "RESCINDED"
    bump(r)
    return success_object(er_view(r))
