"""Compensation calculation: delay duration, tier selection, FIXED vs
ACTUAL_LOSS, and multi-segment combined payout (PRD §3.6).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    SegmentEligibility,
    TierSelected,
    setup_claim_under_review,
    setup_basic_claim_in_matched,
    submit_review,
    approve_claim,
    setup_three_segment_actual_loss_claim,
    get_claim,
    fresh_operator_id,
    make_claims_reviewer_headers,
    make_claims_approver_headers,
    submit_review_payload,
    approve_claim_payload,
    api_client,
    INFINITY_DELAY_SENTINEL,
    TIER_A_AMOUNT_CENTS,
    TIER_B_AMOUNT_CENTS,
    TIER_C_AMOUNT_CENTS,
)


# ---------------------------------------------------------------------------
# Tier-table boundaries (PRD §3.6)
# ---------------------------------------------------------------------------

class TestTierBoundaries:
    def test_below_60_minutes_is_below_threshold(self, api):
        """PRD §3.6: "When delay_minutes_used is below 60, tier_selected is
        NONE, the tier amount is 0, and the segment's eligibility is set to
        DELAY_BELOW_THRESHOLD."

        Claim: 59-min delay → tier_selected=NONE,
        eligibility=DELAY_BELOW_THRESHOLD, gross=0.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            departure_delay_minutes=59,
            deductible_cents=0,
        )
        full = get_claim(insurer["id"], claim_uw["id"])
        seg = full["segments"][0]
        assert seg["delay_minutes_used"] == 59
        assert seg["tier_selected"] == TierSelected.NONE.value
        assert seg["eligibility"] == SegmentEligibility.DELAY_BELOW_THRESHOLD.value
        assert seg["gross_segment_payout_cents"] == 0

    def test_60_minutes_inclusive_lands_in_tier_a(self, api):
        """PRD §3.6: "When delay_minutes_used is at least 60 but less than
        180, tier_selected is TIER_A and the tier amount is 10,000 cents
        (one hundred euros)."

        Claim: exactly 60 min delay → TIER_A with gross=10000.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            departure_delay_minutes=60,
            deductible_cents=0,
        )
        full = get_claim(insurer["id"], claim_uw["id"])
        seg = full["segments"][0]
        assert seg["delay_minutes_used"] == 60
        assert seg["tier_selected"] == TierSelected.TIER_A.value
        assert seg["eligibility"] == SegmentEligibility.ELIGIBLE.value
        assert seg["gross_segment_payout_cents"] == TIER_A_AMOUNT_CENTS

    def test_180_minutes_lands_in_tier_b(self, api):
        """PRD §3.6: "When delay_minutes_used is at least 180 but less than
        360, tier_selected is TIER_B and the tier amount is 25,000 cents
        (two hundred fifty euros)."

        Claim: exactly 180 min delay → TIER_B with gross=25000.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            departure_delay_minutes=180,
            deductible_cents=0,
        )
        full = get_claim(insurer["id"], claim_uw["id"])
        seg = full["segments"][0]
        assert seg["delay_minutes_used"] == 180
        assert seg["tier_selected"] == TierSelected.TIER_B.value
        assert seg["gross_segment_payout_cents"] == TIER_B_AMOUNT_CENTS

    def test_360_minutes_lands_in_tier_c(self, api):
        """PRD §3.6: "When delay_minutes_used is at least 360 minutes (or
        equals the infinity sentinel), tier_selected is TIER_C and the tier
        amount is 60,000 cents (six hundred euros)."

        Claim: exactly 360 min delay → TIER_C with gross=60000.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            departure_delay_minutes=360,
            deductible_cents=0,
        )
        full = get_claim(insurer["id"], claim_uw["id"])
        seg = full["segments"][0]
        assert seg["delay_minutes_used"] == 360
        assert seg["tier_selected"] == TierSelected.TIER_C.value
        assert seg["gross_segment_payout_cents"] == TIER_C_AMOUNT_CENTS


# ---------------------------------------------------------------------------
# CANCELLED → infinity sentinel (PRD §3.6)
# ---------------------------------------------------------------------------

class TestInfinityDelay:
    def test_cancelled_flight_uses_infinity_sentinel(self, api):
        """PRD §3.6: "if the flight's status is CANCELLED, the
        delay_minutes_used takes the infinity sentinel value of 99,999,999".
        PRD §3.6: "When delay_minutes_used is at least 360 minutes (or
        equals the infinity sentinel), tier_selected is TIER_C ...".

        Claim: a CANCELLED flight produces delay_minutes_used=99_999_999 and
        tier_selected=TIER_C with gross=60000 under FIXED.
        """
        from test_helpers import (
            setup_basic_insurer_with_policy, create_flight, create_ticket,
            create_claim, finalize_flight_cancelled,
        )
        insurer, policy = setup_basic_insurer_with_policy(
            delay_basis="DEPARTURE", payout_mode="FIXED",
            deductible_cents=0,
        )
        flight = create_flight(
            insurer["id"],
            scheduled_departure_epoch_ms=10_000_000,
            scheduled_arrival_epoch_ms=15_000_000,
        )
        finalize_flight_cancelled(insurer["id"], flight["id"], cause="AIRLINE")
        ticket = create_ticket(
            insurer["id"], flight_id=flight["id"],
            passenger_doc_id=policy["policy_holder_doc_id"],
        )
        claim = create_claim(insurer["id"], policy["id"], ticket_ids=[ticket["id"]])
        rid = fresh_operator_id("rev")
        api_client.submit_review(
            insurer["id"], claim["id"],
            submit_review_payload(assigned_reviewer_id=rid),
            make_claims_reviewer_headers(rid),
        )
        full = get_claim(insurer["id"], claim["id"])
        seg = full["segments"][0]
        assert seg["delay_minutes_used"] == INFINITY_DELAY_SENTINEL
        assert seg["tier_selected"] == TierSelected.TIER_C.value
        assert seg["gross_segment_payout_cents"] == TIER_C_AMOUNT_CENTS


# ---------------------------------------------------------------------------
# ACTUAL_LOSS mode (PRD §3.6)
# ---------------------------------------------------------------------------

class TestActualLossMode:
    def test_actual_loss_uses_floor_of_loss_times_rate(self, api):
        """PRD §3.6: "Under ACTUAL_LOSS, the gross segment payout is the
        integer floor of claimed_actual_loss_cents * reimbursement_rate_bps
        / 10000, and that result is then capped above by the tier amount —
        i.e., the smaller of the floored expense-times-rate and the tier-
        amount in cents."

        Claim: ACTUAL_LOSS @ 50% rate, claimed_loss=4501 → floor(4501*5000/10000)
        = 2250, well below TIER_B 25000 cap.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            payout_mode="ACTUAL_LOSS",
            reimbursement_rate_bps=5000,
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
            claimed_actual_loss_cents=4501,
        )
        full = get_claim(insurer["id"], claim_uw["id"])
        seg = full["segments"][0]
        assert seg["delay_minutes_used"] == 200
        assert seg["tier_selected"] == TierSelected.TIER_B.value
        assert seg["gross_segment_payout_cents"] == 2250

    def test_actual_loss_capped_at_tier_amount(self, api):
        """PRD §3.6: "and that result is then capped above by the tier
        amount — i.e., the smaller of the floored expense-times-rate and
        the tier-amount in cents."

        Claim: ACTUAL_LOSS @ 50% rate with huge claimed_loss → capped at
        TIER_B 25000.
        """
        insurer, policy, flight, ticket, claim_uw, rid = setup_claim_under_review(
            payout_mode="ACTUAL_LOSS",
            reimbursement_rate_bps=5000,
            departure_delay_minutes=200,  # TIER_B → cap 25000
            deductible_cents=0,
            policy_limit_cents=1_000_000_000,
            claimed_actual_loss_cents=1_000_000,  # 1_000_000 * 0.5 = 500_000 — capped
        )
        full = get_claim(insurer["id"], claim_uw["id"])
        seg = full["segments"][0]
        assert seg["gross_segment_payout_cents"] == TIER_B_AMOUNT_CENTS, \
            f"Expected cap at TIER_B 25000; got {seg['gross_segment_payout_cents']}"


