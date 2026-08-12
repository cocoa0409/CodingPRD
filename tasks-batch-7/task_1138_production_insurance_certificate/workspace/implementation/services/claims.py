"""Claim deductible computation (scaffold claim_deductible_applied)."""

from db import db

AGGREGATE_DEDUCTIBLE_CAP_DIVISOR = 4  # cap = 25% of aggregate_limit_cents


def annual_aggregate_cap(policy):
    return policy["aggregate_limit_cents"] // AGGREGATE_DEDUCTIBLE_CAP_DIVISOR


def cumulative_paid_deductibles(policy):
    """Sum of applied deductibles over the policy's open/resolved claims."""
    total = 0
    for cl in db.claims.values():
        if cl["policy_id"] != policy["id"]:
            continue
        if cl["status"] not in ("UNDER_REVIEW", "ADJUSTED", "SETTLED"):
            continue
        if not (policy["effective_date"] <= cl["occurrence_date"] <= policy["expiry_date"]):
            continue
        total += cl["deductible_applied_cents"]
    return total


def remaining_cap_room(policy):
    return max(0, annual_aggregate_cap(policy) - cumulative_paid_deductibles(policy))


def would_exceed_cap(policy, loss_amount_cents):
    """The proposed claim pushes paid deductibles past the aggregate cap."""
    proposed = min(policy["deductible_cents"], loss_amount_cents)
    return proposed > remaining_cap_room(policy)


def deductible_applied(policy, loss_amount_cents):
    applied = min(
        policy["deductible_cents"],
        loss_amount_cents,
        remaining_cap_room(policy),
    )
    return applied
