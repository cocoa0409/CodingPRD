"""Claim endpoints: submission, review pipeline, approval, payment, reversal."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

from db import STORE
from errors import (err, ERR_CLAIM_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND,
                    ERR_MEMBER_NOT_FOUND, ERR_VISIT_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_INVALID_AMOUNT,
                    ERR_ENROLLMENT_NOT_ACTIVE, ERR_MEMBER_TERMINATED,
                    ERR_CLAIM_FILING_DEADLINE, ERR_SERVICE_OUTSIDE_PLAN_PERIOD,
                    ERR_DUPLICATE_RECEIPT, ERR_VISIT_NOT_VERIFIED,
                    ERR_CLAIM_NOT_REVIEWABLE, ERR_CLAIM_TERMINAL,
                    ERR_PAYMENT_NOT_REVERSIBLE, ERR_FRAUD_HOLD,
                    ERR_FUNDING_NOT_ACTIVE, ERR_QUARTERLY_CAP_EXCEEDED,
                    ERR_ALLOWANCE_EXCEEDED, ERR_FUNDING_INSUFFICIENT,
                    ERR_MAX_RESUBMISSIONS, ERR_FORBIDDEN_ROLE)
from middleware import (require_roles, is_member, is_provider_operator,
                        member_owns, provider_owns)
from response import success, paginate
from services.core import (new_entity, touch, serialize, sort_created,
                           tier_for, claim_fraud_hold, reject_claim,
                           funding_for_claim, append_funding_entry,
                           exhaustion_cascade, clawback_recovery,
                           OPEN_REVIEW, MAX_RESUBMISSIONS, FILING_DEADLINE_DAYS)
from util import (body_json, req, opt, as_str, as_int, as_num, as_list,
                  check_enum, parse_dt, quarter_key_of, rhu)

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("REIMBURSEMENT", "DIRECT_PAY")
READ_ROLES = ("BenefitsAdmin", "Auditor", "ClaimsReviewer", "Member", "ProviderOperator")


def get_claim(cid):
    c = STORE.claims.get(cid)
    if c is None:
        raise err(ERR_CLAIM_NOT_FOUND, 404, "claim id does not resolve")
    return c


def calc_claimed_amount(line_items):
    """calc_line_rounding: round_half_up PER LINE ITEM, then sum."""
    total = 0
    for li in line_items:
        line = (Decimal(li["unit_amount_cents"]) * Decimal(li["quantity"])
                * (Decimal(1) + Decimal(str(li["tax_pct"]))))
        total += rhu(line)
    return total


def _validate_line_items(raw):
    items = as_list(raw, "line_items")
    parsed = []
    for li in items:
        if not isinstance(li, dict):
            raise err(ERR_INVALID_REQUEST, 400, "each line item must be an object")
        description = as_str(req(li, "description"), "description")
        unit = as_int(req(li, "unit_amount_cents"), "unit_amount_cents")
        qty = as_int(req(li, "quantity"), "quantity")
        tax = as_num(req(li, "tax_pct"), "tax_pct")
        if unit <= 0:
            raise err(ERR_INVALID_AMOUNT, 400, "unit_amount_cents must be positive")
        if qty < 1:
            raise err(ERR_INVALID_AMOUNT, 400, "quantity must be at least one")
        parsed.append({"description": description, "unit_amount_cents": unit,
                       "quantity": qty, "tax_pct": tax})
    return parsed


@bp.post("/api/claims")
def create_claim():
    require_roles("Member", "ProviderOperator")
    body = body_json()
    enrollment_id = as_str(req(body, "enrollment_id"), "enrollment_id")
    claim_type = check_enum(req(body, "claim_type"), CLAIM_TYPES, "claim_type")
    # routing is fixed by claim_type: Member <-> REIMBURSEMENT, ProviderOperator <-> DIRECT_PAY
    if is_member() and claim_type != "REIMBURSEMENT":
        raise err(ERR_FORBIDDEN_ROLE, 403, "Member callers submit REIMBURSEMENT claims")
    if is_provider_operator() and claim_type != "DIRECT_PAY":
        raise err(ERR_FORBIDDEN_ROLE, 403, "ProviderOperator callers submit DIRECT_PAY claims")
    service_date_raw = req(body, "service_date")
    receipt_ref = as_str(req(body, "receipt_ref"), "receipt_ref")
    line_items = _validate_line_items(req(body, "line_items"))
    visit_ids = opt(body, "visit_ids", [])
    visit_ids = [as_str(v, "visit_ids[]") for v in as_list(visit_ids, "visit_ids")]
    if is_member():
        member_id = g.user_id
    else:
        member_id = as_str(req(body, "member_id"), "member_id")
    # existence: body FKs, left to right
    enr = STORE.enrollments.get(enrollment_id)
    if enr is None:
        raise err(ERR_ENROLLMENT_NOT_FOUND, 404, "enrollment id does not resolve")
    member = STORE.members.get(member_id)
    if member is None:
        raise err(ERR_MEMBER_NOT_FOUND, 404, "member id does not resolve")
    visits = []
    for vid in visit_ids:
        v = STORE.visits.get(vid)
        if v is None:
            raise err(ERR_VISIT_NOT_FOUND, 404, "id inside visit_ids does not resolve")
        visits.append(v)
    service_date = parse_dt(service_date_raw)
    # ownership: Member may only claim against their own enrollment
    if is_member():
        member_owns(enr["member_id"])
    # state
    if member["eligibility_status"] == "TERMINATED":
        raise err(ERR_MEMBER_TERMINATED, 409, "member TERMINATED")
    if enr["status"] != "ACTIVE":
        raise err(ERR_ENROLLMENT_NOT_ACTIVE, 409, "claim creation requires enrollment ACTIVE")
    # temporal: filing deadline (exactly 90 days old is allowed)
    if STORE.clock - service_date > timedelta(days=FILING_DEADLINE_DAYS):
        raise err(ERR_CLAIM_FILING_DEADLINE, 422,
                  "service_date more than 90 days before the logical clock")
    # temporal: service_date inside the plan period (closed both ends)
    plan = STORE.plans.get(enr["plan_id"])
    if plan is not None and not (plan["_ps"] <= service_date <= plan["_pe"]):
        raise err(ERR_SERVICE_OUTSIDE_PLAN_PERIOD, 422,
                  "claim service_date outside plan period")
    # business: receipt_ref unique per member across non-REJECTED claims
    for c in STORE.claims.values():
        if (c["member_id"] == member_id and c["receipt_ref"] == receipt_ref
                and c["review_status"] != "REJECTED"):
            raise err(ERR_DUPLICATE_RECEIPT, 409,
                      "receipt_ref already used by a non-REJECTED claim of this member")
    # business: every referenced visit must be VERIFIED and owned by the claimant
    for v in visits:
        if v["status"] != "VERIFIED" or v["member_id"] != member_id:
            raise err(ERR_VISIT_NOT_VERIFIED, 422,
                      "visit_ids contains a visit not VERIFIED or not owned by the claimant")
    # provider resolution
    if claim_type == "DIRECT_PAY":
        provider_id = g.user_id
    else:
        provider_id = None
        if visits:
            provider_id = visits[0]["provider_id"]
        elif body.get("provider_id") is not None:
            provider_id = as_str(body.get("provider_id"), "provider_id")
    claimed = calc_claimed_amount(line_items)
    c = new_entity()
    c.update({
        "enrollment_id": enrollment_id,
        "member_id": member_id,
        "provider_id": provider_id,
        "claim_type": claim_type,
        "service_date": service_date_raw,
        "receipt_ref": receipt_ref,
        "line_items": line_items,
        "visit_ids": visit_ids,
        "claimed_amount_cents": claimed,
        "approved_amount_cents": None,
        "review_status": "SUBMITTED",
        "payment_status": "UNPAID",
        "resubmission_count": 0,
        "fraud_hold": False,
        "quarter_key": quarter_key_of(service_date),
        "_service_dt": service_date,
        "_paid_at": None,
    })
    c["fraud_hold"] = claim_fraud_hold(c)
    STORE.claims[c["id"]] = c
    # reservation against the allowance
    enr["reserved_cents"] += claimed
    touch(enr)
    return success(serialize(c), 201)


@bp.get("/api/claims/<cid>")
def read_claim(cid):
    require_roles(*READ_ROLES)
    c = get_claim(cid)
    member_owns(c["member_id"])
    provider_owns(c["provider_id"])
    c["fraud_hold"] = claim_fraud_hold(c)
    return success(serialize(c))


@bp.get("/api/claims")
def list_claims():
    require_roles(*READ_ROLES)
    items = sort_created(STORE.claims.values())
    member_id = request.args.get("member_id")
    enrollment_id = request.args.get("enrollment_id")
    provider_id = request.args.get("provider_id")
    review_status = request.args.get("review_status")
    if is_member():
        if member_id is not None and member_id != g.user_id:
            member_owns(member_id)
        items = [c for c in items if c["member_id"] == g.user_id]
    elif member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if is_provider_operator():
        if provider_id is not None and provider_id != g.user_id:
            provider_owns(provider_id)
        items = [c for c in items if c["provider_id"] == g.user_id]
    elif provider_id is not None:
        items = [c for c in items if c["provider_id"] == provider_id]
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if review_status is not None:
        items = [c for c in items if c["review_status"] == review_status]
    for c in items:
        c["fraud_hold"] = claim_fraud_hold(c)
    return paginate([serialize(c) for c in items])


# ---------------------------------------------------------------------------
# Review pipeline
# ---------------------------------------------------------------------------

def _review_gate(c, allowed_from):
    if c["review_status"] == "REJECTED":
        raise err(ERR_CLAIM_TERMINAL, 409, "claim review_status REJECTED is terminal")
    if c["review_status"] not in allowed_from:
        raise err(ERR_CLAIM_NOT_REVIEWABLE, 409,
                  "claim review transition attempted from a state that does not allow it")


@bp.post("/api/claims/<cid>/start-review")
def start_review(cid):
    require_roles("ClaimsReviewer")
    c = get_claim(cid)
    _review_gate(c, ("SUBMITTED",))
    c["review_status"] = "UNDER_REVIEW"
    touch(c)
    return success(serialize(c))


def calc_claim_payable(claim, enr):
    """Returns (approved, annual_headroom, quarterly_headroom)."""
    tier = tier_for(enr["plan_id"], enr["tier_code"]) or enr["_tier_snapshot"]
    provider = STORE.providers.get(claim["provider_id"]) if claim["provider_id"] else None
    nt = provider["network_tier"] if provider is not None else "OUT_OF_NETWORK"
    k = Decimal(str(tier[{"IN_NETWORK": "in_network_pct",
                          "PREFERRED": "preferred_pct",
                          "OUT_OF_NETWORK": "out_of_network_pct"}[nt]]))
    covered = rhu(Decimal(claim["claimed_amount_cents"]) * k)
    own_reserved = claim["claimed_amount_cents"] if claim["review_status"] in OPEN_REVIEW else 0
    annual_headroom = (enr["annual_allowance_cents"] - enr["used_cents"]
                       - (enr["reserved_cents"] - own_reserved))
    other_q_reserved = 0
    for c2 in STORE.claims.values():
        if c2["enrollment_id"] != enr["id"] or c2["id"] == claim["id"]:
            continue
        if c2["quarter_key"] != enr["quarter_key"]:
            continue
        if c2["review_status"] in OPEN_REVIEW:
            other_q_reserved += c2["claimed_amount_cents"]
        elif c2["review_status"] == "APPROVED" and c2["payment_status"] == "UNPAID":
            other_q_reserved += c2["approved_amount_cents"] or 0
    quarterly_headroom = (enr["quarterly_cap_cents"] - enr["quarter_used_cents"]
                          - other_q_reserved)
    approved = min(covered, tier["per_claim_cap_cents"], annual_headroom, quarterly_headroom)
    return approved, annual_headroom, quarterly_headroom


@bp.post("/api/claims/<cid>/approve")
def approve_claim(cid):
    require_roles("ClaimsReviewer")
    c = get_claim(cid)
    _review_gate(c, ("UNDER_REVIEW",))
    c["fraud_hold"] = claim_fraud_hold(c)
    # approval gate, in PRD section 3.8 order
    if c["fraud_hold"]:
        raise err(ERR_FRAUD_HOLD, 422, "claim is fraud-held")
    enr = STORE.enrollments.get(c["enrollment_id"])
    if enr is None or enr["status"] != "ACTIVE":
        raise err(ERR_ENROLLMENT_NOT_ACTIVE, 409, "approval requires enrollment ACTIVE")
    acct = funding_for_claim(c)
    if acct is not None and acct["status"] == "SUSPENDED":
        raise err(ERR_FUNDING_NOT_ACTIVE, 409, "funding account SUSPENDED")
    approved, annual_headroom, quarterly_headroom = calc_claim_payable(c, enr)
    # fiscal windows: quarterly first, then annual, then funding availability
    if quarterly_headroom <= 0:
        raise err(ERR_QUARTERLY_CAP_EXCEEDED, 422, "quarterly cap window exhausted")
    if annual_headroom <= 0:
        raise err(ERR_ALLOWANCE_EXCEEDED, 422, "annual allowance window exhausted")
    if approved <= 0:
        raise err(ERR_ALLOWANCE_EXCEEDED, 422, "computed payable amount is not positive")
    available = acct["available_cents"] if acct is not None else 0
    if available < approved:
        raise err(ERR_FUNDING_INSUFFICIENT, 422,
                  "funding account available_cents below approved amount")
    # apply: rebalance enrollment reservation, place funding HOLD
    c["approved_amount_cents"] = approved
    enr["reserved_cents"] -= c["claimed_amount_cents"]
    enr["reserved_cents"] += approved
    touch(enr)
    if acct is not None:
        append_funding_entry(acct, c["id"], "HOLD", approved)
    c["review_status"] = "APPROVED"
    touch(c)
    return success(serialize(c))


@bp.post("/api/claims/<cid>/reject")
def reject_claim_endpoint(cid):
    require_roles("ClaimsReviewer")
    c = get_claim(cid)
    _review_gate(c, OPEN_REVIEW)
    reject_claim(c)
    return success(serialize(c))


@bp.post("/api/claims/<cid>/request-info")
def request_info(cid):
    require_roles("ClaimsReviewer")
    c = get_claim(cid)
    _review_gate(c, ("UNDER_REVIEW",))
    c["review_status"] = "NEEDS_INFO"
    touch(c)
    return success(serialize(c))


@bp.post("/api/claims/<cid>/resubmit")
def resubmit_claim(cid):
    require_roles("Member")
    c = get_claim(cid)
    member_owns(c["member_id"])
    _review_gate(c, ("NEEDS_INFO",))
    if c["resubmission_count"] >= MAX_RESUBMISSIONS:
        raise err(ERR_MAX_RESUBMISSIONS, 422, "resubmission_count already 3")
    c["resubmission_count"] += 1
    c["review_status"] = "UNDER_REVIEW"
    touch(c)
    return success(serialize(c))


# ---------------------------------------------------------------------------
# Payment axis
# ---------------------------------------------------------------------------

@bp.post("/api/claims/<cid>/pay")
def pay_claim(cid):
    require_roles("BenefitsAdmin")
    c = get_claim(cid)
    if c["review_status"] == "REJECTED":
        raise err(ERR_CLAIM_TERMINAL, 409, "claim review_status REJECTED is terminal")
    if c["review_status"] != "APPROVED" or c["payment_status"] != "UNPAID":
        raise err(ERR_CLAIM_NOT_REVIEWABLE, 409,
                  "pay requires review APPROVED and payment UNPAID")
    acct = funding_for_claim(c)
    if acct is None or acct["status"] != "FUNDED":
        raise err(ERR_FUNDING_NOT_ACTIVE, 409, "pay requires funding account FUNDED")
    approved = c["approved_amount_cents"]
    enr = STORE.enrollments[c["enrollment_id"]]
    paid_at = STORE.clock
    # funding: HOLD converts to DEBIT
    append_funding_entry(acct, c["id"], "DEBIT", approved)
    # enrollment ledger: reserved falls, used rises; quarter accumulation
    enr["reserved_cents"] -= approved
    enr["used_cents"] += approved
    if quarter_key_of(paid_at) == enr["quarter_key"]:
        enr["quarter_used_cents"] += approved
    touch(enr)
    c["payment_status"] = "PAID"
    c["_paid_at"] = paid_at
    touch(c)
    # exhaustion cascade
    exhaustion_cascade(enr)
    return success(serialize(c))


@bp.post("/api/claims/<cid>/reverse")
def reverse_claim(cid):
    require_roles("BenefitsAdmin")
    c = get_claim(cid)
    if c["payment_status"] in ("REVERSED", "CLAWED_BACK"):
        raise err(ERR_PAYMENT_NOT_REVERSIBLE, 409,
                  "payment already REVERSED or CLAWED_BACK")
    if c["review_status"] == "REJECTED":
        raise err(ERR_CLAIM_TERMINAL, 409, "claim review_status REJECTED is terminal")
    if c["review_status"] != "APPROVED":
        raise err(ERR_CLAIM_NOT_REVIEWABLE, 409, "reverse requires review APPROVED")
    acct = funding_for_claim(c)
    approved = c["approved_amount_cents"] or 0
    enr = STORE.enrollments.get(c["enrollment_id"])
    if c["payment_status"] == "UNPAID":
        # release the hold
        if acct is not None:
            append_funding_entry(acct, c["id"], "RELEASE", approved)
        if enr is not None:
            enr["reserved_cents"] -= approved
            touch(enr)
        c["payment_status"] = "REVERSED"
    else:  # PAID -> CLAWED_BACK
        if acct is not None:
            append_funding_entry(acct, c["id"], "CLAWBACK_CREDIT", approved)
        if enr is not None:
            enr["used_cents"] -= approved
            if c["_paid_at"] is not None and quarter_key_of(c["_paid_at"]) == enr["quarter_key"]:
                enr["quarter_used_cents"] -= approved
            touch(enr)
        c["payment_status"] = "CLAWED_BACK"
        if enr is not None:
            clawback_recovery(enr)
    touch(c)
    return success(serialize(c))