# ---------------------------------------------------------------------------
# Per-segment-then-sum rounding order (PRD §3.6)
# ---------------------------------------------------------------------------

class TestMultiSegmentRoundingOrder:
    def test_per_segment_then_sum_then_deductible(self, api):
        """PRD §3.6: "Per-segment gross amounts are floor-rounded once, at
        the segment level, before they are summed; do not recompute by
        summing raw expenses and then multiplying by the rate, as that path
        can produce a different cents result under ACTUAL_LOSS."
        PRD §3.6: "sum gross_segment_payout_cents over only those segments
        whose eligibility is ELIGIBLE; subtract policy.deductible_cents,
        clamping at zero; then take the smaller of that result and
        policy.policy_limit_cents."

        Claim: three ACTUAL_LOSS segments at 50% with losses 4501, 4502,
        4503 and deductible 2500 → per-segment grosses 2250+2251+2251=6752,
        estimated_payout = 6752 - 2500 = 4252. Sum-then-round (floor(13506
        * 0.5) = 6753) is the WRONG order; assert PRD's pinned 4252.
        """
        ctx = setup_three_segment_actual_loss_claim(
            losses=[4501, 4502, 4503],
            rate_bps=5000,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        insurer, claim = ctx["insurer"], ctx["claim"]
        # submit_review computes per-segment grosses.
        reviewed, rid = submit_review(insurer["id"], claim["id"])
        full = get_claim(insurer["id"], claim["id"])
        grosses = [s["gross_segment_payout_cents"] for s in full["segments"]]
        assert grosses == [2250, 2251, 2251], \
            f"per-segment floor must yield [2250,2251,2251]; got {grosses}"
        # Approve so estimated_payout is pinned.
        approved, aid = approve_claim(insurer["id"], claim["id"])
        assert approved["estimated_payout_cents"] == 4252, (
            f"estimated_payout_cents must be 4252 (= 6752 - 2500 deductible); "
            f"got {approved['estimated_payout_cents']}"
        )

    def test_estimated_payout_capped_at_policy_limit(self, api):
        """PRD §3.6: "subtract policy.deductible_cents, clamping at zero;
        then take the smaller of that result and policy.policy_limit_cents."

        Claim: three TIER_C segments (60000 each = 180000 sum), deductible
        2500 → 177500 net, capped at policy_limit_cents=150000 →
        estimated_payout = 150000.
        """
        from test_helpers import setup_capped_three_segment_paid_claim
        ctx = setup_capped_three_segment_paid_claim(departure_delay_minutes=360)
        claim = ctx["claim"]
        assert claim["final_payout_cents"] == 150000, \
            f"final_payout_cents must be capped at policy_limit 150000; got {claim['final_payout_cents']}"
