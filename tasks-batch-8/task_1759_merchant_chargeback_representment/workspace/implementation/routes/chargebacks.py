"""Chargeback ingest and lifecycle endpoints (PRD 3.5, 3.7)."""

from datetime import timedelta

from flask import Blueprint, g, request

from clock import CLOCK
from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_chargeback, new_fee_assessment, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from routes.rules import find_governing_rule
from serializers import serialize_chargeback
from services.cascade import (
    cascade_decided_lost, cascade_pre_arb_won, cascade_pre_arbitration,
    cascade_reverse, funds_axis_target_recompute, merchant_of,
)
from services.reserve import account_for_merchant, post_entry, recompute_target
from util import Body, CASE_STATUSES, OPEN_CASE_STATUSES, PRE_ARB_DECISIONS, filter_enum

bp = Blueprint("chargebacks", __name__)


@bp.post("/acquirer/chargebacks")
def create_chargeback():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    merchant_id = b.req_str("merchant_id")
    external_ref = b.req_str("transaction_external_ref")
    network_case_id = b.req_str("network_case_id")
    reason_code = b.req_str("reason_code")
    amount_cents = b.req_int("amount_cents")

    # Priority 3: body-referenced ids (merchant, then transaction within merchant scope).
    merchant = None
    txn = None
    if merchant_id is not None:
        merchant = get_or_404(db.merchants, merchant_id, "Merchant")
        if external_ref is not None:
            txn = next((t for t in db.transactions.values()
                        if t["merchant_id"] == merchant_id and t["external_ref"] == external_ref), None)
            if txn is None:
                raise ApiError(404, "ERR_NOT_FOUND", "Transaction not found")

    # Priority 5: the disputed sale must be SETTLED.
    if txn is not None and txn["status"] != "SETTLED":
        raise ApiError(409, "ERR_TRANSACTION_NOT_CHARGEBACKABLE",
                       "Transaction status does not permit chargeback ingest")
    # Priority 6: the merchant must be ACTIVE.
    if merchant is not None and merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_NOT_ACTIVE", "Merchant is not ACTIVE")
    # Priority 7 (scaffold order): globally unique case id; one open case per sale; amount bound.
    if network_case_id is not None:
        if any(c for c in db.chargebacks.values() if c["network_case_id"] == network_case_id):
            raise ApiError(409, "ERR_DUPLICATE_NETWORK_CASE", "network_case_id already exists")
    if txn is not None:
        if any(c for c in db.chargebacks.values()
               if c["transaction_id"] == txn["id"] and c["case_status"] in OPEN_CASE_STATUSES):
            raise ApiError(409, "ERR_TRANSACTION_HAS_OPEN_CHARGEBACK",
                           "Transaction already has a chargeback in an open state")
    if txn is not None and amount_cents is not None:
        if amount_cents <= 0 or amount_cents > txn["amount_cents"]:
            raise ApiError(409, "ERR_CHARGEBACK_AMOUNT_EXCEEDS_TRANSACTION",
                           "Chargeback amount exceeds the disputed transaction's amount")
    # Priority 9: a governing rule whose window covers the receipt instant must exist.
    rule = None
    if txn is not None and reason_code is not None:
        rule = find_governing_rule(txn["network"], reason_code, CLOCK.now())
        if rule is None:
            raise ApiError(422, "ERR_REASON_CODE_RULE_NOT_FOUND",
                           "No ReasonCodeRule covers (%s, %s) at receipt" % (txn["network"], reason_code))
    # Priority 11: payload shape.
    b.raise_pending()

    now = CLOCK.now()
    cb = new_chargeback(
        merchant_id=merchant["id"], transaction_external_ref=external_ref,
        transaction_id=txn["id"], network_case_id=network_case_id,
        reason_code=reason_code, network=txn["network"], amount_cents=amount_cents,
        received_at=now, representment_due_at=now + timedelta(days=rule["representment_days"]),
        rule_id=rule["id"],
    )
    db.chargebacks[cb["id"]] = cb

    # Receipt debit; the disputed sale flips to CHARGED_BACK.
    merchant["clearing_balance_cents"] -= amount_cents
    touch(merchant)
    txn["status"] = "CHARGED_BACK"
    touch(txn)
    # Auto-assessed per-case fee (system-assessed).
    fee = new_fee_assessment(merchant["id"], cb["id"], None, "CHARGEBACK_FEE",
                             rule["chargeback_fee_cents"], "system")
    db.fee_assessments[fee["id"]] = fee

    acct = account_for_merchant(merchant["id"])
    if merchant["risk_tier"] == "HIGH_RISK":
        # Receipt holdback: case-bound, never matures.
        post_entry(acct, "HOLD", amount_cents, "CHARGEBACK_RECEIPT", cb["id"], None)
    # The case joins the open-exposure set.
    recompute_target(merchant)
    touch(acct)
    return ok_object(serialize_chargeback(cb), status=201)


