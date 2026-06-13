"""Payout disbursement / reversal cascades and the free-look cancellation cascade (§3.5, §3.8).

Covers difficulty rules transitive_cascade (disburse depth-4 chain; free-look depth-2 chain)
and compensating_invariant (payout reverse restores the conserved aggregate).
"""
from test_helpers import (
    validate_success,
    setup_active_policy, setup_approved_cancellation_claim_with_pending_payout,
    setup_claim_under_review, approve_claim, create_payout, disburse_payout,
    file_claim, set_clock, get_policy, get_claim, list_refunds_for_policy,
    TEST_USERS,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ─── transitive_cascade: disburse -> ledger -> EXHAUSTED -> sibling denial ──

def test_disburse_exhausts_aggregate_and_pays_claim(api):
    """PRD §3.8: "On disbursement the payout's `status` becomes `DISBURSED` and a cascade fires:
    the policy's `amount_reimbursed_cents` increases by the payout's `amount_cents` and
    `remaining_aggregate_cents` is recomputed as `aggregate_limit_cents` minus
    `amount_reimbursed_cents`; the linked claim's `status` advances to `PAID`".
    PRD §3.8: "If after this debit the `remaining_aggregate_cents` has reached zero, the policy's
    `coverage_status` transitions to `EXHAUSTED`".

    Aggregate pinned at exactly 300000; disbursing the 300000 payout zeroes remaining and
    exhausts the policy while the claim becomes PAID.

    Design: Difficulty/transitive_cascade/payout_disburse_cascades_ledger_then_exhausted_then_sibling_denial
    """
    bundle = setup_approved_cancellation_claim_with_pending_payout(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "cancellation_limit_pct": 100,
                        "medical_limit_cents": 0, "delay_block_cap_cents": 0,
                        "delay_limit_cents": 0, "baggage_item_sublimit_cents": 0,
                        "baggage_limit_cents": 0},
        trip_cost_cents=300000, prepaid_cents=300000)
    payout = disburse_payout(bundle["payout"]["id"])
    assert payout["status"] == "DISBURSED"
    policy = get_policy(bundle["policy"]["id"])
    assert policy["amount_reimbursed_cents"] == 300000
    assert policy["remaining_aggregate_cents"] == 0
    assert policy["coverage_status"] == "EXHAUSTED"
    claim = get_claim(bundle["claim"]["id"])
    assert claim["status"] == "PAID", f"linked claim must be PAID, got {claim['status']}"


def test_exhaustion_auto_denies_open_sibling_claim(api):
    """PRD §3.8: "that exhaustion in turn auto-denies every sibling claim on the same policy
    still in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`, setting each such claim's
    `denial_reason` to `AGGREGATE_EXHAUSTED`, moving each to `DENIED`".

    A second open CANCELLATION claim (SUBMITTED) on the same policy is auto-denied with
    denial_reason AGGREGATE_EXHAUSTED when the first payout exhausts the aggregate.

    Design: Difficulty/transitive_cascade/payout_disburse_cascades_ledger_then_exhausted_then_sibling_denial
    """
    bundle = setup_approved_cancellation_claim_with_pending_payout(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "cancellation_limit_pct": 100,
                        "medical_limit_cents": 0, "delay_block_cap_cents": 0,
                        "delay_limit_cents": 0, "baggage_item_sublimit_cents": 0,
                        "baggage_limit_cents": 0},
        trip_cost_cents=300000, prepaid_cents=300000)
    sibling = file_claim(bundle["policy"]["id"], bundle["insured"]["id"],
                         bundle["traveler_id"], "CANCELLATION", "2026-06-06T00:00:00Z",
                         cancellation_reason="COVERED_REASON")
    disburse_payout(bundle["payout"]["id"])
    sibling_after = get_claim(sibling["id"])
    assert sibling_after["status"] == "DENIED", \
        f"open sibling claim must be auto-DENIED, got {sibling_after['status']}"
    assert sibling_after["denial_reason"] == "AGGREGATE_EXHAUSTED", \
        f"denial_reason must be AGGREGATE_EXHAUSTED, got {sibling_after['denial_reason']}"


# ─── transitive_cascade: free-look cancel -> refund -> payment REFUNDED ─────

