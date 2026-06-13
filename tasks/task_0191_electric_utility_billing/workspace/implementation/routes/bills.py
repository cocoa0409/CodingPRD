"""Bill endpoints: create, issue (price + OCC + budget accrual), void (full
ledger reversal), and reads (PRD §3.3, §3.4)."""
from flask import Blueprint, request

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles, require_owner
from response import success
from services import serializers as ser
from services.common import (
    get_json_body,
    paginate,
    parse_dt,
    parse_pagination,
    require_dt,
    require_fields,
    require_int,
)
from services.ledger import recompute_oldest_unpaid, reage_account, refund_grant
from services.pricing import price_bill

bp = Blueprint("bills", __name__)

READ_ROLES = {"BillingOperator", "Customer", "AssistanceCaseworker"}


def _active_plan_for(account_id):
    for p in db.budget_plans.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            return p
    return None


@bp.route("/bills", methods=["POST"])
def create_bill():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()
    require_fields(body, ["account_id", "period_start", "period_end", "due_date"])
    account_id = body["account_id"]
    period_start_dt = require_dt(body, "period_start")
    period_end_dt = require_dt(body, "period_end")
    due_dt = require_dt(body, "due_date")

    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced account does not exist.")

    # Period must be non-empty and not overlap an existing non-VOID bill.
    if not (period_end_dt > period_start_dt):
        raise err("ERR_BILL_PERIOD_OVERLAP", "period_end must be after period_start.")
    for b in db.bills.values():
        if b["account_id"] != account_id or b["status"] == "VOID":
            continue
        b_start = parse_dt(b["period_start"])
        b_end = parse_dt(b["period_end"])
        if b_start is None or b_end is None:
            continue
        if period_start_dt < b_end and b_start < period_end_dt:
            raise err("ERR_BILL_PERIOD_OVERLAP", "Bill period overlaps an existing bill.")

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "tariff_id": None,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "status": "DRAFT",
        "total_import_kwh": 0,
        "total_export_kwh": 0,
        "billed_peak_demand_kw": 0,
        "energy_charge_cents": 0,
        "demand_charge_cents": 0,
        "net_metering_credit_applied_cents": 0,
        "assistance_applied_cents": 0,
        "total_due_cents": 0,
        "amount_paid_cents": 0,
        "due_date": body["due_date"],
        "is_budget_billed": False,
        "actual_cost_cents": 0,
    })
    db.bills[rec["id"]] = rec
    return success(ser.bill(rec), status=201)


