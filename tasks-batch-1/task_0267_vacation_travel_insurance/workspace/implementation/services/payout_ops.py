"""Payout domain operations: disbursement cascade, aggregate exhaustion
auto-deny, compensating reversal."""
import errors
from db import db
from services import policy_ops
from services.store_helpers import touch, claims_for_policy


_OPEN_SIBLING_STATES = {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"}


def disburse(payout):
    claim = db.claims[payout["claim_id"]]
    policy = db.policies[payout["policy_id"]]

    if payout["status"] != "PENDING":
        raise errors.invalid_state("Payout is not PENDING.")
    if claim["status"] != "APPROVED":
        raise errors.conflict(errors.ERR_CLAIM_NOT_APPROVED, "Linked claim is not APPROVED.")
    if payout["amount_cents"] > policy["remaining_aggregate_cents"]:
        raise errors.conflict(errors.ERR_AGGREGATE_LIMIT_EXCEEDED, "Payout exceeds remaining aggregate.")

    payout["status"] = "DISBURSED"
    touch(payout)

    # CASCADE L1->L2: debit policy aggregate.
    policy["amount_reimbursed_cents"] += payout["amount_cents"]
    policy_ops.recompute_remaining(policy)

    # Linked claim -> PAID (its own version bump).
    claim["status"] = "PAID"
    touch(claim)

    # CASCADE L2->L3: exhaustion when remaining hits 0.
    if policy["remaining_aggregate_cents"] == 0:
        policy["coverage_status"] = "EXHAUSTED"
        # CASCADE L3->L4: auto-deny sibling open claims.
        for c in claims_for_policy(policy["id"]):
            if c["id"] == claim["id"]:
                continue
            if c["status"] in _OPEN_SIBLING_STATES:
                c["denial_reason"] = "AGGREGATE_EXHAUSTED"
                c["status"] = "DENIED"
                touch(c)

    touch(policy)


def reverse(payout):
    if payout["status"] == "PENDING":
        payout["status"] = "REVERSED"
        touch(payout)
        return
    if payout["status"] != "DISBURSED":
        raise errors.invalid_state("Payout is not in a reversible state.")

    # DISBURSED -> REVERSED with compensation.
    policy = db.policies[payout["policy_id"]]
    claim = db.claims[payout["claim_id"]]

    payout["status"] = "REVERSED"
    touch(payout)

    policy["amount_reimbursed_cents"] -= payout["amount_cents"]
    policy_ops.recompute_remaining(policy)

    if policy["coverage_status"] == "EXHAUSTED" and policy["remaining_aggregate_cents"] > 0:
        policy["coverage_status"] = "ACTIVE"

    # Linked claim PAID -> APPROVED.
    if claim["status"] == "PAID":
        claim["status"] = "APPROVED"
        touch(claim)

    touch(policy)