@bp.get("/acquirer/chargebacks")
def list_chargebacks():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    transaction_id = request.args.get("transaction_id")
    case_status = filter_enum(request.args, "case_status", CASE_STATUSES)
    records = list(db.chargebacks.values())
    if is_merchant_user():
        records = [c for c in records if c["merchant_id"] == g.uid]
    elif merchant_id is not None:
        records = [c for c in records if c["merchant_id"] == merchant_id]
    if transaction_id is not None:
        records = [c for c in records if c["transaction_id"] == transaction_id]
    if case_status is not None:
        records = [c for c in records if c["case_status"] == case_status]
    return list_response(records, serialize_chargeback)


@bp.get("/acquirer/chargebacks/<cid>")
def get_chargeback(cid):
    authenticate(ALL_ROLES)
    cb = get_or_404(db.chargebacks, cid, "Chargeback")
    hide_if_cross_merchant(cb["merchant_id"])
    return ok_object(serialize_chargeback(cb))


@bp.post("/acquirer/chargebacks/<cid>/notify")
def notify_chargeback(cid):
    authenticate(("AcquirerOps",))
    cb = get_or_404(db.chargebacks, cid, "Chargeback")
    if cb["case_status"] != "RECEIVED":
        raise ApiError(409, "ERR_INVALID_CASE_STATE", "Only a RECEIVED chargeback can be notified")
    rule = db.rules[cb["_rule_id"]]
    now = CLOCK.now()
    cb["case_status"] = "MERCHANT_NOTIFIED"
    cb["merchant_notified_at"] = now
    cb["merchant_response_due_at"] = now + timedelta(days=rule["merchant_response_days"])
    touch(cb)
    return ok_object(serialize_chargeback(cb))


@bp.post("/acquirer/chargebacks/<cid>/accept")
def accept_chargeback(cid):
    authenticate(("MerchantUser",))
    cb = get_or_404(db.chargebacks, cid, "Chargeback")
    hide_if_cross_merchant(cb["merchant_id"])  # ownership mismatch hidden as 404
    # Priority 5: lifecycle state.
    if cb["case_status"] != "MERCHANT_NOTIFIED":
        raise ApiError(409, "ERR_INVALID_CASE_STATE", "Only a MERCHANT_NOTIFIED chargeback can be accepted")
    # Priority 6: suspension gate.
    merchant = merchant_of(cb)
    if merchant["status"] != "ACTIVE":
        raise ApiError(409, "ERR_MERCHANT_SUSPENDED", "Merchant is SUSPENDED")
    # Priority 7: no in-flight packet.
    if any(r for r in db.representments.values()
           if r["chargeback_id"] == cb["id"] and r["status"] in ("ASSEMBLED", "SUBMITTED")):
        raise ApiError(409, "ERR_REPRESENTMENT_ALREADY_OPEN", "A representment packet is already open for this case")
    # Priority 8: inclusive accept window.
    if CLOCK.now() > cb["merchant_response_due_at"]:
        raise ApiError(409, "ERR_ACCEPT_WINDOW_PASSED", "The merchant response window has passed")
    cb["case_status"] = "MERCHANT_ACCEPTED"
    cb["funds_status"] = "DEBIT_FINAL"  # the receipt debit stands
    touch(cb)
    funds_axis_target_recompute(cb)
    return ok_object(serialize_chargeback(cb))


@bp.post("/acquirer/chargebacks/<cid>/reverse")
def reverse_chargeback(cid):
    authenticate(("AcquirerOps",))
    cb = get_or_404(db.chargebacks, cid, "Chargeback")
    if cb["case_status"] not in ("RECEIVED", "MERCHANT_NOTIFIED", "REPRESENTED"):
        raise ApiError(409, "ERR_INVALID_CASE_STATE", "Case state does not permit reversal")
    cascade_reverse(cb)
    return ok_object(serialize_chargeback(cb))


@bp.post("/acquirer/chargebacks/<cid>/pre-arbitration")
def pre_arbitration(cid):
    authenticate(("AcquirerOps",))
    cb = get_or_404(db.chargebacks, cid, "Chargeback")
    if cb["case_status"] != "DECIDED_WON":
        raise ApiError(409, "ERR_INVALID_CASE_STATE", "Only a DECIDED_WON case can move to pre-arbitration")
    cascade_pre_arbitration(cb)
    return ok_object(serialize_chargeback(cb))


@bp.post("/acquirer/chargebacks/<cid>/pre-arbitration/outcome")
def pre_arbitration_outcome(cid):
    authenticate(("AcquirerOps",))
    cb = get_or_404(db.chargebacks, cid, "Chargeback")
    if cb["case_status"] != "PRE_ARBITRATION":
        raise ApiError(409, "ERR_INVALID_CASE_STATE", "Only a PRE_ARBITRATION case accepts a pre-arbitration outcome")
    b = Body(json_body())
    decision = b.req_enum("decision", PRE_ARB_DECISIONS)
    b.raise_pending()
    if decision == "WON":
        cascade_pre_arb_won(cb)
    else:  # LOST — pre-arb re-debit stands; recredited_cents stays as recorded
        cascade_decided_lost(cb)
    return ok_object(serialize_chargeback(cb))
