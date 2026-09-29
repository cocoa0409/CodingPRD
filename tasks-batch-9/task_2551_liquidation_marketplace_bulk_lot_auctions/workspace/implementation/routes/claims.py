"""Manifest discrepancy claims: filing, evidence, decisions, reversals (PRD 3.8)."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError
from routes.helpers import list_rows
from services import aggregates, calc, guards, lookups, orders as order_svc
from util import clock

bp = Blueprint("claims", __name__)

READ_ALL = (
    mw.PLATFORM_ADMIN, mw.MARKETPLACE_OPS, mw.SELLER_OPS, mw.TRUST_SAFETY, mw.BUYER,
)
DECISIONS = ("APPROVE", "PARTIALLY_APPROVE", "DENY", "REQUEST_EVIDENCE")
ADD_EVIDENCE_STATES = ("SUBMITTED", "EVIDENCE_REQUESTED")
REVERSIBLE_STATES = ("APPROVED", "PARTIALLY_APPROVED")

_DECIDE_SEQ = [0]


def _next_decided_seq():
    _DECIDE_SEQ[0] += 1
    return _DECIDE_SEQ[0]


@bp.post("/liquidation/sale-orders/<order_id>/claims")
def file_claim(order_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    order = lookups.sale_order(order_id)
    # band 4
    guards.owns_order(order, user_id)
    payload = mw.body()
    # band 6
    line = (
        lookups.manifest_line(payload.get("manifest_line_id"))
        if mw.present(payload, "manifest_line_id") else None
    )
    # band 7
    if line is None:
        raise ApiError("ERR_INVALID_REQUEST", "manifest_line_id is required.")
    claim_type = mw.req_enum(payload, "claim_type", mw.CLAIM_TYPES)
    claimed_units = mw.req_int(payload, "claimed_units", minimum=1)
    evidence_urls = mw.opt_str_list(payload, "evidence_urls", default=[])

    # band 10
    if order["logistics_status"] != "PICKED_UP":
        raise ApiError("ERR_ORDER_LOGISTICS_STATE_INVALID")
    if line["line_status"] != "ACTIVE":
        raise ApiError("ERR_LINE_VOIDED")
    # band 12
    window_closes_at = order.get("claim_window_closes_at")
    if window_closes_at is None or clock.now() > window_closes_at:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    # band 15
    if claimed_units > int(line["unit_count"]):
        raise ApiError("ERR_CLAIMED_UNITS_EXCEED_LINE")
    if line["lot_id"] != lookups.listing_of_order(order)["lot_id"]:
        raise ApiError("ERR_LINE_NOT_ON_ORDER_LOT")

    claim = db.new_row(
        sale_order_id=order["id"],
        manifest_line_id=line["id"],
        claim_type=claim_type,
        claimed_units=claimed_units,
        verified_units=None,
        evidence_item_count=len(evidence_urls),
        evidence_request_count=0,
        claim_status="SUBMITTED",
        refund_cents=0,
        decided_by_user_id=None,
        reversed_by_user_id=None,
    )
    claim["filed_at"] = claim["created_at"]
    claim["_decided_seq"] = None
    if claim["evidence_item_count"] >= 2:
        claim["claim_status"] = "UNDER_REVIEW"
    db.claims[claim["id"]] = claim
    return response.created(db.view("claim", claim))


@bp.get("/liquidation/claims/<claim_id>")
def read_claim(claim_id):
    mw.authenticate(READ_ALL)
    return response.success(db.view("claim", lookups.claim(claim_id)))


@bp.get("/liquidation/claims")
def list_claims():
    mw.authenticate(READ_ALL)
    return list_rows(
        "claim",
        list(db.claims.values()),
        (
            ("sale_order_id", "sale_order_id"),
            ("manifest_line_id", "manifest_line_id"),
            ("claim_status", "claim_status"),
            ("claim_type", "claim_type"),
        ),
    )


@bp.post("/liquidation/claims/<claim_id>/evidence-items")
def add_evidence(claim_id):
    user_id, _role = mw.authenticate((mw.BUYER,))
    claim = lookups.claim(claim_id)
    order = lookups.order_of_claim(claim)
    # band 4
    guards.owns_order(order, user_id)
    payload = mw.body()
    # band 7
    mw.req_str(payload, "evidence_url")
    # band 9
    if claim["claim_status"] not in ADD_EVIDENCE_STATES:
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    was_requested = claim["claim_status"] == "EVIDENCE_REQUESTED"
    claim["evidence_item_count"] = int(claim["evidence_item_count"]) + 1
    if was_requested:
        claim["claim_status"] = "UNDER_REVIEW"
    elif claim["evidence_item_count"] >= 2:
        claim["claim_status"] = "UNDER_REVIEW"
    db.touch(claim)
    return response.success(db.view("claim", claim))


def _apply_accuracy_chain(line, lot):
    """ManifestLine -> Lot score -> seller average, status and tier."""
    aggregates.recompute_line_verified_units(line)
    aggregates.recompute_lot_score(lot)
    db.touch(lot)
    aggregates.recompute_seller_accuracy(lookups.seller(lot["seller_id"]))


def _move_ledger(order, delta_cents):
    """Shift the order's claim credit and re-run the payment waterfall."""
    order["claim_credit_cents"] = int(order["claim_credit_cents"]) + delta_cents
    order_svc.recompute_money(order)
    if delta_cents > 0:
        if order["payment_status"] == "PAID":
            order["payment_status"] = "REFUND_ISSUED"
    elif int(order["claim_credit_cents"]) == 0 and order["payment_status"] == "REFUND_ISSUED":
        order["payment_status"] = "PAID"
    db.touch(order)

    buyer = db.buyers.get(order["buyer_id"])
    if buyer is not None:
        buyer["wallet_credit_cents"] = int(buyer["wallet_credit_cents"]) + delta_cents
        buyer["outstanding_exposure_cents"] = aggregates.exposure_of(buyer["id"])
        db.touch(buyer)


