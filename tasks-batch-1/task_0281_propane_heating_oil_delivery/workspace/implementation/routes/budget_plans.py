"""BudgetPlan endpoints (PRD §3.10)."""
from flask import Blueprint, request

import db
import errors
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, require_iso_datetime)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L
from services import calculations as C

bp = Blueprint("budget_plans", __name__)


def _budget_under_account(account_id, budget_plan_id):
    acc = L.get_account(account_id)
    bp_rec = L.get_budget_plan(budget_plan_id)
    if bp_rec["account_id"] != acc["id"]:
        raise errors.ApiError(errors.ERR_NOT_FOUND, 404, "Budget plan not under account")
    return acc, bp_rec


@bp.post("/accounts/<account_id>/budget-plans")
def create_budget_plan(account_id):
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Customer"})
    acc = L.get_account(account_id)
    check_owner(role, user_id, acc["id"])
    body = get_json_body()

    plan_year_start = require_iso_datetime(body, "plan_year_start")
    est_gallons = require_int(body, "estimated_annual_gallons", minimum=1)
    est_price = require_int(body, "estimated_price_cents_per_gallon", minimum=1)

    installment = C.monthly_installment(est_gallons, est_price)

    rec = {
        "account_id": acc["id"],
        "plan_year_start": plan_year_start,
        "estimated_annual_gallons": est_gallons,
        "estimated_price_cents_per_gallon": est_price,
        "monthly_installment_cents": installment,
        "installments_paid_count": 0,
        "actual_cost_to_date_cents": 0,
        "status": "ACTIVE",
        "settlement_balance_cents": 0,
    }
    db.stamp_create_full(rec)
    db.budget_plans[rec["id"]] = rec
    return object_response(L.serialize_budget_plan(rec), 201)


@bp.get("/budget-plans/<budget_plan_id>")
def get_budget_plan(budget_plan_id):
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Customer"})
    rec = L.get_budget_plan(budget_plan_id)
    check_owner(role, user_id, rec["account_id"])
    return object_response(L.serialize_budget_plan(rec), 200)


@bp.get("/budget-plans")
def list_budget_plans():
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "Customer"})
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")

    items = list(db.budget_plans.values())
    if role == "Customer":
        items = [b for b in items if b.get("account_id") == user_id]
    if account_id is not None:
        items = [b for b in items if b.get("account_id") == account_id]
    if status is not None:
        items = [b for b in items if b.get("status") == status]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_budget_plan(b) for b in page], limit, offset, total)


@bp.post("/accounts/<account_id>/budget-plans/<budget_plan_id>/post-installment")
def post_installment(account_id, budget_plan_id):
    user_id, role = require_auth()
    require_role(role, {"AccountManager", "System"})
    acc, plan = _budget_under_account(account_id, budget_plan_id)

    if plan["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Budget plan is not ACTIVE")
    if plan["installments_paid_count"] >= 12:
        raise errors.ApiError(errors.ERR_BUDGET_PLAN_FULLY_PAID, 409,
                              "All 12 installments already posted")

    plan["installments_paid_count"] += 1
    acc["credit_balance_cents"] += plan["monthly_installment_cents"]
    plan["settlement_balance_cents"] = C.settlement_balance(
        plan["installments_paid_count"],
        plan["monthly_installment_cents"],
        plan["actual_cost_to_date_cents"])

    db.touch(plan)
    db.touch_no_version(acc)

    return object_response(L.serialize_budget_plan(plan), 200)


@bp.post("/accounts/<account_id>/budget-plans/<budget_plan_id>/reconcile")
def reconcile_budget_plan(account_id, budget_plan_id):
    _, role = require_auth()
    require_role(role, {"AccountManager"})
    acc, plan = _budget_under_account(account_id, budget_plan_id)

    if plan["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_STATE, 409, "Budget plan is not ACTIVE")

    final_settlement = (plan["installments_paid_count"] * plan["monthly_installment_cents"]
                        - plan["actual_cost_to_date_cents"])
    plan["settlement_balance_cents"] = final_settlement
    plan["status"] = "RECONCILED"

    # FINAL true-up: refund the settlement out of the running ledger.
    acc["credit_balance_cents"] -= final_settlement

    db.touch(plan)
    db.touch_no_version(acc)

    return object_response(L.serialize_budget_plan(plan), 200)
