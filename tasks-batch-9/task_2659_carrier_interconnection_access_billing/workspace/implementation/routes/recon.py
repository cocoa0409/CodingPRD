"""Mutual record exchange reconciliation (PRD 3.10)."""
from decimal import Decimal

from flask import Blueprint, request

import validation as v
from auth import (ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate, carrier_of_case,
                  scope_check, scope_filter)
from constants import VARIANCE_TOLERANCE_PCT
from dec import q2, q4, q6
from envelope import object_response, paginate
from errors import ApiError
from lookup import get_recon_case, get_usage_batch, invoice_for_batch
from services import reserve
from services.invoicing import apply_credit, derive_lifecycle
from store import base_record, db, now, ordered, touch

bp = Blueprint("recon", __name__)

ZERO = Decimal("0")
ZERO2 = Decimal("0.00")
HUNDRED = Decimal("100")


@bp.post("/reconciliation-cases")
def open_case():
    authenticate((REVENUE_ASSURANCE_CONTROLLER, ACCESS_BILLING_ANALYST))
    payload = v.body()
    batch_id = v.string(payload, "usage_batch_id")
    counterparty_minutes = v.number(payload, "counterparty_reported_minutes", 4, ge=0)
    counterparty_amount = v.number(payload, "counterparty_reported_amount_usd", 2, ge=0)
    exchange_reference = v.string(payload, "exchange_reference")

    batch = get_usage_batch(batch_id)

    for existing in db.recon_cases.values():
        if (existing["usage_batch_id"] == batch["id"]
                and existing["exchange_reference"] == exchange_reference):
            raise ApiError("ERR_DUPLICATE_RECONCILIATION_CASE",
                           "a case already exists for this batch and exchange reference")

    case = base_record()
    case.update({
        "usage_batch_id": batch["id"],
        "exchange_reference": exchange_reference,
        "counterparty_reported_minutes": counterparty_minutes,
        "counterparty_reported_amount_usd": counterparty_amount,
        "our_minutes": batch["total_billable_minutes"],
        "our_amount_usd": batch["rated_amount_usd"],
        "status": "OPEN",
        "minute_variance_pct": None,
        "amount_variance_usd": None,
        "agreed_minutes": None,
        "adjustment_amount_usd": None,
        "adjusted_at": None,
    })
    db.recon_cases[case["id"]] = case
    return object_response(case, 201)


@bp.get("/reconciliation-cases/<case_id>")
def read_case(case_id):
    actor = authenticate((PLATFORM_ADMIN, REVENUE_ASSURANCE_CONTROLLER,
                          ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE))
    case = get_recon_case(case_id)
    scope_check(actor, carrier_of_case(case))
    return object_response(case)


@bp.get("/usage-batches/<batch_id>/reconciliation-cases")
def list_batch_cases(batch_id):
    actor = authenticate((PLATFORM_ADMIN, REVENUE_ASSURANCE_CONTROLLER,
                          ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE))
    batch = get_usage_batch(batch_id)
    scope_check(actor, batch["carrier_id"])
    rows = [c for c in ordered(db.recon_cases)
            if c["usage_batch_id"] == batch["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, request.args, lambda r: r)


@bp.get("/reconciliation-cases")
def list_cases():
    actor = authenticate((PLATFORM_ADMIN, REVENUE_ASSURANCE_CONTROLLER,
                          ACCESS_BILLING_ANALYST, CARRIER_REPRESENTATIVE))
    rows = ordered(db.recon_cases)
    batch_id = request.args.get("usage_batch_id")
    if batch_id:
        rows = [r for r in rows if r["usage_batch_id"] == batch_id]
    exchange_reference = request.args.get("exchange_reference")
    if exchange_reference:
        rows = [r for r in rows if r["exchange_reference"] == exchange_reference]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = scope_filter(actor, rows, carrier_of_case)
    return paginate(rows, request.args, lambda r: r)


@bp.post("/reconciliation-cases/<case_id>/evaluate")
def evaluate_case(case_id):
    authenticate((REVENUE_ASSURANCE_CONTROLLER,))
    case = get_recon_case(case_id)

    if case["status"] != "OPEN":
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE",
                       "only an OPEN case may be evaluated")

    ours = case["our_minutes"]
    theirs = case["counterparty_reported_minutes"]
    if theirs == ZERO:
        variance_pct = Decimal("100.00") if ours > ZERO else ZERO2
    else:
        variance_pct = q2((ours - theirs) * HUNDRED / theirs)

    case["minute_variance_pct"] = variance_pct
    case["amount_variance_usd"] = q2(case["our_amount_usd"]
                                     - case["counterparty_reported_amount_usd"])
    case["status"] = ("VARIANCE_IDENTIFIED"
                      if abs(variance_pct) > VARIANCE_TOLERANCE_PCT else "ACCEPTED")
    touch(case)
    return object_response(case)


@bp.post("/reconciliation-cases/<case_id>/adjust")
def adjust_case(case_id):
    authenticate((REVENUE_ASSURANCE_CONTROLLER,))
    case = get_recon_case(case_id)
    payload = v.body()
    agreed_minutes = v.number(payload, "agreed_minutes", 4, ge=0)

    if case["status"] != "VARIANCE_IDENTIFIED":
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE",
                       "only a VARIANCE_IDENTIFIED case may be adjusted")

    ours = case["our_minutes"]
    theirs = case["counterparty_reported_minutes"]
    low, high = (ours, theirs) if ours <= theirs else (theirs, ours)
    if not (low <= agreed_minutes <= high):
        raise ApiError("ERR_AGREED_MINUTES_OUT_OF_RANGE",
                       "agreed_minutes must lie between our minutes and the "
                       "counterparty's minutes, inclusive")

    invoice = invoice_for_batch(case["usage_batch_id"])
    if invoice is None or invoice["lifecycle_status"] != "ISSUED":
        raise ApiError("ERR_INVOICE_NOT_ISSUED",
                       "the batch's access invoice must exist and be ISSUED")
    if invoice["payment_status"] == "WRITTEN_OFF":
        raise ApiError("ERR_INVOICE_ALREADY_WRITTEN_OFF",
                       "a written-off invoice may not be adjusted")

    blended_rate = q6(case["our_amount_usd"] / ours) if ours != ZERO else Decimal("0.000000")
    adjustment = q2((ours - agreed_minutes) * blended_rate)

    case["agreed_minutes"] = q4(agreed_minutes)
    case["_blended_rate_per_mou_usd"] = blended_rate
    case["adjustment_amount_usd"] = adjustment
    case["status"] = "ADJUSTED"
    case["adjusted_at"] = now()
    touch(case)

    apply_credit(invoice, adjustment)
    derive_lifecycle(invoice)
    touch(invoice)

    carrier = db.carriers.get(invoice["carrier_id"])
    if carrier is not None:
        reserve.recompute(carrier, "RECONCILIATION_ADJUSTED", invoice["id"])
    return object_response(case)


@bp.post("/reconciliation-cases/<case_id>/accept")
def accept_case(case_id):
    authenticate((REVENUE_ASSURANCE_CONTROLLER,))
    case = get_recon_case(case_id)
    payload = v.body()
    note = v.string(payload, "acceptance_note")

    if case["status"] != "VARIANCE_IDENTIFIED":
        raise ApiError("ERR_INVALID_RECONCILIATION_STATE",
                       "only a VARIANCE_IDENTIFIED case may be accepted")

    case["status"] = "ACCEPTED"
    case["_acceptance_note"] = note
    touch(case)
    return object_response(case)