def test_free_look_cancel_cascades_coverage_and_refund(api):
    """PRD §3.5: "When it proceeds, the `coverage_status` becomes `CANCELLED` and three
    cascading effects fire in sequence. First, the system auto-creates a refund of `refund_type`
    `FREE_LOOK` for the full `premium_cents` and immediately sets that refund's `status` to
    `COMPLETED`".

    A BASIC policy premium 20000 free-look-cancelled inside the window -> coverage CANCELLED and
    exactly one FREE_LOOK refund of 20000.

    Design: Difficulty/transitive_cascade/free_look_cancel_cascades_refund_then_payment_refunded
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-05T00:00:00Z")
    policy = active["policy"]
    after = validate_success(
        api.free_look_cancel_policy(policy["id"], active["owner_headers"]), 200)
    assert after["coverage_status"] == "CANCELLED"
    refunds = list_refunds_for_policy(policy["id"])
    assert len(refunds) == 1 and refunds[0]["refund_type"] == "FREE_LOOK"
    assert refunds[0]["amount_cents"] == 20000


def test_free_look_cancel_flips_payment_to_refunded(api):
    """PRD §3.5: "Second, because a completed refund now exists, the policy's `payment_status`
    advances to `REFUNDED` and `net_premium_collected_cents` is recomputed as `premium_cents`
    minus the sum of `amount_cents` across the policy's `COMPLETED` refunds."

    The depth-2 chain: coverage->CANCELLED creates the FREE_LOOK refund, and that refund
    creation itself flips payment_status PAID->REFUNDED.

    Design: Difficulty/transitive_cascade/free_look_cancel_cascades_refund_then_payment_refunded
    """
    active = setup_active_policy(
        plan_overrides={"tier": "BASIC", "base_rate_bps": 400, "free_look_days": 10},
        clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-05T00:00:00Z")
    policy = active["policy"]
    after = validate_success(
        api.free_look_cancel_policy(policy["id"], active["owner_headers"]), 200)
    assert after["payment_status"] == "REFUNDED", \
        f"payment_status must flip to REFUNDED, got {after['payment_status']}"


# ─── compensating_invariant: payout reverse restores aggregate ─────────────

def test_payout_reverse_restores_remaining_aggregate(api):
    """PRD §3.8: "A payout already `DISBURSED` may also be reversed; in that case the cascade is
    undone: the policy's `amount_reimbursed_cents` decreases by the payout's `amount_cents` and
    `remaining_aggregate_cents` is recomputed as `aggregate_limit_cents` minus
    `amount_reimbursed_cents`, restoring the conserved aggregate".

    Aggregate 1200000; disburse 300000 (remaining 900000) then reverse -> amount_reimbursed back
    to 0 and remaining back to 1200000.

    Design: Difficulty/compensating_invariant/payout_reverse_restores_remaining_aggregate
    """
    bundle = setup_approved_cancellation_claim_with_pending_payout(
        plan_overrides={"tier": "STANDARD", "base_rate_bps": 600, "cancellation_limit_pct": 100,
                        "medical_limit_cents": 500000, "delay_limit_cents": 100000,
                        "baggage_limit_cents": 100000},
        trip_cost_cents=500000, prepaid_cents=300000)
    disburse_payout(bundle["payout"]["id"])
    validate_success(api.reverse_payout(bundle["payout"]["id"], ADJUSTER), 200)
    policy = get_policy(bundle["policy"]["id"])
    assert policy["amount_reimbursed_cents"] == 0, \
        f"amount_reimbursed_cents must return to 0 after reverse, got {policy['amount_reimbursed_cents']}"
    assert policy["remaining_aggregate_cents"] == 1200000, \
        f"remaining_aggregate_cents must be restored to 1200000, got {policy['remaining_aggregate_cents']}"


def test_payout_reverse_returns_claim_to_approved(api):
    """PRD §3.8: "the linked claim's `status` returns from `PAID` to `APPROVED`; and the policy's
    `version` increments."

    Reversing a disbursed payout returns the linked claim PAID -> APPROVED, the compensating
    inverse of the disburse cascade.

    Design: Difficulty/compensating_invariant/payout_reverse_restores_remaining_aggregate
    """
    bundle = setup_approved_cancellation_claim_with_pending_payout(
        plan_overrides={"tier": "STANDARD", "base_rate_bps": 600, "cancellation_limit_pct": 100,
                        "medical_limit_cents": 500000, "delay_limit_cents": 100000,
                        "baggage_limit_cents": 100000},
        trip_cost_cents=500000, prepaid_cents=300000)
    disburse_payout(bundle["payout"]["id"])
    paid_claim = get_claim(bundle["claim"]["id"])
    assert paid_claim["status"] == "PAID"
    validate_success(api.reverse_payout(bundle["payout"]["id"], ADJUSTER), 200)
    reverted = get_claim(bundle["claim"]["id"])
    assert reverted["status"] == "APPROVED", \
        f"linked claim must return to APPROVED after reverse, got {reverted['status']}"