@bp.post("/liquidation/claims/<claim_id>/decisions")
def decide_claim(claim_id):
    user_id, _role = mw.authenticate((mw.MARKETPLACE_OPS,))
    claim = lookups.claim(claim_id)
    line = lookups.manifest_line(claim["manifest_line_id"])
    lot = lookups.lot(line["lot_id"])
    # band 5 — checked before the claim's own state or any arithmetic
    if lot.get("manifest_reviewed_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    payload = mw.body()
    # band 7
    decision = mw.req_enum(payload, "decision", DECISIONS)
    verified_units = mw.opt_int(payload, "verified_units", minimum=0)
    mw.opt_str(payload, "decision_note")

    # band 9
    if claim["claim_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    # band 15 — counters first, then the units arithmetic
    claimed_units = int(claim["claimed_units"])
    if decision == "REQUEST_EVIDENCE":
        if int(claim["evidence_request_count"]) >= 2:
            raise ApiError("ERR_EVIDENCE_REQUEST_LIMIT")
    else:
        if int(claim["evidence_item_count"]) < 2:
            raise ApiError("ERR_EVIDENCE_INSUFFICIENT")
        if decision == "APPROVE":
            if verified_units != claimed_units:
                raise ApiError("ERR_VERIFIED_UNITS_MISMATCH")
        elif decision == "PARTIALLY_APPROVE":
            if verified_units is None or not (0 < verified_units < claimed_units):
                raise ApiError("ERR_VERIFIED_UNITS_MISMATCH")
        else:  # DENY
            if verified_units not in (None, 0):
                raise ApiError("ERR_VERIFIED_UNITS_MISMATCH")
            verified_units = 0

    if decision == "REQUEST_EVIDENCE":
        claim["claim_status"] = "EVIDENCE_REQUESTED"
        claim["evidence_request_count"] = int(claim["evidence_request_count"]) + 1
        db.touch(claim)
        return response.success(db.view("claim", claim))

    if decision == "DENY":
        claim["claim_status"] = "DENIED"
        claim["verified_units"] = 0
        claim["refund_cents"] = 0
        claim["decided_by_user_id"] = user_id
        db.touch(claim)
        return response.success(db.view("claim", claim))

    order = lookups.order_of_claim(claim)
    refund_cents = calc.claim_refund_cents(order, lot, line, verified_units)
    claim["claim_status"] = (
        "APPROVED" if decision == "APPROVE" else "PARTIALLY_APPROVED"
    )
    claim["verified_units"] = verified_units
    claim["refund_cents"] = refund_cents
    claim["decided_by_user_id"] = user_id
    claim["_decided_seq"] = _next_decided_seq()
    db.touch(claim)

    _move_ledger(order, refund_cents)
    _apply_accuracy_chain(line, lot)
    return response.success(db.view("claim", claim))


@bp.post("/liquidation/claims/<claim_id>/reversals")
def reverse_claim(claim_id):
    user_id, _role = mw.authenticate((mw.TRUST_SAFETY,))
    claim = lookups.claim(claim_id)
    # band 5
    if claim.get("decided_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    payload = mw.body()
    # band 7
    mw.req_str(payload, "reversal_reason")
    # band 9
    if claim["claim_status"] not in REVERSIBLE_STATES:
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    order = lookups.order_of_claim(claim)
    # band 10
    if order["payment_status"] != "REFUND_ISSUED":
        raise ApiError("ERR_ORDER_PAYMENT_STATE_INVALID")

    refund_cents = int(claim["refund_cents"])
    claim["claim_status"] = "REVERSED"
    claim["reversed_by_user_id"] = user_id
    db.touch(claim)

    _move_ledger(order, -refund_cents)
    line = lookups.manifest_line(claim["manifest_line_id"])
    _apply_accuracy_chain(line, lookups.lot(line["lot_id"]))
    return response.success(db.view("claim", claim))
