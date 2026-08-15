"""Cargo claims: filing with liability stamping, review, counteroffer loop,
and settlement (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_AMOUNT_EXCEEDS_LIABILITY,
    ERR_CLAIM_FILING_DEADLINE_PASSED,
    ERR_DUPLICATE_OPEN_CLAIM,
    ERR_HWB_NOT_DELIVERED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from middleware import (
    ALL_ROLES,
    get_body,
    opt_num,
    opt_str,
    pagination_params,
    req_enum,
    req_nonempty_str,
    req_num,
    require_roles,
)
from money import dec
from response import ok

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("DAMAGE", "SHORTAGE", "DELAY", "LOSS")
FILING_WINDOW_DAYS = {"DAMAGE": 14, "SHORTAGE": 14, "DELAY": 21, "LOSS": 21}
OUTCOMES = ("APPROVED", "DENIED", "COUNTERED")


@bp.post("/claims")
@require_roles("ForwarderOps")
def file_claim():
    body = get_body()
    # Existence (priority 3): body hwb reference resolves.
    if isinstance(body.get("hwb_id"), str):
        svc.get_hwb(body["hwb_id"])
    hwb_id = req_nonempty_str(body, "hwb_id")
    hwb = store.hwbs[hwb_id]
    # State gate (priority 5): the waybill must be DELIVERED.
    if hwb.status != "DELIVERED":
        raise ApiError(
            ERR_HWB_NOT_DELIVERED,
            f"House waybill status is {hwb.status}; claim filing requires DELIVERED.",
            409,
        )
    # Malformed input (priority 8).
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    claimed_amount = req_num(body, "claimed_amount", exclusive_minimum=0)
    # One open claim per waybill (priority 8).
    for c in store.claims.values():
        if c.hwb_id == hwb.id and c.status in svc.OPEN_CLAIM_STATES:
            raise ApiError(
                ERR_DUPLICATE_OPEN_CLAIM,
                "Another claim on this waybill is still open.",
                409,
            )
    # Filing window (priority 10); filing exactly at the deadline is allowed.
    deadline = hwb.delivered_at_utc + timedelta(days=FILING_WINDOW_DAYS[claim_type])
    if store.now() > deadline:
        raise ApiError(
            ERR_CLAIM_FILING_DEADLINE_PASSED,
            f"{claim_type} claims must be filed within {FILING_WINDOW_DAYS[claim_type]} days of delivery.",
            422,
        )
    basis, limit = svc.liability_limit(hwb, claimed_amount)
    c = svc.fresh_rec(
        hwb_id=hwb.id,
        claim_type=claim_type,
        claimed_amount=claimed_amount,
        liability_basis=basis,
        liability_limit_amount=limit,
        approved_amount=None,
        counter_amount=None,
        review_round_count=0,
        status="FILED",
    )
    store.claims[c.id] = c
    return ok(svc.claim_json(c), 201)


@bp.get("/claims/<cid>")
@require_roles(*ALL_ROLES)
def get_claim(cid):
    return ok(svc.claim_json(svc.get_claim(cid)), 200)


@bp.post("/claims/<cid>/start-review")
@require_roles("ClaimsAdjuster")
def start_review(cid):
    c = svc.get_claim(cid)
    if c.status != "FILED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Claim status is {c.status}; start-review requires FILED.",
            409,
        )
    c.status = "UNDER_REVIEW"
    svc.touch(c)
    return ok(svc.claim_json(c), 200)


@bp.post("/claims/<cid>/resolve-review")
@require_roles("ClaimsAdjuster")
def resolve_review(cid):
    c = svc.get_claim(cid)
    if c.status != "UNDER_REVIEW":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Claim status is {c.status}; resolve-review requires UNDER_REVIEW.",
            409,
        )
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    opt_str(body, "reason", None)  # optional, accepted and not persisted
    if outcome == "APPROVED":
        amount = req_num(body, "approved_amount", exclusive_minimum=0)
        # Cap: min(claimed_amount, liability_limit_amount) — inclusive.
        cap = min(dec(c.claimed_amount), dec(c.liability_limit_amount))
        if amount > cap:
            raise ApiError(
                ERR_AMOUNT_EXCEEDS_LIABILITY,
                "approved_amount exceeds min(claimed_amount, liability_limit_amount).",
                422,
            )
        c.approved_amount = amount
        c.status = "APPROVED"
    elif outcome == "DENIED":
        c.status = "DENIED"
    else:  # COUNTERED
        amount = req_num(body, "counter_amount", exclusive_minimum=0)
        # The counteroffer is capped by the liability limit ALONE (PRD §3.8).
        if amount > dec(c.liability_limit_amount):
            raise ApiError(
                ERR_AMOUNT_EXCEEDS_LIABILITY,
                "counter_amount exceeds liability_limit_amount.",
                422,
            )
        c.counter_amount = amount
        c.status = "COUNTERED"
    svc.touch(c)
    return ok(svc.claim_json(c), 200)


@bp.post("/claims/<cid>/rebut")
@require_roles("ForwarderOps")
def rebut(cid):
    c = svc.get_claim(cid)
    if c.status != "COUNTERED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Claim status is {c.status}; rebut requires COUNTERED.",
            409,
        )
    c.status = "UNDER_REVIEW"
    c.review_round_count += 1
    svc.touch(c)
    return ok(svc.claim_json(c), 200)


@bp.post("/claims/<cid>/accept-counter")
@require_roles("ForwarderOps")
def accept_counter(cid):
    c = svc.get_claim(cid)
    if c.status != "COUNTERED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Claim status is {c.status}; accept-counter requires COUNTERED.",
            409,
        )
    c.approved_amount = c.counter_amount
    c.status = "SETTLED"
    svc.touch(c)
    return ok(svc.claim_json(c), 200)


@bp.post("/claims/<cid>/settle")
@require_roles("ClaimsAdjuster")
def settle(cid):
    c = svc.get_claim(cid)
    if c.status != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Claim status is {c.status}; settle requires APPROVED.",
            409,
        )
    c.status = "SETTLED"
    svc.touch(c)
    return ok(svc.claim_json(c), 200)
