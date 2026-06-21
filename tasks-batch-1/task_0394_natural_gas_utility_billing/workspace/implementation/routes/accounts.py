"""Account endpoints: open/list/get and lifecycle actions (PRD §3.2, §3.9, §3.10)."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_NOT_SHUTOFF_ELIGIBLE,
    ERR_EMERGENCY_HOLD,
    ERR_WINTER_MORATORIUM,
    ERR_INVALID_STATE,
    err,
)
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_string,
    attach_common_fields,
    bump,
    sorted_by_created,
    paginate,
)
from services.serialize import view_account
from services import lookup, calc

bp = Blueprint("accounts", __name__)


@bp.route("/accounts", methods=["POST"])
def open_account():
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    body = get_body()
    require_fields(body, ["rate_schedule_id", "holder_name"])
    rate_schedule_id = require_string(body, "rate_schedule_id")
    holder_name = require_string(body, "holder_name")

    with store.lock:
        rs = lookup.get_rate_schedule(rate_schedule_id)
        rec = {
            "rate_schedule_id": rate_schedule_id,
            "customer_class": rs["customer_class"],
            "holder_name": holder_name,
            "service_status": "ACTIVE",
            "low_income_status": "NONE",
            "low_income_tier": "NONE",
            "budget_enrolled": False,
            "consecutive_ontime_payments": 0,
        }
        attach_common_fields(rec)
        store.accounts[rec["id"]] = rec
        return success(view_account(rec), 201)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService"})
    rate_schedule_id = request.args.get("rate_schedule_id")
    records = list(store.accounts.values())
    if rate_schedule_id is not None:
        records = [a for a in records if a["rate_schedule_id"] == rate_schedule_id]
    page, list_meta = paginate(records)
    return success([view_account(a) for a in page], 200, list_meta=list_meta)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech", "Account"})
    account = lookup.get_account(account_id)
    require_account_ownership(principal, account_id)
    return success(view_account(account), 200)


@bp.route("/accounts/<account_id>/shutoff-notice", methods=["POST"])
def shutoff_notice(account_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        # State check (priority 6): must be ACTIVE to begin shutoff.
        if account["service_status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Account is not ACTIVE")
        # Shutoff-eligibility (PRD §3.9): past_due >= threshold AND not moratorium.
        past_due = calc.account_past_due_cents(account_id)
        moratorium = calc.winter_moratorium_in_effect()
        if not ((past_due >= calc.SHUTOFF_THRESHOLD_CENTS) and (not moratorium)):
            raise err(ERR_NOT_SHUTOFF_ELIGIBLE, "Account is not shutoff-eligible")
        # Emergency safety hold (priority 7) then winter moratorium (priority 8).
        if lookup.account_has_active_emergency(account_id):
            raise err(ERR_EMERGENCY_HOLD, "Live hazard on the account blocks shutoff")
        if moratorium:
            raise err(ERR_WINTER_MORATORIUM, "Winter moratorium in effect")

        account["service_status"] = "SHUTOFF_PENDING"
        bump(account)

        # Auto-create a SHUTOFF service order in SCHEDULED for the SET meter.
        set_meter = None
        for m in lookup.account_meters(account_id):
            if m["status"] == "SET":
                set_meter = m
                break
        order = {
            "account_id": account_id,
            "premise_meter_id": set_meter["id"] if set_meter else None,
            "order_type": "SHUTOFF",
            "status": "SCHEDULED",
            "scheduled_date": store.clock["current_utc"],
            "completed_index": None,
        }
        attach_common_fields(order)
        store.service_orders[order["id"]] = order
        return success(view_account(account), 200)


@bp.route("/accounts/<account_id>/cancel-shutoff", methods=["POST"])
def cancel_shutoff(account_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        if account["service_status"] != "SHUTOFF_PENDING":
            raise err(ERR_INVALID_STATE, "Account is not SHUTOFF_PENDING")
        account["service_status"] = "ACTIVE"
        bump(account)
        # Cancel any SCHEDULED/DISPATCHED SHUTOFF service order for this account.
        for o in store.service_orders.values():
            if (o["account_id"] == account_id and o["order_type"] == "SHUTOFF"
                    and o["status"] in ("SCHEDULED", "DISPATCHED")):
                o["status"] = "CANCELLED"
                bump(o)
        return success(view_account(account), 200)


@bp.route("/accounts/<account_id>/final-bill", methods=["POST"])
def final_bill(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        if account["service_status"] != "DISCONNECTED":
            raise err(ERR_INVALID_STATE, "Account is not DISCONNECTED")

        account["service_status"] = "FINALED"
        bump(account)

        # Cascade: any HELD deposit -> APPLIED against balance, remainder REFUNDED.
        for d in store.deposits.values():
            if d["account_id"] == account_id and d["status"] == "HELD":
                d["status"] = "APPLIED"
                bump(d)

        # Cascade: any ACTIVE budget plan -> TRUED_UP.
        for p in store.budget_plans.values():
            if p["account_id"] == account_id and p["status"] == "ACTIVE":
                _true_up_plan(account, p)

        return success(view_account(account), 200)


def _true_up_plan(account, plan):
    """Shared true-up cascade (PRD §3.7) used by finalization and the explicit
    true-up endpoint. Sets trueup_balance and creates a residual DRAFT bill."""
    from routes.budget_plans import compute_plan_accruals, create_trueup_bill

    accrued_actual, accrued_budget = compute_plan_accruals(plan)
    plan["accrued_actual_cents"] = accrued_actual
    plan["accrued_budget_cents"] = accrued_budget
    plan["trueup_balance_cents"] = accrued_actual - accrued_budget
    plan["status"] = "TRUED_UP"
    bump(plan)
    account["budget_enrolled"] = False
    if plan["trueup_balance_cents"] != 0:
        create_trueup_bill(account, plan, plan["trueup_balance_cents"])
