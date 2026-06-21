"""BudgetBillingPlan endpoints: enroll, true-up (OCC), cancel, reads (PRD §3.7)."""
from flask import Blueprint, request

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles, require_owner
from response import success
from services import serializers as ser
from services.common import (
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
)

bp = Blueprint("budget_plans", __name__)

READ_ROLES = {"BillingOperator", "Customer"}


@bp.route("/budget-plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()
    require_fields(body, ["account_id", "levelized_amount_cents"])
    account_id = body["account_id"]
    levelized = require_int(body, "levelized_amount_cents")

    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced account does not exist.")

    if levelized <= 0:
        raise err("ERR_VALIDATION_RANGE", "levelized_amount_cents must be > 0.")

    # At most one ACTIVE plan per account.
    for p in db.budget_plans.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            raise err("ERR_BUDGET_PLAN_EXISTS", "Account already has an ACTIVE plan.")

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "status": "ACTIVE",
        "levelized_amount_cents": levelized,
        "accumulated_actual_cents": 0,
        "accumulated_levelized_cents": 0,
        "true_up_balance_cents": 0,
    })
    db.budget_plans[rec["id"]] = rec
    account["budget_plan_id"] = rec["id"]
    touch(account)
    return success(ser.budget_plan(rec), status=201)


def _settle(plan, account, new_status):
    """Compute true_up_balance and adjust account balance, then move plan to the
    given terminal status and clear the account pointer (PRD §3.7)."""
    delta = plan["accumulated_actual_cents"] - plan["accumulated_levelized_cents"]
    plan["true_up_balance_cents"] = delta
    account["balance_cents"] += delta
    plan["status"] = new_status
    touch(plan)
    if account["budget_plan_id"] == plan["id"]:
        account["budget_plan_id"] = None


@bp.route("/budget-plans/<plan_id>/true-up", methods=["POST"])
def true_up_plan(plan_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    plan = db.budget_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Budget plan not found.")
    body = get_json_body()
    require_fields(body, ["expected_account_version"])
    expected_version = require_int(body, "expected_account_version")

    account = db.accounts.get(plan["account_id"])

    # State check (priority 9) before OCC (priority 17).
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE plan can be trued up.")
    if expected_version != account["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "Account version is stale.")

    _settle(plan, account, "TRUED_UP")
    touch(account)  # increments Account.version (PRD §3.7)
    return success(ser.budget_plan(plan), status=200)


@bp.route("/budget-plans/<plan_id>/cancel", methods=["POST"])
def cancel_plan(plan_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    plan = db.budget_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Budget plan not found.")
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE plan can be cancelled.")

    account = db.accounts.get(plan["account_id"])
    _settle(plan, account, "CANCELLED")
    touch(account)  # increments Account.version (PRD §3.7)
    return success(ser.budget_plan(plan), status=200)


@bp.route("/budget-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    plan = db.budget_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Budget plan not found.")
    require_owner(role, user_id, plan["account_id"])
    return success(ser.budget_plan(plan), status=200)


@bp.route("/budget-plans", methods=["GET"])
def list_plans():
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.budget_plans.values())
    if role == "Customer":
        items = [p for p in items if p["account_id"] == user_id]
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pagination = paginate(items)
    return success([ser.budget_plan(p) for p in page], status=200, pagination=pagination)
