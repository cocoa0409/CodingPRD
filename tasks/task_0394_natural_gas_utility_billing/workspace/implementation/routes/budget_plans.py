"""Budget plan endpoints (PRD §3.7)."""

from flask import Blueprint

from db import store
from errors import (
    ERR_STALE_ACCOUNT_VERSION,
    ERR_BUDGET_PERIOD_OVERLAP,
    ERR_INVALID_STATE,
    ERR_NO_BILLS_TO_TRUE_UP,
    err,
)
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_month,
    require_int,
    attach_common_fields,
    bump,
    paginate,
)
from services.serialize import view_budget_plan
from services import lookup, calc

bp = Blueprint("budget_plans", __name__)

BUDGET_MONTHS = calc.BUDGET_MONTHS


def _month_index(month_str):
    """Convert YYYY-MM to an absolute month integer for window math."""
    y, m = month_str.split("-")
    return int(y) * 12 + (int(m) - 1)


@bp.route("/accounts/<account_id>/budget-plans", methods=["POST"])
def create_budget_plan(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        body = get_body()
        require_fields(body, ["anchor_month", "projected_annual_cents", "expected_account_version"])
        anchor_month = require_month(body, "anchor_month")
        projected_annual_cents = require_int(body, "projected_annual_cents", minimum=0)
        expected = require_int(body, "expected_account_version")

        # Coverage-window overlap (priority 5.2): half-open interval on same account.
        new_start = _month_index(anchor_month)
        new_end = new_start + BUDGET_MONTHS  # exclusive
        for p in store.budget_plans.values():
            if p["account_id"] != account_id or p["status"] != "ACTIVE":
                continue
            ex_start = _month_index(p["anchor_month"])
            ex_end = ex_start + BUDGET_MONTHS
            # Half-open overlap: [a,b) and [c,d) overlap iff a < d and c < b.
            if new_start < ex_end and ex_start < new_end:
                raise err(ERR_BUDGET_PERIOD_OVERLAP, "Budget plan window overlaps an active plan")

        # OCC (priority 11).
        if expected != account["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "expected_account_version does not match current account version")

        monthly = calc.compute_monthly_installment(projected_annual_cents)
        rec = {
            "account_id": account_id,
            "anchor_month": anchor_month,
            "monthly_installment_cents": monthly,
            "projected_annual_cents": projected_annual_cents,
            "accrued_actual_cents": 0,
            "accrued_budget_cents": 0,
            "status": "ACTIVE",
            "trueup_balance_cents": 0,
        }
        attach_common_fields(rec)
        store.budget_plans[rec["id"]] = rec

        account["budget_enrolled"] = True
        bump(account)

        return success(view_budget_plan(rec), 201)


@bp.route("/accounts/<account_id>/budget-plans", methods=["GET"])
def list_budget_plans(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    account = lookup.get_account(account_id)
    require_account_ownership(principal, account_id)
    records = [p for p in store.budget_plans.values() if p["account_id"] == account_id]
    page, list_meta = paginate(records)
    return success([view_budget_plan(p) for p in page], 200, list_meta=list_meta)


def compute_plan_accruals(plan):
    """Sum amount_due_cents and budget_billed_cents over bills under this plan
    (status ISSUED or PAID, service_month >= anchor_month), ordered by
    service_month then created_at (PRD §3.7)."""
    account_id = plan["account_id"]
    anchor = plan["anchor_month"]
    bills = [b for b in store.bills.values()
             if b["account_id"] == account_id
             and b["status"] in ("ISSUED", "PAID")
             and b.get("service_month") is not None
             and b["service_month"] >= anchor]
    bills.sort(key=lambda b: (b["service_month"], b["_seq"]))
    accrued_actual = sum(b["amount_due_cents"] for b in bills)
    accrued_budget = sum(b["budget_billed_cents"] for b in bills)
    return accrued_actual, accrued_budget


def create_trueup_bill(account, plan, balance_cents):
    """Create a residual DRAFT true-up bill (PRD §3.7).

    balance_cents > 0 => debit bill the customer owes (amount_due_cents = balance).
    balance_cents < 0 => credit bill (negative net) reducing the balance.
    """
    rec = {
        "account_id": account["id"],
        "service_month": plan["anchor_month"],
        "from_read_id": None,
        "to_read_id": None,
        "corrects_bill_id": None,
        "therms_billed": 0,
        "commodity_charge_cents": 0,
        "distribution_charge_cents": 0,
        "fixed_charge_cents": 0,
        "low_income_credit_cents": 0,
        "amount_due_cents": balance_cents,
        "budget_billed_cents": balance_cents,
        "status": "DRAFT",
        "due_date": None,
        "paid_cents": 0,
    }
    attach_common_fields(rec)
    store.bills[rec["id"]] = rec
    return rec


@bp.route("/accounts/<account_id>/budget-plans/<plan_id>/true-up", methods=["POST"])
def true_up(account_id, plan_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        plan = lookup.get_budget_plan_under_account(account_id, plan_id)
        if plan["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")

        # Require at least one bill issued under this plan.
        accrued_actual, accrued_budget = compute_plan_accruals(plan)
        has_bill = any(
            b["account_id"] == account_id
            and b["status"] in ("ISSUED", "PAID")
            and b.get("service_month") is not None
            and b["service_month"] >= plan["anchor_month"]
            for b in store.bills.values()
        )
        if not has_bill:
            raise err(ERR_NO_BILLS_TO_TRUE_UP, "No bills issued under this plan")

        plan["accrued_actual_cents"] = accrued_actual
        plan["accrued_budget_cents"] = accrued_budget
        plan["trueup_balance_cents"] = accrued_actual - accrued_budget
        plan["status"] = "TRUED_UP"
        bump(plan)

        account["budget_enrolled"] = False

        if plan["trueup_balance_cents"] != 0:
            create_trueup_bill(account, plan, plan["trueup_balance_cents"])

        return success(view_budget_plan(plan), 200)


@bp.route("/accounts/<account_id>/budget-plans/<plan_id>/cancel", methods=["POST"])
def cancel_budget_plan(account_id, plan_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        plan = lookup.get_budget_plan_under_account(account_id, plan_id)
        if plan["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")
        plan["status"] = "CANCELLED"
        bump(plan)
        account["budget_enrolled"] = False
        return success(view_budget_plan(plan), 200)