@bp.route("/bills/<bill_id>/issue", methods=["POST"])
def issue_bill(bill_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    bill = db.bills.get(bill_id)
    if bill is None:
        raise err("ERR_NOT_FOUND", "Bill not found.")
    body = get_json_body()
    require_fields(body, ["expected_account_version"])
    expected_version = require_int(body, "expected_account_version")

    account = db.accounts.get(bill["account_id"])
    tariff = db.tariffs.get(account["tariff_id"]) if account else None

    # Priority order: tariff-active (8) -> state (9) -> OCC (17).
    if tariff is None or tariff["status"] != "ACTIVE":
        raise err("ERR_TARIFF_NOT_ACTIVE", "Account tariff is not ACTIVE.")
    if bill["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT bill can be issued.")
    if expected_version != account["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "Account version is stale.")

    plan = _active_plan_for(account["id"])

    # Run pricing — mutates bill computed fields, returns ledger deltas.
    deltas = price_bill(bill, account, tariff, plan)

    # Commit ledger side effects (PRD §3.3).
    bill["status"] = "ISSUED"
    bill["tariff_id"] = tariff["id"]
    touch(bill)

    # Debit net-metering credit bank to the carryover.
    account["net_metering_credit_balance_cents"] = deltas["new_credit_balance_cents"]
    # Increase balance by total_due.
    account["balance_cents"] += bill["total_due_cents"]

    # Consume assistance grant lifecycle (if any).
    grant = deltas["grant"]
    if grant is not None and deltas["assistance_applied_cents"] > 0:
        from services.ledger import consume_grant
        consume_grant(grant, deltas["assistance_applied_cents"])

    # Budget-plan accrual when budget-billed.
    if bill["is_budget_billed"] and plan is not None:
        plan["accumulated_actual_cents"] += bill["actual_cost_cents"]
        plan["accumulated_levelized_cents"] += plan["levelized_amount_cents"]
        touch(plan)

    # Issuing changes the unpaid set; refresh oldest-unpaid pointer and re-age.
    recompute_oldest_unpaid(account)
    reage_account(account)

    touch(account)  # increments Account.version by 1 (PRD §3.3)
    return success(ser.bill(bill), status=200)


@bp.route("/bills/<bill_id>/void", methods=["POST"])
def void_bill(bill_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    bill = db.bills.get(bill_id)
    if bill is None:
        raise err("ERR_NOT_FOUND", "Bill not found.")

    if bill["status"] != "ISSUED" or bill["amount_paid_cents"] != 0:
        raise err("ERR_INVALID_STATE", "Only an ISSUED, unpaid bill can be voided.")

    account = db.accounts.get(bill["account_id"])

    # Reverse ledger effects (PRD §3.4).
    account["balance_cents"] -= bill["total_due_cents"]
    account["net_metering_credit_balance_cents"] += bill["net_metering_credit_applied_cents"]

    # Refund assistance back to the source grant.
    if bill["assistance_applied_cents"] > 0:
        grant = _find_grant_for_refund(bill)
        if grant is not None:
            refund_grant(grant, bill["assistance_applied_cents"])

    # Decrement budget-plan counters when budget-billed.
    if bill["is_budget_billed"]:
        plan = _active_plan_for(account["id"]) or _plan_of_bill(bill)
        if plan is not None:
            plan["accumulated_actual_cents"] -= bill["actual_cost_cents"]
            plan["accumulated_levelized_cents"] -= bill["total_due_cents"]
            touch(plan)

    bill["status"] = "VOID"
    touch(bill)

    recompute_oldest_unpaid(account)
    reage_account(account)
    touch(account)  # increments Account.version (PRD §3.4)
    return success(ser.bill(bill), status=200)


def _find_grant_for_refund(bill):
    """Find the grant whose assistance this bill consumed. The pricing engine
    consumes the oldest consumable grant for the account; on void we refund to
    a grant of that account (prefer one not in a terminal CANCELLED state)."""
    candidates = [
        g for g in db.assistance_grants.values()
        if g["account_id"] == bill["account_id"] and g["status"] != "CANCELLED"
    ]
    if not candidates:
        return None
    # Prefer EXHAUSTED/APPLIED grants (the ones consumption could have touched),
    # oldest-created first to mirror consumption order.
    candidates.sort(key=lambda g: (g["created_at"], g["_seq"]))
    return candidates[0]


def _plan_of_bill(bill):
    """Best-effort lookup of the plan a budget-billed bill accrued into."""
    plans = [
        p for p in db.budget_plans.values() if p["account_id"] == bill["account_id"]
    ]
    if not plans:
        return None
    # Prefer an ACTIVE plan, else the most recent.
    active = [p for p in plans if p["status"] == "ACTIVE"]
    if active:
        return active[0]
    plans.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return plans[-1]


@bp.route("/bills/<bill_id>", methods=["GET"])
def get_bill(bill_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.bills.get(bill_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Bill not found.")
    require_owner(role, user_id, rec["account_id"])
    return success(ser.bill(rec), status=200)


@bp.route("/bills", methods=["GET"])
def list_bills():
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    account_id = request.args.get("account_id")
    tariff_id = request.args.get("tariff_id")
    status = request.args.get("status")
    items = list(db.bills.values())
    if role == "Customer":
        items = [b for b in items if b["account_id"] == user_id]
    if account_id is not None:
        items = [b for b in items if b["account_id"] == account_id]
    if tariff_id is not None:
        items = [b for b in items if b["tariff_id"] == tariff_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, pagination = paginate(items)
    return success([ser.bill(b) for b in page], status=200, pagination=pagination)
