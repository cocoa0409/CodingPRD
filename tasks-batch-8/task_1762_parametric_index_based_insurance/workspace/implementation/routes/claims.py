"""PayoutClaim endpoints (PRD §3.7): adjust, approve, decline, fraud hold,
release payment (cession waterfall + SoD)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_CLAIM_NOT_ADJUSTABLE, ERR_EVENT_NOT_VERIFIED,
    ERR_TIER_EXCEEDS_BREACH, ERR_POLICY_NOT_BOUND, ERR_HOLDER_BLACKLISTED,
    ERR_CLAIM_NOT_APPROVED, ERR_CLAIM_NOT_IN_FRAUD_HOLD, ERR_SOD_VIOLATION,
    ERR_CLAIM_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, pagination_params, paginate, sorted_by_created,
    get_program, get_claim_in_program, get_holder_in_program, get_policy_of_holder,
)
from services import domain, calc

bp = Blueprint("claims", __name__)

FRAUD_SCORE_AUTO_HOLD = 70


def _claim_context(programId, claimId):
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    pol = db.policies[claim["policy_id"]]
    idx = db.index_definitions[pol["index_definition_id"]]
    holder = db.policyholders[pol["policyholder_id"]]
    ev = db.trigger_events[claim["trigger_event_id"]]
    return prog, claim, pol, idx, holder, ev


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/programs/<programId>/claims")
def list_claims(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    limit, offset = pagination_params()
    pol_ids = {p["id"] for p in db.policies.values() if p["program_id"] == prog["id"]}
    items = [c for c in db.claims.values() if c["policy_id"] in pol_ids]
    items = _apply_claim_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


def _apply_claim_filters(items):
    pid = request.args.get("policy_id")
    tid = request.args.get("trigger_event_id")
    st = request.args.get("status")
    if pid is not None:
        items = [c for c in items if c["policy_id"] == pid]
    if tid is not None:
        items = [c for c in items if c["trigger_event_id"] == tid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    return items


@bp.get("/programs/<programId>/claims/<claimId>")
def get_claim(programId, claimId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    return success_object(domain.serialize(claim))


@bp.get("/programs/<programId>/policyholders/<holderId>/policies/<policyId>/claims")
def list_claims_of_policy(programId, holderId, policyId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    holder = get_holder_in_program(prog, holderId)
    pol = get_policy_of_holder(holder, policyId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        c for c in db.claims.values() if c["policy_id"] == pol["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Adjust
# ---------------------------------------------------------------------------

@bp.post("/programs/<programId>/claims/<claimId>/adjust")
def adjust_claim(programId, claimId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog, claim, pol, idx, holder, ev = _claim_context(programId, claimId)
    data = body()
    require_fields(data, ["new_tier"])
    new_tier = data["new_tier"]
    if not isinstance(new_tier, int):
        raise err(ERR_INVALID_REQUEST, 400, "new_tier must be an integer")

    if claim["status"] not in ("GENERATED", "ADJUSTED"):
        raise err(ERR_CLAIM_NOT_ADJUSTABLE, 409,
                  "Adjust/decline requires claim GENERATED or ADJUSTED")
    if ev["status"] != "VERIFIED":
        raise err(ERR_EVENT_NOT_VERIFIED, 409,
                  "Claim operation requires trigger event VERIFIED")
    if new_tier < 1 or new_tier > int(ev["max_tier_breached"]) or new_tier == int(claim["tier_applied"]):
        raise err(ERR_TIER_EXCEEDS_BREACH, 422,
                  "Claimed tier above event max_tier_breached, below 1, or equal to current tier_applied")

    claim["tier_applied"] = new_tier
    claim["provisional_payout_cents"] = calc.provisional_payout_cents(pol, idx, new_tier)
    claim["status"] = "ADJUSTED"
    domain.touch(claim)
    return success_object(domain.serialize(claim))


# ---------------------------------------------------------------------------
# Approve (with fraud gate)
# ---------------------------------------------------------------------------

@bp.post("/programs/<programId>/claims/<claimId>/approve")
def approve_claim(programId, claimId):
    user_id, _ = require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog, claim, pol, idx, holder, ev = _claim_context(programId, claimId)

    if claim["status"] not in ("GENERATED", "ADJUSTED"):
        raise err(ERR_CLAIM_NOT_ADJUSTABLE, 409,
                  "Adjust/decline requires claim GENERATED or ADJUSTED")
    if ev["status"] != "VERIFIED":
        raise err(ERR_EVENT_NOT_VERIFIED, 409,
                  "Claim operation requires trigger event VERIFIED")
    if pol["lifecycle_status"] != "BOUND":
        raise err(ERR_POLICY_NOT_BOUND, 409, "Operation requires lifecycle_status BOUND")
    # Fraud gate (priority 15): blacklisted holder blocks outright
    if holder["status"] == "BLACKLISTED":
        raise err(ERR_HOLDER_BLACKLISTED, 403,
                  "Claim approval blocked: policyholder is BLACKLISTED")

    claim["approver_user_id"] = user_id

    if int(holder["fraud_score"]) >= FRAUD_SCORE_AUTO_HOLD:
        # Auto-route to FRAUD_HOLD
        claim["status"] = "FRAUD_HOLD"
        domain.touch(claim)
        calc.recompute_fraud_alert_count(prog)
        domain.touch(prog)
        pol["settlement_posture"] = "PAYMENT_PENDING"
        domain.touch(pol)
        return success_object(domain.serialize(claim))

    claim["final_payout_cents"] = calc.final_payout_cents(pol, idx, claim)
    claim["status"] = "APPROVED"
    domain.touch(claim)
    pol["settlement_posture"] = "PAYMENT_PENDING"
    domain.touch(pol)
    return success_object(domain.serialize(claim))


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

@bp.post("/programs/<programId>/claims/<claimId>/decline")
def decline_claim(programId, claimId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog, claim, pol, idx, holder, ev = _claim_context(programId, claimId)
    if claim["status"] not in ("GENERATED", "ADJUSTED"):
        raise err(ERR_CLAIM_NOT_ADJUSTABLE, 409,
                  "Adjust/decline requires claim GENERATED or ADJUSTED")
    claim["status"] = "DECLINED"
    domain.touch(claim)
    domain.reevaluate_policy_posture(pol)
    return success_object(domain.serialize(claim))


# ---------------------------------------------------------------------------
# Clear fraud hold
# ---------------------------------------------------------------------------

@bp.post("/programs/<programId>/claims/<claimId>/clear-fraud-hold")
def clear_fraud_hold(programId, claimId):
    require_roles("FraudAnalyst")
    domain.run_expiry_sweep()
    prog, claim, pol, idx, holder, ev = _claim_context(programId, claimId)
    if claim["status"] != "FRAUD_HOLD":
        raise err(ERR_CLAIM_NOT_IN_FRAUD_HOLD, 409,
                  "Clear-fraud-hold requires claim FRAUD_HOLD")
    claim["final_payout_cents"] = calc.final_payout_cents(pol, idx, claim)
    claim["status"] = "APPROVED"
    domain.touch(claim)
    calc.recompute_fraud_alert_count(prog)
    domain.touch(prog)
    # Posture: still has an APPROVED claim -> PAYMENT_PENDING (re-evaluate keeps it)
    domain.reevaluate_policy_posture(pol)
    return success_object(domain.serialize(claim))


# ---------------------------------------------------------------------------
# Release payment (SoD + cession waterfall)
# ---------------------------------------------------------------------------

@bp.post("/programs/<programId>/claims/<claimId>/release-payment")
def release_payment(programId, claimId):
    user_id, _ = require_roles("TreasuryOfficer")
    domain.run_expiry_sweep()
    prog, claim, pol, idx, holder, ev = _claim_context(programId, claimId)

    if claim["status"] != "APPROVED":
        raise err(ERR_CLAIM_NOT_APPROVED, 409, "Release-payment requires claim APPROVED")
    # SoD (priority 6): releaser must differ from approver
    if claim.get("approver_user_id") is not None and claim["approver_user_id"] == user_id:
        raise err(ERR_SOD_VIOLATION, 403,
                  "Segregation of duties: payment releaser must differ from approving adjuster")

    # Cession waterfall
    total_ceded = calc.cession_waterfall(prog, claim)
    claim["ceded_recovery_cents"] = total_ceded
    claim["net_payment_cents"] = int(claim["final_payout_cents"]) - total_ceded
    claim["status"] = "RECOVERY_CEDED" if total_ceded > 0 else "PAID"
    domain.touch(claim)

    prog["incurred_claims_cents"] = int(prog["incurred_claims_cents"]) + int(claim["final_payout_cents"])
    prog["ceded_recovery_cents"] = int(prog["ceded_recovery_cents"]) + total_ceded
    domain.touch(prog)

    domain.reevaluate_policy_posture(pol)
    return success_object(domain.serialize(claim))


# --- Flat reads ---

@bp.get("/programs/claims")
def list_claims_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = list(db.claims.values())
    items = _apply_claim_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/claims/<claimId>")
def get_claim_flat(claimId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    claim = db.claims.get(claimId)
    if not claim:
        raise err(ERR_CLAIM_NOT_FOUND, 404, "Claim id does not exist")
    return success_object(domain.serialize(claim))
