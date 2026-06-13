"""Claim endpoints: file/get/list, issue-rma, adjudicate, fulfill, withdraw.

PRD §3.5 (file/withdraw), §3.6 (issue-rma), §3.7 (adjudicate), §3.8 (refund
depreciation), §3.10 (fulfill).
"""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_CLAIM_COOLDOWN,
    ERR_COVERAGE_EXHAUSTED,
    ERR_DEFECT_NOT_COVERED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_REFUND_NOT_ELIGIBLE,
    ERR_WARRANTY_EXPIRED,
)
from middleware import require_roles
from response import ok_array, ok_object
from services import calc, common
from services.registration_svc import (
    active_extensions,
    bump,
    make_ledger_entry,
    mint_common,
    public,
    public_registration,
    reconcile,
    recompute_remaining_coverage,
)
from services.timeutil import parse_iso, whole_months_between

bp = Blueprint("claims", __name__)

DEFECT_CATEGORIES = {"MANUFACTURING", "WEAR_AND_TEAR", "ACCIDENTAL", "COSMETIC"}
RESOLUTION_TYPES = {"REPAIR", "REPLACE", "REFUND"}
DECISIONS = {"approve", "deny"}


def _get_claim_or_404(cid):
    claim = db.claims.get(cid)
    if claim is None:
        raise APIError(ERR_NOT_FOUND, 404, "Claim not found")
    return claim


# ---- file claim -------------------------------------------------------------

@bp.post("/claims")
def file_claim():
    require_roles(["Owner"])
    body = common.get_json_body()
    common.require_fields(body, ["registration_id", "defect_category", "reported_date"])
    registration_id = common.require_str(body, "registration_id")
    defect_category = common.require_enum(body, "defect_category", DEFECT_CATEGORIES)
    reported_date = common.require_str(body, "reported_date")
    try:
        parse_iso(reported_date)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "reported_date must be ISO 8601")

    reg = db.registrations.get(registration_id)
    if reg is None:
        raise APIError(ERR_NOT_FOUND, 404, "Registration not found")

    # ownership (priority 6): owner must own the registration
    if reg["owner_user_id"] != g.user_id:
        raise APIError(ERR_NOT_OWNER, 403, "Caller is not the registration owner")

    # derive current warranty_end_date / status for the window check
    reconcile(reg)

    # warranty window (priority 8): reported_date <= warranty_end_date, reg not EXPIRED
    if reg["status"] == "EXPIRED":
        raise APIError(ERR_WARRANTY_EXPIRED, 422, "Registration is expired")
    if reg["warranty_end_date"] is not None:
        if parse_iso(reported_date) > parse_iso(reg["warranty_end_date"]):
            raise APIError(ERR_WARRANTY_EXPIRED, 422, "reported_date past warranty_end_date")

    # cooldown (priority 15): strictly > 30 days after most recent non-CLOSED claim
    prior = [c for c in db.claims.values()
             if c["registration_id"] == registration_id and c["status"] != "CLOSED"]
    if prior:
        prior.sort(key=lambda c: parse_iso(c["reported_date"]))
        most_recent = prior[-1]
        gap_days = (parse_iso(reported_date) - parse_iso(most_recent["reported_date"])).total_seconds() / 86400.0
        if gap_days <= calc.CLAIM_COOLDOWN_DAYS:
            raise APIError(ERR_CLAIM_COOLDOWN, 409,
                           "New claim within cooldown of a prior non-closed claim")

    claim = {
        "registration_id": registration_id,
        "defect_category": defect_category,
        "reported_date": reported_date,
        "resolution_type": None,
        "rma_number": None,
        "assessed_value_cents": 0,
        "claims_processor_user_id": None,
        "status": "INTAKE",
    }
    mint_common(claim)
    db.claims[claim["id"]] = claim
    return ok_object(public(claim), 201)


@bp.get("/claims/<cid>")
def get_claim(cid):
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    return ok_object(public(_get_claim_or_404(cid)))


