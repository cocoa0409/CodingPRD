"""Reserve accounting: ledger writes and policy balance updates."""

from __future__ import annotations

from db import db, gen_id, now_iso_z


def append_reserve_adjustment(policy: dict, claim_id: str, delta_cents: int, reason: str) -> dict:
    """Apply delta_cents to policy.reserve_balance_cents and journal a ReserveAdjustment."""
    policy["reserve_balance_cents"] = policy.get("reserve_balance_cents", 0) + delta_cents
    adj = {
        "id": gen_id(),
        "policy_id": policy["id"],
        "insurer_id": policy["insurer_id"],
        "claim_id": claim_id,
        "delta_cents": delta_cents,
        "reason": reason,
        "balance_after_cents": policy["reserve_balance_cents"],
        "created_at": now_iso_z(),
    }
    db.reserve_adjustments[adj["id"]] = adj
    return adj


def recompute_reserve_balance(policy: dict) -> int:
    """Sum of estimated_payout_cents over (PAYABLE | EXECUTING) AND review APPROVED claims."""
    total = 0
    for claim in db.claims.values():
        if claim.get("policy_id") != policy["id"]:
            continue
        if claim.get("review_status") != "APPROVED":
            continue
        if claim.get("payout_status") not in ("PAYABLE", "EXECUTING"):
            continue
        total += claim.get("estimated_payout_cents", 0) or 0
    return total


def recompute_quota_used(policy: dict) -> int:
    """Sum of final_payout_cents over claims in PAID payout_status."""
    total = 0
    for claim in db.claims.values():
        if claim.get("policy_id") != policy["id"]:
            continue
        if claim.get("payout_status") != "PAID":
            continue
        total += claim.get("final_payout_cents", 0) or 0
    return total


def recompute_pessimistic_reserve(policy: dict) -> int:
    """Pessimistic exposure (PRD §2.8): includes UNDER_REVIEW claims (whose
    payout_status is not PAID) in addition to the optimistic set
    (APPROVED + PAYABLE/EXECUTING). For UNDER_REVIEW claims, estimated_payout
    has not yet been pinned, so we compute the same algorithm (PRD §3.6):
    sum gross_segment_payout_cents over ELIGIBLE segments, subtract
    deductible (clamp at 0), cap at policy_limit.
    """
    total = 0
    deductible = policy.get("deductible_cents", 0) or 0
    policy_limit = policy.get("policy_limit_cents", 0) or 0
    for claim in db.claims.values():
        if claim.get("policy_id") != policy["id"]:
            continue
        review = claim.get("review_status")
        payout = claim.get("payout_status")
        if payout == "PAID":
            continue
        if review == "APPROVED":
            if payout in ("PAYABLE", "EXECUTING"):
                total += claim.get("estimated_payout_cents", 0) or 0
            continue
        if review == "UNDER_REVIEW":
            # Compute gross-payout view for this claim from its segments.
            sum_gross = 0
            for sid in claim.get("segment_ids", []) or []:
                seg = db.claim_segments.get(sid)
                if not seg:
                    continue
                if seg.get("eligibility") != "ELIGIBLE":
                    continue
                sum_gross += seg.get("gross_segment_payout_cents", 0) or 0
            net = max(0, sum_gross - deductible)
            capped = min(net, policy_limit) if policy_limit > 0 else net
            total += capped
    return total


def total_outstanding_reserve(insurer_id: str) -> int:
    """Sum of reserve_balance_cents across all ACTIVE policies of the insurer."""
    total = 0
    for pol in db.policies.values():
        if pol.get("insurer_id") != insurer_id:
            continue
        if pol.get("status") != "ACTIVE":
            continue
        total += pol.get("reserve_balance_cents", 0) or 0
    return total
