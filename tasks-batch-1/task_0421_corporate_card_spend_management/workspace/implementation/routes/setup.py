"""Routes for Company, clock, SpendPolicy, Employee, GlAccount."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch, LOCK
from middleware import get_user_context, require_role, get_json_body
from response import success, success_list
from services.common import (
    get_or_404, require_fields, validate_enum, paginate, serialize,
    recompute_available_credit, to_dt, q as _q, filter_items as _filter,
)
from services.statements import open_new_statement, evaluate_past_due_for_company

bp = Blueprint("setup", __name__)


# ----------------------------------------------------------------- Company
@bp.route("/companies", methods=["POST"])
def create_company():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["legal_name", "credit_limit_cents", "billing_model"])
    validate_enum(body, "billing_model", {"CHARGE", "CREDIT"})
    credit_limit = body["credit_limit_cents"]
    if not isinstance(credit_limit, int) or isinstance(credit_limit, bool):
        raise errors.err(errors.ERR_VALIDATION, "credit_limit_cents must be an integer.")

    with LOCK:
        company = {
            "legal_name": body["legal_name"],
            "currency": body.get("currency", "USD"),
            "credit_limit_cents": credit_limit,
            "billing_model": body["billing_model"],
            "minimum_payment_pct": body.get("minimum_payment_pct", 0.10),
            "reward_rate_default_bps": body.get("reward_rate_default_bps", 100),
            "available_credit_cents": credit_limit,
            "clock_utc": None,
            "status": "ACTIVE",
        }
        stamp_create(company)
        db.companies[company["id"]] = company

        # CASCADE: RewardAccount with zero balances.
        ra = {
            "company_id": company["id"],
            "accrued_points_cents": 0,
            "redeemed_points_cents": 0,
            "balance_points_cents": 0,
        }
        stamp_create(ra)
        db.reward_accounts[ra["id"]] = ra

        # CASCADE: first OPEN statement (cycle_index=1, opened_at null).
        open_new_statement(company, cycle_index=1)

    return success(serialize(company), 201)


@bp.route("/companies/<company_id>", methods=["GET"])
def get_company(company_id):
    get_user_context()
    with LOCK:
        company = get_or_404(db.companies, company_id)
        recompute_available_credit(company)
        return success(serialize(company), 200)


@bp.route("/companies", methods=["GET"])
def list_companies():
    get_user_context()
    with LOCK:
        items = list(db.companies.values())
        status = _q("status")
        if status is not None:
            items = [c for c in items if c["status"] == status]
        for c in items:
            recompute_available_credit(c)
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/companies/<company_id>/suspend", methods=["POST"])
def suspend_company(company_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()  # reason? optional
    with LOCK:
        company = get_or_404(db.companies, company_id)
        company["status"] = "SUSPENDED"
        touch(company)
        recompute_available_credit(company)
        return success(serialize(company), 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "to_iso8601"])
    with LOCK:
        company = get_or_404(db.companies, body["company_id"])
        # Validate datetime well-formedness.
        to_dt(body["to_iso8601"])
        company["clock_utc"] = body["to_iso8601"]
        touch(company)
        # CASCADE: DUE -> PAST_DUE sweep.
        evaluate_past_due_for_company(company)
        recompute_available_credit(company)
        return success(serialize(company), 200)


# ----------------------------------------------------------------- SpendPolicy
@bp.route("/spend-policies", methods=["POST"])
def create_spend_policy():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "name",
                          "per_transaction_limit_cents", "approval_threshold_cents"])
    with LOCK:
        get_or_404(db.companies, body["company_id"])
        policy = {
            "company_id": body["company_id"],
            "name": body["name"],
            "per_transaction_limit_cents": body["per_transaction_limit_cents"],
            "approval_threshold_cents": body["approval_threshold_cents"],
            "blocked_mcc_codes": body.get("blocked_mcc_codes", []) or [],
            "mcc_reward_overrides": body.get("mcc_reward_overrides", []) or [],
            "status": "ACTIVE",
        }
        stamp_create(policy)
        db.spend_policies[policy["id"]] = policy
        return success(serialize(policy), 201)


@bp.route("/spend-policies/<policy_id>", methods=["GET"])
def get_spend_policy(policy_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.spend_policies, policy_id)), 200)


@bp.route("/spend-policies", methods=["GET"])
def list_spend_policies():
    get_user_context()
    with LOCK:
        items = list(db.spend_policies.values())
        items = _filter(items, {"company_id": _q("company_id"), "status": _q("status")})
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


# ----------------------------------------------------------------- Employee
@bp.route("/employees", methods=["POST"])
def create_employee():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "email", "full_name", "employee_role"])
    validate_enum(body, "employee_role", {"CARDHOLDER", "APPROVER", "FINANCE_ADMIN"})
    with LOCK:
        get_or_404(db.companies, body["company_id"])
        mgr = body.get("manager_employee_id")
        if mgr is not None:
            get_or_404(db.employees, mgr)
        # email unique among ACTIVE employees of the company
        for e in db.employees.values():
            if (e["company_id"] == body["company_id"]
                    and e["status"] == "ACTIVE"
                    and e["email"] == body["email"]):
                raise errors.err(errors.ERR_DUPLICATE_EMAIL,
                                 "Email already in use among active employees.")
        emp = {
            "company_id": body["company_id"],
            "email": body["email"],
            "full_name": body["full_name"],
            "employee_role": body["employee_role"],
            "manager_employee_id": mgr,
            "status": "ACTIVE",
        }
        stamp_create(emp)
        db.employees[emp["id"]] = emp
        return success(serialize(emp), 201)


@bp.route("/employees/<employee_id>", methods=["GET"])
def get_employee(employee_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.employees, employee_id)), 200)


@bp.route("/employees", methods=["GET"])
def list_employees():
    get_user_context()
    with LOCK:
        items = list(db.employees.values())
        items = _filter(items, {
            "company_id": _q("company_id"),
            "manager_employee_id": _q("manager_employee_id"),
            "employee_role": _q("employee_role"),
            "status": _q("status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


# ----------------------------------------------------------------- GlAccount
@bp.route("/gl-accounts", methods=["POST"])
def create_gl_account():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["company_id", "gl_code", "name"])
    with LOCK:
        get_or_404(db.companies, body["company_id"])
        for g in db.gl_accounts.values():
            if (g["company_id"] == body["company_id"]
                    and g["status"] == "ACTIVE"
                    and g["gl_code"] == body["gl_code"]):
                raise errors.err(errors.ERR_DUPLICATE_GL_CODE,
                                 "GL code already in use among active accounts.")
        gl = {
            "company_id": body["company_id"],
            "gl_code": body["gl_code"],
            "name": body["name"],
            "status": "ACTIVE",
        }
        stamp_create(gl)
        db.gl_accounts[gl["id"]] = gl
        return success(serialize(gl), 201)


@bp.route("/gl-accounts/<gl_id>", methods=["GET"])
def get_gl_account(gl_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.gl_accounts, gl_id)), 200)


@bp.route("/gl-accounts", methods=["GET"])
def list_gl_accounts():
    get_user_context()
    with LOCK:
        items = list(db.gl_accounts.values())
        items = _filter(items, {"company_id": _q("company_id"), "status": _q("status")})
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


