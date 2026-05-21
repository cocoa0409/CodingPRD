"""Dispute-claim lifecycle endpoints (flat path under brokerage)."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_CLAIM_NOT_COUNTER_OFFERED,
    ERR_CLAIM_NOT_IN_REVIEW,
    ERR_CLAIM_NOT_OPEN,
    ERR_COUNTER_OFFER_INVALID,
    ERR_DISPUTE_CLAIM_NOT_FOUND,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_SETTLED_CREDIT_INVALID,
)
from ..helpers import (
    check_version,
    get_body,
    get_brokerage_or_404,
    get_scoped,
)
from ..services.cascade import apply_resolved_dispute
from ..store import store


dispute_claims_bp = Blueprint("dispute_claims", __name__, url_prefix="/brokerages")


def _ensure_shipper_owns_claim(claim: dict) -> None:
    """For ShipperUser callers, ensure the claim belongs to their shipper."""
    if g.user_role != "ShipperUser":
        return
    invoice = store.invoices.get(claim.get("invoice_id"))
    if invoice is None or invoice.get("shipper_id") != g.user_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "ShipperUser can only act on own shipper's claims.",
        )


@dispute_claims_bp.get("/<brokerage_id>/dispute-claims/<claim_id>")
@require_auth(["BrokerOps", "ShipperUser"])
def get_dispute_claim(brokerage_id, claim_id):
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        _ensure_shipper_owns_claim(cl)
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/start-review")
@require_auth(["BrokerOps"])
def start_review(brokerage_id, claim_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        check_version(cl, body)
        if cl.get("status") != "OPEN":
            raise ApiError(ERR_CLAIM_NOT_OPEN, 409, "Claim not in OPEN.")
        cl["status"] = "IN_REVIEW"
        store.bump(cl)
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/counter")
@require_auth(["BrokerOps"])
def counter(brokerage_id, claim_id):
    body = get_body()
    if "counter_offer_cents" not in body or body["counter_offer_cents"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing counter_offer_cents.")
    coc = body["counter_offer_cents"]
    if isinstance(coc, bool) or not isinstance(coc, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "counter_offer_cents must be an integer.")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        check_version(cl, body)

        if cl.get("status") != "IN_REVIEW":
            raise ApiError(ERR_CLAIM_NOT_IN_REVIEW, 409, "Claim not in IN_REVIEW.")

        if int(coc) <= 0 or int(coc) >= int(cl.get("claimed_cents", 0)):
            raise ApiError(ERR_COUNTER_OFFER_INVALID, 422, "Invalid counter_offer_cents.")

        cl["counter_offer_cents"] = int(coc)
        cl["status"] = "COUNTER_OFFERED"
        store.bump(cl)
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/accept-counter")
@require_auth(["ShipperUser"])
def accept_counter(brokerage_id, claim_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        _ensure_shipper_owns_claim(cl)
        check_version(cl, body)

        if cl.get("status") != "COUNTER_OFFERED":
            raise ApiError(ERR_CLAIM_NOT_COUNTER_OFFERED, 409, "Claim not in COUNTER_OFFERED.")

        settled = int(cl.get("counter_offer_cents") or 0)
        cl["settled_credit_cents"] = settled
        cl["status"] = "RESOLVED"
        store.bump(cl)
        apply_resolved_dispute(cl, settled_credit=settled)
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/reject-counter")
@require_auth(["ShipperUser"])
def reject_counter(brokerage_id, claim_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        _ensure_shipper_owns_claim(cl)
        check_version(cl, body)

        if cl.get("status") != "COUNTER_OFFERED":
            raise ApiError(ERR_CLAIM_NOT_COUNTER_OFFERED, 409, "Claim not in COUNTER_OFFERED.")

        cl["counter_offer_cents"] = None
        cl["status"] = "IN_REVIEW"
        store.bump(cl)
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/resolve")
@require_auth(["BrokerOps"])
def resolve(brokerage_id, claim_id):
    body = get_body()
    if "settled_credit_cents" not in body or body["settled_credit_cents"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing settled_credit_cents.")
    s = body["settled_credit_cents"]
    if isinstance(s, bool) or not isinstance(s, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "settled_credit_cents must be an integer.")

    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        check_version(cl, body)

        if cl.get("status") != "IN_REVIEW":
            raise ApiError(ERR_CLAIM_NOT_IN_REVIEW, 409, "Claim not in IN_REVIEW.")

        inv = store.invoices.get(cl["invoice_id"])
        if inv is None:
            raise ApiError(ERR_DISPUTE_CLAIM_NOT_FOUND, 404, "Underlying invoice not found.")

        if s < 0 or s > int(cl.get("claimed_cents", 0)) or s > int(inv.get("balance_due_cents", 0)):
            raise ApiError(ERR_SETTLED_CREDIT_INVALID, 422, "Invalid settled_credit_cents.")

        cl["settled_credit_cents"] = int(s)
        cl["status"] = "RESOLVED"
        store.bump(cl)
        apply_resolved_dispute(cl, settled_credit=int(s))
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/escalate")
@require_auth(["BrokerOps"])
def escalate(brokerage_id, claim_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        check_version(cl, body)
        if cl.get("status") != "IN_REVIEW":
            raise ApiError(ERR_CLAIM_NOT_IN_REVIEW, 409, "Claim not in IN_REVIEW.")
        cl["status"] = "ESCALATED"
        store.bump(cl)
    return ok_object(cl)


@dispute_claims_bp.post("/<brokerage_id>/dispute-claims/<claim_id>/withdraw")
@require_auth(["ShipperUser"])
def withdraw(brokerage_id, claim_id):
    body = get_body()
    with store.lock:
        get_brokerage_or_404(brokerage_id)
        cl = get_scoped(store.dispute_claims, claim_id, brokerage_id, ERR_DISPUTE_CLAIM_NOT_FOUND)
        _ensure_shipper_owns_claim(cl)
        check_version(cl, body)

        if cl.get("status") not in ("OPEN", "IN_REVIEW"):
            raise ApiError(ERR_CLAIM_NOT_OPEN, 409, "Claim not withdrawable.")
        cl["status"] = "WITHDRAWN"
        store.bump(cl)
    return ok_object(cl)
