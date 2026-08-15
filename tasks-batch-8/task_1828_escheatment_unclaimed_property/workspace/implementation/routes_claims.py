"""Owner claim endpoints (PRD 3.7)."""

from flask import Blueprint

import clock
import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import (
    new_entity, touch, get_property_or_404, get_claim_or_404,
    check_claimant_owner_scope, find_applicable_rule, recoverable_base_cents,
    confirmed_remittance_for_property, round_half_up_cents,
    CLAIM_FEE_BP, CLAIM_FEE_FREE_CAP_CENTS, BP_DENOMINATOR,
)

bp = Blueprint("claims", __name__)

NON_TERMINAL_CLAIM_STATES = ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED")


def claim_view(c):
    return {
        "id": c["id"],
        "property_id": c["property_id"],
        "claimant_owner_id": c["claimant_owner_id"],
        "claim_type": c["claim_type"],
        "evidence_ref": c["evidence_ref"],
        "status": c["status"],
        "reviewed_by_user_id": c["reviewed_by_user_id"],
        "decided_by_user_id": c["decided_by_user_id"],
        "denial_reason": c["denial_reason"],
        "approved_base_cents": c["approved_base_cents"],
        "approved_interest_cents": c["approved_interest_cents"],
        "processing_fee_cents": c["processing_fee_cents"],
        "approved_payout_cents": c["approved_payout_cents"],
        "paid_date": c["paid_date"].isoformat() if c["paid_date"] else None,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/escheatment/owner-claims")
def create_claim():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Claimant",))
    data = mw.body_json()
    property_id = mw.req_string(data, "property_id")
    evidence_ref = mw.opt_string(data, "evidence_ref", None)
    prop = get_property_or_404(property_id)
    # Ownership scoping (layer 5): claimant may only claim own property.
    if ctx.user_id != prop["owner_id"]:
        raise_error(
            errors.ERR_OWNERSHIP_SCOPE_VIOLATION,
            "A claimant may only claim their own property",
        )
    if prop["status"] not in ("REMITTED", "ESCHEATED"):
        raise_error(
            errors.ERR_PROPERTY_NOT_CLAIMABLE,
            "Claim creation requires the property to be REMITTED or ESCHEATED",
        )
    for existing in db.claims.values():
        if existing["property_id"] == prop["id"] and existing["status"] in NON_TERMINAL_CLAIM_STATES:
            raise_error(
                errors.ERR_DUPLICATE_ACTIVE_CLAIM,
                "A non-terminal claim already exists for this property",
            )
    base = recoverable_base_cents(prop)
    if base is None or base <= 0:
        raise_error(
            errors.ERR_CLAIM_EXCEEDS_RECOVERABLE,
            "The recoverable base for this property is not greater than zero",
        )
    claim_type = "SECURITIES" if prop["property_type"] == "BROKERAGE_SHARES" else "CASH"
    claim = new_entity({
        "property_id": prop["id"],
        "claimant_owner_id": ctx.user_id,
        "claim_type": claim_type,
        "evidence_ref": evidence_ref,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "decided_by_user_id": None,
        "denial_reason": None,
        "approved_base_cents": None,
        "approved_interest_cents": None,
        "processing_fee_cents": None,
        "approved_payout_cents": None,
        "paid_date": None,
    })
    db.claims[claim["id"]] = claim
    return resp.success(claim_view(claim), "object", 201)


@bp.get("/escheatment/owner-claims")
def list_claims():
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer", "ClaimsExaminer", "ClaimsApprover"))
    limit, offset = mw.pagination_params()
    items = list(db.claims.values())
    property_id = mw.request.args.get("property_id")
    if property_id is not None:
        items = [c for c in items if c["property_id"] == property_id]
    status = mw.request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([claim_view(c) for c in page], "array", 200, pagination=meta)


@bp.get("/escheatment/owner-claims/<claimId>")
def get_claim(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    claim = get_claim_or_404(claimId)
    check_claimant_owner_scope(ctx, claim["claimant_owner_id"])
    return resp.success(claim_view(claim), "object", 200)


@bp.post("/escheatment/owner-claims/<claimId>/start-review")
def start_review(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ClaimsExaminer",))
    mw.body_json(required=False)
    claim = get_claim_or_404(claimId)
    if claim["status"] != "SUBMITTED":
        raise_error(errors.ERR_CLAIM_NOT_SUBMITTED, "Start-review requires a SUBMITTED claim")
    claim["status"] = "UNDER_REVIEW"
    claim["reviewed_by_user_id"] = ctx.user_id
    touch(claim)
    return resp.success(claim_view(claim), "object", 200)


@bp.post("/escheatment/owner-claims/<claimId>/request-info")
def request_info(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ClaimsExaminer",))
    data = mw.body_json()
    mw.req_string(data, "info_request_note")
    claim = get_claim_or_404(claimId)
    if claim["status"] != "UNDER_REVIEW":
        raise_error(
            errors.ERR_CLAIM_NOT_UNDER_REVIEW,
            "Request-info requires an UNDER_REVIEW claim",
        )
    claim["status"] = "MORE_INFO_REQUESTED"
    touch(claim)
    return resp.success(claim_view(claim), "object", 200)


@bp.post("/escheatment/owner-claims/<claimId>/submit-info")
def submit_info(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Claimant",))
    data = mw.body_json()
    mw.req_string(data, "info_response_ref")
    claim = get_claim_or_404(claimId)
    if ctx.user_id != claim["claimant_owner_id"]:
        raise_error(
            errors.ERR_OWNERSHIP_SCOPE_VIOLATION,
            "Only the owning claimant may submit information",
        )
    if claim["status"] != "MORE_INFO_REQUESTED":
        raise_error(
            errors.ERR_CLAIM_NOT_AWAITING_INFO,
            "Submit-info requires a MORE_INFO_REQUESTED claim",
        )
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return resp.success(claim_view(claim), "object", 200)


def _decision_prechecks(ctx, claim):
    if claim["status"] != "UNDER_REVIEW":
        raise_error(
            errors.ERR_CLAIM_NOT_UNDER_REVIEW,
            "Decision requires an UNDER_REVIEW claim",
        )
    if ctx.user_id == claim["reviewed_by_user_id"]:
        raise_error(
            errors.ERR_SEGREGATION_OF_DUTIES_VIOLATION,
            "The approver must differ from the reviewing examiner",
        )


@bp.post("/escheatment/owner-claims/<claimId>/approve")
def approve_claim(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ClaimsApprover",))
    mw.body_json(required=False)
    claim = get_claim_or_404(claimId)
    _decision_prechecks(ctx, claim)
    prop = get_property_or_404(claim["property_id"])
    if prop["status"] not in ("REMITTED", "ESCHEATED"):
        raise_error(
            errors.ERR_PROPERTY_NOT_CLAIMABLE,
            "Approve requires the property to still be REMITTED or ESCHEATED",
        )
    # claim_payout pinned order: base -> interest -> gross -> fee tier -> fee
    # -> payout (PRD 3.7).
    base = recoverable_base_cents(prop)
    if claim["claim_type"] == "CASH":
        rule = find_applicable_rule(
            prop["state_code"], prop["property_type"], prop["last_contact_date"]
        )
        rate_bp = rule["annual_interest_rate_bp"] if rule else 0
        rem = confirmed_remittance_for_property(prop["id"])
        approve_date = clock.today()
        if rem is not None and rem["confirmed_date"] is not None:
            days_held = max(0, (approve_date - rem["confirmed_date"]).days)
        else:
            days_held = 0
        interest = round_half_up_cents(base * rate_bp * days_held, BP_DENOMINATOR)
    else:
        interest = 0
    gross = base + interest
    if gross > CLAIM_FEE_FREE_CAP_CENTS:
        fee = round_half_up_cents(gross * CLAIM_FEE_BP, 10_000)
    else:
        fee = 0
    claim["approved_base_cents"] = base
    claim["approved_interest_cents"] = interest
    claim["processing_fee_cents"] = fee
    claim["approved_payout_cents"] = gross - fee
    claim["decided_by_user_id"] = ctx.user_id
    claim["status"] = "APPROVED"
    touch(claim)
    return resp.success(claim_view(claim), "object", 200)


@bp.post("/escheatment/owner-claims/<claimId>/deny")
def deny_claim(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("ClaimsApprover",))
    data = mw.body_json()
    reason = mw.req_string(data, "denial_reason")
    claim = get_claim_or_404(claimId)
    _decision_prechecks(ctx, claim)
    claim["status"] = "DENIED"
    claim["denial_reason"] = reason
    claim["decided_by_user_id"] = ctx.user_id
    touch(claim)
    return resp.success(claim_view(claim), "object", 200)


@bp.post("/escheatment/owner-claims/<claimId>/pay")
def pay_claim(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("TreasuryOps",))
    mw.body_json(required=False)
    claim = get_claim_or_404(claimId)
    if claim["status"] != "APPROVED":
        raise_error(errors.ERR_CLAIM_NOT_APPROVED, "Pay requires an APPROVED claim")
    claim["status"] = "PAID"
    claim["paid_date"] = clock.today()
    touch(claim)
    # Cascade: property REMITTED -> REUNITED or ESCHEATED -> REUNITED.
    prop = db.properties.get(claim["property_id"])
    if prop is not None and prop["status"] in ("REMITTED", "ESCHEATED"):
        prop["status"] = "REUNITED"
        prop["reunited_date"] = clock.today()
        touch(prop)
    return resp.success(claim_view(claim), "object", 200)


@bp.post("/escheatment/owner-claims/<claimId>/withdraw")
def withdraw_claim(claimId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Claimant",))
    mw.body_json(required=False)
    claim = get_claim_or_404(claimId)
    if ctx.user_id != claim["claimant_owner_id"]:
        raise_error(
            errors.ERR_OWNERSHIP_SCOPE_VIOLATION,
            "Only the owning claimant may withdraw the claim",
        )
    if claim["status"] not in ("SUBMITTED", "MORE_INFO_REQUESTED"):
        raise_error(
            errors.ERR_CLAIM_NOT_WITHDRAWABLE,
            "Withdraw requires the claim to be SUBMITTED or MORE_INFO_REQUESTED",
        )
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return resp.success(claim_view(claim), "object", 200)
