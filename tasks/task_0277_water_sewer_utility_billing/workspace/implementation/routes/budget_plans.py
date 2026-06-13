"""BudgetBillingPlan routes (PRD §3.7, §2.7 OCC)."""
from flask import Blueprint

import db
import errors
import middleware
from response import object_response, array_response
from services import lookup, ledger, billing
from services.common import (
    get_json_body, require_int, public, public_list, parse_pagination, paginate,
)

bp = Blueprint("budget_plans", __name__)


@bp.post("/accounts/<account_id>/budget-billing-plans")
def enroll(account_id):
    # Customer (own account) or BillingClerk (PRD §3.7).
    middleware.require_role({"Customer", "BillingClerk"})
    account = lookup.account(account_id)
    middleware.require_owner(account_id)
    body = get_json_body()

    monthly_amount = require_int(body, "monthly_amount_cents", minimum=0)
    expected_version = require_int(body, "expected_account_version")

    # OCC (PRD §2.7): expected_account_version must match current version.
    # Runs after state-legality slot (no state precondition here) and before
    # domain rules, per §2.9.
    if expected_version != account["version"]:
        raise errors.err(
            errors.ERR_STALE_ACCOUNT_VERSION,
            "expected_account_version does not match the current account version.",
        )

    # A new plan supersedes any prior ACTIVE plan -> CANCELLED.
    for pl in db.budget_plans.values():
        if pl["account_id"] == account_id and pl["status"] == "ACTIVE":
            pl["status"] = "CANCELLED"
            db.touch(pl)

    rec = db.make_record({
        "account_id": account_id,
        "monthly_amount_cents": monthly_amount,
        # anchor_balance_cents snapshots current balance at enrollment.
        "anchor_balance_cents": account["balance_due_cents"],
        "cycles_elapsed": 0,
        "trued_up_delta_cents": 0,
        "status": "ACTIVE",
    })
    # Internal chronological anchor: bills created after this seq count toward
    # the plan's true-up window (PRD §3.7 "since enrollment").
    rec["_enroll_seq"] = db.next_seq()
    db.budget_plans[rec["id"]] = rec

    # Enrollment increments the account's version by one and refreshes derived
    # flags (budget_billing_enrolled becomes true).
    ledger.reconcile(account)
    return object_response(public(rec), 201)


@bp.get("/accounts/<account_id>/budget-billing-plans")
def list_plans(account_id):
    middleware.require_role({"BillingClerk", "Customer"})
    lookup.account(account_id)
    middleware.require_owner(account_id)
    limit, offset = parse_pagination()

    records = [p for p in db.budget_plans.values() if p["account_id"] == account_id]
    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@bp.post("/budget-billing-plans/<rid>/true-up")
def true_up(rid):
    middleware.require_role({"BillingClerk"})
    plan = lookup.budget_plan(rid)

    # True-up is defined only from ACTIVE (TRUED_UP/CANCELLED are end states).
    if plan["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE plan may be trued up.")

    account = db.accounts[plan["account_id"]]
    # Chronological actual-vs-installment delta (PRD §3.7).
    billing.recompute_plan_trueup(plan)
    delta = plan["trued_up_delta_cents"]
    plan["status"] = "TRUED_UP"
    db.touch(plan)

    # Delta posts to the account ledger as an adjustment to balance_due_cents.
    account["_trueup_adjustment_cents"] = account.get("_trueup_adjustment_cents", 0) + delta
    ledger.reconcile(account)
    return object_response(public(plan), 200)