@bp.get("/claims")
def list_claims():
    require_roles(["WarrantyAdmin", "Owner", "ClaimsProcessor"])
    limit, offset = common.parse_pagination()
    registration_id = request.args.get("registration_id")
    status = request.args.get("status")
    rows = list(db.claims.values())
    if registration_id is not None:
        rows = [c for c in rows if c["registration_id"] == registration_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = common.paginate(rows, limit, offset)
    return ok_array([public(c) for c in page], limit, offset, total)


# ---- issue RMA --------------------------------------------------------------

@bp.post("/claims/<cid>/issue-rma")
def issue_rma(cid):
    require_roles(["ClaimsProcessor"])
    claim = _get_claim_or_404(cid)
    if claim["status"] != "INTAKE":
        raise APIError(ERR_INVALID_STATE, 409, "Claim is not in INTAKE")
    reg = db.registrations[claim["registration_id"]]
    reconcile(reg)
    # State precondition (priority 4, PRD §2.10/§3.6): the INTAKE->RMA_ISSUED
    # transition is legal only when the parent registration is ACTIVE and its
    # proof_status is VALIDATED. An EXPIRED registration ("no longer eligible")
    # is the business-temporal path (ERR_WARRANTY_EXPIRED, priority 8); any other
    # non-ACTIVE status (REGISTERED, TRANSFER_PENDING, VOIDED) or an unvalidated
    # proof is an illegal-state condition -> ERR_INVALID_STATE.
    if reg["status"] == "EXPIRED":
        raise APIError(ERR_WARRANTY_EXPIRED, 422, "Registration is expired")
    if reg["status"] != "ACTIVE" or reg["proof_status"] != "VALIDATED":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Registration must be ACTIVE with a VALIDATED proof to issue RMA")
    # Business-temporal (priority 8): reported_date past warranty_end_date.
    if reg["warranty_end_date"] is not None:
        if parse_iso(claim["reported_date"]) > parse_iso(reg["warranty_end_date"]):
            raise APIError(ERR_WARRANTY_EXPIRED, 422, "reported_date past warranty_end_date")

    claim["rma_number"] = "RMA-" + db.new_uuid().replace("-", "")[:12].upper()
    claim["claims_processor_user_id"] = g.user_id
    claim["status"] = "RMA_ISSUED"
    bump(claim)
    bump(reg)
    return ok_object(public(claim))


# ---- adjudicate -------------------------------------------------------------

@bp.post("/claims/<cid>/adjudicate")
def adjudicate(cid):
    require_roles(["WarrantyAdmin"])
    claim = _get_claim_or_404(cid)
    body = common.get_json_body()
    decision = body.get("decision")
    if decision not in DECISIONS:
        raise APIError(ERR_INVALID_REQUEST, 400, "decision must be 'approve' or 'deny'")

    # state (priority 4)
    if claim["status"] != "RMA_ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "Claim is not under RMA")

    reg = db.registrations[claim["registration_id"]]
    reconcile(reg)
    pre_remaining = reg["remaining_coverage_cents"]

    if decision == "deny":
        claim["status"] = "DENIED"
        # resolution_type stays null
        bump(claim)
        bump(reg)
        return ok_object(public(claim))

    # approve path
    resolution_type = body.get("resolution_type")
    if resolution_type not in RESOLUTION_TYPES:
        raise APIError(ERR_INVALID_REQUEST, 400, "resolution_type must be REPAIR/REPLACE/REFUND")

    # defect coverage (priority 7): approval requires MANUFACTURING
    if claim["defect_category"] != "MANUFACTURING":
        raise APIError(ERR_DEFECT_NOT_COVERED, 422,
                       "Only MANUFACTURING defects may be approved")

    active_tier = db.coverage_tiers.get(reg.get("active_tier_id"))

    # refund eligibility (priority 9)
    if resolution_type == "REFUND":
        if active_tier is None or not active_tier.get("refund_eligible", True):
            raise APIError(ERR_REFUND_NOT_ELIGIBLE, 422,
                           "Active tier does not permit REFUND")

    # fiscal coverage (priority 12): remaining must be > 0
    if pre_remaining <= 0:
        raise APIError(ERR_COVERAGE_EXHAUSTED, 422, "Remaining coverage is exhausted")

    # compute assessed value + ledger reason
    if resolution_type == "REFUND":
        product = db.products[reg["product_id"]]
        base = min(reg["purchase_price_cents"], product["msrp_cents"])
        elapsed = whole_months_between(parse_iso(reg["purchase_date"]),
                                       parse_iso(claim["reported_date"]))
        raw = calc.refund_proration_raw(
            base, elapsed, product["serviceable_lifespan_months"],
            active_tier["depreciation_method"],
        )
        assessed = min(raw, pre_remaining)
        reason = "REFUND_PAYOUT"
    elif resolution_type == "REPAIR":
        assessed = common.require_int(body, "repair_cost_cents", minimum=0)
        reason = "REPAIR_COST"
    else:  # REPLACE
        assessed = common.require_int(body, "replace_cost_cents", minimum=0)
        reason = "REPLACE_COST"

    # fiscal coverage (priority 12): assessed must not exceed remaining
    if assessed > pre_remaining:
        raise APIError(ERR_COVERAGE_EXHAUSTED, 422,
                       "assessed_value_cents exceeds remaining coverage")

    claim["resolution_type"] = resolution_type
    claim["assessed_value_cents"] = assessed
    claim["status"] = "ADJUDICATED"
    # write DEBIT ledger entry (read order pinned: cap used pre-debit value)
    make_ledger_entry(reg["id"], "DEBIT", reason, assessed, claim_id=claim["id"])
    # reconcile post-debit remaining coverage
    reconcile(reg)
    bump(claim)
    bump(reg)
    return ok_object(public(claim))


# ---- fulfill ----------------------------------------------------------------

@bp.post("/claims/<cid>/fulfill")
def fulfill(cid):
    require_roles(["ClaimsProcessor"])
    claim = _get_claim_or_404(cid)
    if claim["status"] != "ADJUDICATED" or claim["resolution_type"] is None:
        raise APIError(ERR_INVALID_STATE, 409, "Claim is not ADJUDICATED with a resolution")
    claim["status"] = "FULFILLED"
    bump(claim)
    reg = db.registrations[claim["registration_id"]]
    if claim["resolution_type"] == "REFUND":
        reg["status"] = "VOIDED"
        for ext in active_extensions(reg["id"]):
            ext["status"] = "CANCELLED"
            bump(ext)
    reconcile(reg)
    bump(reg)
    return ok_object(public(claim))


# ---- withdraw ---------------------------------------------------------------

@bp.post("/claims/<cid>/withdraw")
def withdraw(cid):
    require_roles(["Owner"])
    claim = _get_claim_or_404(cid)
    if claim["status"] != "RMA_ISSUED":
        raise APIError(ERR_INVALID_STATE, 409, "Claim is not under RMA")
    reg = db.registrations[claim["registration_id"]]
    if reg["owner_user_id"] != g.user_id:
        raise APIError(ERR_NOT_OWNER, 403, "Caller is not the registration owner")
    claim["status"] = "CLOSED"
    bump(claim)
    bump(reg)
    return ok_object(public(claim))
