"""Bill routes: generate, fetch, list, post, void (PRD §3.4, §3.5)."""
from flask import Blueprint, request

import db
import errors
import middleware
from response import object_response, array_response
from services import lookup, ledger, billing
from services.common import (
    get_json_body, require_str, public, public_list, parse_pagination, paginate,
)

bp = Blueprint("bills", __name__)


def _non_void_bill_exists(account_id, cycle_id, exclude_id=None):
    for b in db.bills.values():
        if b["id"] == exclude_id:
            continue
        if b["account_id"] == account_id and b["billing_cycle_id"] == cycle_id:
            if b["status"] != "VOID":
                return True
    return False


def _posted_or_paid_bill_exists(account_id, cycle_id, exclude_id=None):
    for b in db.bills.values():
        if b["id"] == exclude_id:
            continue
        if b["account_id"] == account_id and b["billing_cycle_id"] == cycle_id:
            if b["status"] in ("POSTED", "PAID"):
                return True
    return False


@bp.post("/bills")
def generate_bill():
    middleware.require_role({"BillingClerk"})
    body = get_json_body()

    account_id = require_str(body, "account_id")
    billing_cycle_id = require_str(body, "billing_cycle_id")
    account = lookup.account(account_id)
    cycle = lookup.billing_cycle(billing_cycle_id)

    # Business rules. State legality runs before domain rules (PRD §2.9); cycle
    # closure is the gating state-ish guard, then duplicate, then consumption.
    if cycle["status"] == "CLOSED":
        raise errors.err(errors.ERR_CYCLE_CLOSED, "Cannot generate a bill against a CLOSED cycle.")

    # At most one non-VOID bill per (account, cycle) (PRD §3.4).
    if _non_void_bill_exists(account_id, billing_cycle_id):
        raise errors.err(errors.ERR_DUPLICATE_BILL, "A non-VOID bill already exists for this account and cycle.")

    potable, irrigation, has_read = billing.consumption_for_account(account_id, cycle)
    if not has_read:
        raise errors.err(errors.ERR_NO_CONSUMPTION_DATA, "Account has no meter reads in the cycle window.")

    schedule = db.rate_schedules[account["rate_schedule_id"]]

    rec = db.make_record({
        "account_id": account_id,
        "billing_cycle_id": billing_cycle_id,
        # rate_schedule_id pinned (snapshot) at generation time.
        "rate_schedule_id": account["rate_schedule_id"],
        "potable_consumption_gallons": potable,
        "irrigation_consumption_gallons": irrigation,
        "billable_sewer_gallons": 0,
        "fixed_charge_cents": 0,
        "water_volumetric_cents": 0,
        "sewer_volumetric_cents": 0,
        "leak_credit_cents": 0,
        "amount_billed_cents": 0,
        "total_cents": 0,
        "budget_billing_amount_cents": 0,
        "status": "DRAFT",
        "late_fee_cents": 0,
    })
    billing.compute_charge_stack(rec, account, schedule)
    db.bills[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/bills/<rid>")
def get_bill(rid):
    middleware.require_role({"BillingClerk", "AssistanceCaseworker", "Customer"})
    rec = lookup.bill(rid)
    middleware.require_owner(rec["account_id"])
    return object_response(public(rec), 200)


@bp.get("/bills")
def list_bills():
    middleware.require_role({"BillingClerk", "AssistanceCaseworker", "Customer"})
    limit, offset = parse_pagination()

    records = list(db.bills.values())
    account_id = request.args.get("account_id")
    billing_cycle_id = request.args.get("billing_cycle_id")
    rate_schedule_id = request.args.get("rate_schedule_id")
    status = request.args.get("status")

    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if billing_cycle_id is not None:
        records = [r for r in records if r["billing_cycle_id"] == billing_cycle_id]
    if rate_schedule_id is not None:
        records = [r for r in records if r["rate_schedule_id"] == rate_schedule_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    # Customer ownership: a customer may only list their own bills.
    if middleware.get_role() == "Customer":
        uid = middleware.get_user_id()
        records = [r for r in records if r["account_id"] == uid]

    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@bp.post("/bills/<rid>/post")
def post_bill(rid):
    middleware.require_role({"BillingClerk"})
    bill = lookup.bill(rid)

    # State: only DRAFT bills may be posted (PRD §3.5).
    if bill["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT bill may be posted.")

    cycle = db.billing_cycles[bill["billing_cycle_id"]]
    # Cycle must still be OPEN (PRD §3.5).
    if cycle["status"] == "CLOSED":
        raise errors.err(errors.ERR_CYCLE_CLOSED, "Cannot post a bill against a CLOSED cycle.")

    # No other POSTED/PAID bill for the same (account, cycle) (PRD §3.5).
    if _posted_or_paid_bill_exists(bill["account_id"], bill["billing_cycle_id"], exclude_id=rid):
        raise errors.err(errors.ERR_DUPLICATE_BILL, "Another posted bill already exists for this account and cycle.")

    account = db.accounts[bill["account_id"]]
    schedule = db.rate_schedules[bill["rate_schedule_id"]]
    # Finalize computed charge fields against current account state.
    billing.compute_charge_stack(bill, account, schedule)
    bill["status"] = "POSTED"
    db.touch(bill)

    # Cascade: if on ACTIVE budget plan, advance cycles_elapsed and recompute delta.
    plan = ledger.active_budget_plan(account["id"])
    if plan is not None:
        plan["cycles_elapsed"] += 1
        billing.recompute_plan_trueup(plan)
        db.touch(plan)

    ledger.reconcile(account)
    return object_response(public(bill), 200)


@bp.post("/bills/<rid>/void")
def void_bill(rid):
    middleware.require_role({"BillingClerk"})
    bill = lookup.bill(rid)

    if bill["status"] not in ("DRAFT", "POSTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT or POSTED bill may be voided.")

    if bill["status"] == "POSTED":
        # A POSTED bill may only be voided if no payment has been applied to it.
        for p in db.payments.values():
            if p["account_id"] == bill["account_id"] and p.get("_allocations", {}).get(rid, 0) > 0:
                raise errors.err(errors.ERR_BILL_HAS_PAYMENT, "A payment has already been applied to this bill.")

        account = db.accounts[bill["account_id"]]
        bill["status"] = "VOID"
        db.touch(bill)
        # Compensation: reverse the posting; recompute budget plan if active.
        plan = ledger.active_budget_plan(account["id"])
        if plan is not None:
            plan["cycles_elapsed"] -= 1
            billing.recompute_plan_trueup(plan)
            db.touch(plan)
        ledger.reconcile(account)
        return object_response(public(bill), 200)

    # DRAFT void: terminal, no ledger effect.
    bill["status"] = "VOID"
    db.touch(bill)
    return object_response(public(bill), 200)
