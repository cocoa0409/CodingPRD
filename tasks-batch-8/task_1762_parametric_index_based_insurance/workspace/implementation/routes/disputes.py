"""DisputeCase endpoints (PRD §3.8)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_CLAIM_NOT_SETTLED, ERR_DISPUTE_NOT_OPEN,
    ERR_DISPUTE_NOT_AWAITING, ERR_TIER_EXCEEDS_BREACH, ERR_DISPUTE_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, require_enum, pagination_params, paginate,
    sorted_by_created, get_program, get_claim_in_program, get_dispute_in_claim,
)
from services import domain, calc

bp = Blueprint("disputes", __name__)

DISPUTE_REASONS = {"BASIS_RISK_MISMATCH", "DATA_SOURCE_ERROR", "THRESHOLD_BOUNDARY", "LATE_REVISION"}
RESOLUTIONS = {"UPHELD", "PARTIAL_UPHELD", "DENIED"}
SETTLED_CLAIM_STATES = {"PAID", "RECOVERY_CEDED", "DECLINED"}
DENIED_DATA_SOURCE_PENALTY = 10


@bp.post("/programs/<programId>/claims/<claimId>/disputes")
def open_dispute(programId, claimId):
    user_id, role = require_roles("ServicingAgent")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    data = body()
    require_fields(data, ["dispute_reason", "claimed_tier"])
    require_enum(data, "dispute_reason", DISPUTE_REASONS)
    if not isinstance(data["claimed_tier"], int):
        raise err(ERR_INVALID_REQUEST, 400, "claimed_tier must be an integer")
    if claim["status"] not in SETTLED_CLAIM_STATES:
        raise err(ERR_CLAIM_NOT_SETTLED, 409,
                  "Dispute open requires claim PAID, RECOVERY_CEDED, or DECLINED")
    disp = domain.stamp_new({
        "claim_id": claim["id"],
        "opened_by_role": role,
        "dispute_reason": data["dispute_reason"],
        "claimed_tier": data["claimed_tier"],
        "resolution": "NONE",
        "adjustment_delta_cents": 0,
        "status": "OPEN",
    })
    db.disputes[disp["id"]] = disp
    return success_object(domain.serialize(disp), 201)


@bp.get("/programs/<programId>/claims/<claimId>/disputes")
def list_disputes(programId, claimId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        d for d in db.disputes.values() if d["claim_id"] == claim["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/claims/<claimId>/disputes/<disputeId>")
def get_dispute(programId, claimId, disputeId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    disp = get_dispute_in_claim(claim, disputeId)
    return success_object(domain.serialize(disp))


@bp.post("/programs/<programId>/claims/<claimId>/disputes/<disputeId>/request-info")
def request_info(programId, claimId, disputeId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    disp = get_dispute_in_claim(claim, disputeId)
    if disp["status"] != "OPEN":
        raise err(ERR_DISPUTE_NOT_OPEN, 409, "Operation requires dispute OPEN or AWAITING_CUSTOMER")
    disp["status"] = "AWAITING_CUSTOMER"
    domain.touch(disp)
    return success_object(domain.serialize(disp))


@bp.post("/programs/<programId>/claims/<claimId>/disputes/<disputeId>/submit-info")
def submit_info(programId, claimId, disputeId):
    require_roles("ServicingAgent")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    disp = get_dispute_in_claim(claim, disputeId)
    if disp["status"] != "AWAITING_CUSTOMER":
        raise err(ERR_DISPUTE_NOT_AWAITING, 409, "Submit-info requires dispute AWAITING_CUSTOMER")
    disp["status"] = "OPEN"
    domain.touch(disp)
    return success_object(domain.serialize(disp))


@bp.post("/programs/<programId>/claims/<claimId>/disputes/<disputeId>/resolve")
def resolve_dispute(programId, claimId, disputeId):
    require_roles("ClaimsAdjuster")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    disp = get_dispute_in_claim(claim, disputeId)
    data = body()
    require_fields(data, ["resolution"])
    require_enum(data, "resolution", RESOLUTIONS)

    if disp["status"] not in ("OPEN", "AWAITING_CUSTOMER"):
        raise err(ERR_DISPUTE_NOT_OPEN, 409, "Operation requires dispute OPEN or AWAITING_CUSTOMER")
    if claim["status"] not in SETTLED_CLAIM_STATES:
        raise err(ERR_CLAIM_NOT_SETTLED, 409,
                  "Dispute resolve requires claim PAID, RECOVERY_CEDED, or DECLINED")

    pol = db.policies[claim["policy_id"]]
    idx = db.index_definitions[pol["index_definition_id"]]
    ev = db.trigger_events[claim["trigger_event_id"]]
    holder = db.policyholders[pol["policyholder_id"]]

    # Validate claimed_tier (PRD §3.8): >= 1, <= event max_tier_breached, != tier_applied
    claimed_tier = int(disp["claimed_tier"])
    if claimed_tier < 1 or claimed_tier > int(ev["max_tier_breached"]) or claimed_tier == int(claim["tier_applied"]):
        raise err(ERR_TIER_EXCEEDS_BREACH, 422,
                  "Claimed tier above event max_tier_breached, below 1, or equal to current tier_applied")

    resolution = data["resolution"]
    target = calc.payout_for_tier(pol, idx, claimed_tier)
    if resolution == "UPHELD":
        delta = target - int(claim["final_payout_cents"])
    elif resolution == "PARTIAL_UPHELD":
        from decimal import Decimal
        delta = calc.round_half_up_cents((calc._D(target) - calc._D(int(claim["final_payout_cents"]))) / Decimal("2"))
    else:  # DENIED
        delta = 0

    disp["resolution"] = resolution
    disp["adjustment_delta_cents"] = delta
    disp["status"] = "RESOLVED"
    domain.touch(disp)

    # Signed delta applies to claim and program aggregates; cession not re-run
    claim["final_payout_cents"] = int(claim["final_payout_cents"]) + delta
    claim["net_payment_cents"] = int(claim["final_payout_cents"]) - int(claim["ceded_recovery_cents"])
    domain.touch(claim)
    prog["incurred_claims_cents"] = int(prog["incurred_claims_cents"]) + delta
    domain.touch(prog)

    # Fraud contagion: DENIED + DATA_SOURCE_ERROR -> fraud_score += 10
    if resolution == "DENIED" and disp["dispute_reason"] == "DATA_SOURCE_ERROR":
        holder["fraud_score"] = max(0, min(100, int(holder["fraud_score"]) + DENIED_DATA_SOURCE_PENALTY))
        domain.touch(holder)

    return success_object(domain.serialize(disp))


@bp.post("/programs/<programId>/claims/<claimId>/disputes/<disputeId>/withdraw")
def withdraw_dispute(programId, claimId, disputeId):
    require_roles("ServicingAgent")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    claim = get_claim_in_program(prog, claimId)
    disp = get_dispute_in_claim(claim, disputeId)
    if disp["status"] not in ("OPEN", "AWAITING_CUSTOMER"):
        raise err(ERR_DISPUTE_NOT_OPEN, 409, "Operation requires dispute OPEN or AWAITING_CUSTOMER")
    disp["status"] = "WITHDRAWN"
    domain.touch(disp)
    return success_object(domain.serialize(disp))


# --- Flat reads ---

@bp.get("/programs/disputes")
def list_disputes_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = list(db.disputes.values())
    cid = request.args.get("claim_id")
    st = request.args.get("status")
    if cid is not None:
        items = [d for d in items if d["claim_id"] == cid]
    if st is not None:
        items = [d for d in items if d["status"] == st]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/disputes/<disputeId>")
def get_dispute_flat(disputeId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    disp = db.disputes.get(disputeId)
    if not disp:
        raise err(ERR_DISPUTE_NOT_FOUND, 404, "Dispute id does not exist")
    return success_object(domain.serialize(disp))
