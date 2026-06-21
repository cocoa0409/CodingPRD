"""LeakAdjustment routes (PRD §3.8)."""
from flask import Blueprint, request

import db
import errors
import middleware
from response import object_response, array_response
from services import lookup, ledger, calc
from services.common import (
    get_json_body, require_str, require_int, public, public_list,
    parse_pagination, paginate,
)

bp = Blueprint("leak_adjustments", __name__)


@bp.post("/leak-adjustments")
def create():
    middleware.require_role({"Customer", "AssistanceCaseworker"})
    body = get_json_body()

    bill_id = require_str(body, "bill_id")
    bill = lookup.bill(bill_id)
    # Customer may only request against their own bill.
    middleware.require_owner(bill["account_id"])

    baseline = require_int(body, "baseline_gallons", minimum=0)
    repair_ref = require_str(body, "repair_evidence_ref")

    rec = db.make_record({
        "bill_id": bill_id,
        # account_id copied from the bill at request time.
        "account_id": bill["account_id"],
        "baseline_gallons": baseline,
        "repair_evidence_ref": repair_ref,
        "credit_cents": 0,
        "status": "PENDING",
    })
    db.leak_adjustments[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/leak-adjustments/<rid>")
def get_one(rid):
    middleware.require_role({"AssistanceCaseworker", "Customer", "BillingClerk"})
    rec = lookup.leak_adjustment(rid)
    middleware.require_owner(rec["account_id"])
    return object_response(public(rec), 200)


@bp.get("/leak-adjustments")
def list_all():
    middleware.require_role({"AssistanceCaseworker", "BillingClerk", "Customer"})
    limit, offset = parse_pagination()

    records = list(db.leak_adjustments.values())
    bill_id = request.args.get("bill_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")

    if bill_id is not None:
        records = [r for r in records if r["bill_id"] == bill_id]
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    if middleware.get_role() == "Customer":
        uid = middleware.get_user_id()
        records = [r for r in records if r["account_id"] == uid]

    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@bp.post("/leak-adjustments/<rid>/approve")
def approve(rid):
    middleware.require_role({"AssistanceCaseworker"})
    adj = lookup.leak_adjustment(rid)

    # State: approve defined only from PENDING.
    if adj["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PENDING adjustment may be approved.")

    bill = db.bills[adj["bill_id"]]
    # Referenced bill must be POSTED (PRD §3.8).
    if bill["status"] != "POSTED":
        raise errors.err(errors.ERR_BILL_NOT_POSTED, "Leak credit requires the referenced bill to be POSTED.")

    # Genuine over-baseline volume required: baseline strictly below potable.
    if adj["baseline_gallons"] >= bill["potable_consumption_gallons"]:
        raise errors.err(errors.ERR_NO_LEAK_VOLUME, "baseline_gallons is not below the bill's potable consumption.")

    schedule = db.rate_schedules[bill["rate_schedule_id"]]
    credit = calc.leak_credit_cents(
        bill["potable_consumption_gallons"],
        adj["baseline_gallons"],
        schedule["water_tiers"],
        schedule["leak_adjustment_rate_pct"],
        bill["water_volumetric_cents"],
    )

    adj["credit_cents"] = credit
    adj["status"] = "APPROVED"
    db.touch(adj)

    # Apply to bill: leak_credit_cents, amount_billed_cents recomputed (cascade).
    bill["leak_credit_cents"] = credit
    bill["amount_billed_cents"] = calc.amount_billed_cents(
        bill["fixed_charge_cents"],
        bill["water_volumetric_cents"],
        bill["sewer_volumetric_cents"],
        credit,
    )

    account = db.accounts[bill["account_id"]]
    plan = ledger.active_budget_plan(account["id"])
    # If the bill is not on a budget plan, recompute total_cents and decrease
    # balance by the credit (compensation). On a budget plan, total_cents stays
    # the flat installment, so no ledger compensation.
    if plan is None:
        bill["total_cents"] = bill["amount_billed_cents"]
    db.touch(bill)

    ledger.reconcile(account)
    return object_response(public(adj), 200)


@bp.post("/leak-adjustments/<rid>/deny")
def deny(rid):
    middleware.require_role({"AssistanceCaseworker"})
    adj = lookup.leak_adjustment(rid)

    if adj["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PENDING adjustment may be denied.")

    adj["status"] = "DENIED"
    # Terminal; credit_cents stays 0; no ledger effect.
    db.touch(adj)
    return object_response(public(adj), 200)
