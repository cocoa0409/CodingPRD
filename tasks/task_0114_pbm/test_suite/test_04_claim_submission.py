"""Claim submission: POST /pbm/claims, channel/days-supply bands,
estimated_member_cost_cents computation (PRD §3.4 forward-looking).

PRD §3.4 / §2.8 rung 10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_claim,
    create_claim_payload,
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    setup_paid_claim,
    setup_reference_data,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission shape
# ===========================================================================
class TestClaimSubmissionShape:
    """PRD §3.4 claim submission."""

    def test_claim_starts_submitted_unpaid(self, api, prescriber_headers):
        """PRD §3.4: "The claim is persisted with status SUBMITTED and
        payment_status UNPAID."

        Claim: create claim returns status=SUBMITTED, payment_status=
        UNPAID.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=1,
        )
        claim = validate_success(
            api.create_claim(payload, prescriber_headers), 201,
        )
        assert_claim(claim)
        assert claim["status"] == "SUBMITTED"
        assert claim["payment_status"] == "UNPAID"


# ===========================================================================
# Channel / days-supply band — PRD §2.8 rung 10
# ===========================================================================
class TestChannelDaysSupply:
    """PRD §2.8 rung 10: ERR_CHANNEL_DAYS_SUPPLY_MISMATCH covers both
    create and adjudicate."""

    @pytest.mark.parametrize("channel,bad_days_supply", [
        ("RETAIL_30", 0),       # below RETAIL_30 1..34
        ("RETAIL_30", 35),      # above RETAIL_30 1..34
        ("MAIL_ORDER_90", 59),  # below MAIL_ORDER_90 60..100
        ("MAIL_ORDER_90", 101), # above MAIL_ORDER_90 60..100
        ("SPECIALTY", 0),       # below SPECIALTY 1..30
        ("SPECIALTY", 31),      # above SPECIALTY 1..30
    ])
    def test_invalid_days_supply_rejected_on_submit(
        self, api, prescriber_headers, channel, bad_days_supply,
    ):
        """PRD §3.4: "RETAIL_30 permits a days_supply of 1 through 34
        inclusive, MAIL_ORDER_90 permits 60 through 100 inclusive,
        and SPECIALTY permits 1 through 30 inclusive."
        PRD §2.8 rung 10: "for both claim creation and claim
        adjudicate, the channel and days_supply must satisfy the per-
        channel bands described in §3 and quantity must be at least
        1; otherwise ERR_CHANNEL_DAYS_SUPPLY_MISMATCH (422)."

        Claim: submitting a days_supply outside its channel's band
        returns ERR_CHANNEL_DAYS_SUPPLY_MISMATCH.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel=channel, days_supply=bad_days_supply, quantity=1,
        )
        res = api.create_claim(payload, prescriber_headers)
        validate_error(res, "ERR_CHANNEL_DAYS_SUPPLY_MISMATCH")

    def test_quantity_zero_rejected_on_submit(
        self, api, prescriber_headers,
    ):
        """PRD §3.4: "quantity must be at least 1."
        PRD §2.8 rung 10: "and quantity must be at least 1; otherwise
        ERR_CHANNEL_DAYS_SUPPLY_MISMATCH (422)."

        Claim: quantity=0 returns ERR_CHANNEL_DAYS_SUPPLY_MISMATCH.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=0,
        )
        res = api.create_claim(payload, prescriber_headers)
        validate_error(res, "ERR_CHANNEL_DAYS_SUPPLY_MISMATCH")

    @pytest.mark.parametrize("channel,days_supply", [
        ("RETAIL_30", 1),
        ("RETAIL_30", 34),
        ("MAIL_ORDER_90", 60),
        ("MAIL_ORDER_90", 100),
        ("SPECIALTY", 1),
        ("SPECIALTY", 30),
    ])
    def test_boundary_days_supply_accepted(
        self, api, prescriber_headers, channel, days_supply,
    ):
        """PRD §3.4: per-channel bands are stated inclusive on both
        ends — 1..34, 60..100, 1..30.

        Claim: the inclusive endpoint values are accepted at submit.
        """
        _, drug, _, member = setup_reference_data()
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel=channel, days_supply=days_supply, quantity=1,
        )
        validate_success(
            api.create_claim(payload, prescriber_headers), 201,
        )


# ===========================================================================
# estimated_member_cost calculation — PRD §3.4 forward-looking
# ===========================================================================
class TestEstimatedMemberCost:
    """PRD §3.4 forward-looking estimate formula."""

    def test_estimate_simple_retail_under_deductible(
        self, api, prescriber_headers,
    ):
        """PRD §3.4: "first multiplies unit_allowed_cents by quantity
        to obtain the raw allowed amount. When the channel is
        MAIL_ORDER_90, the raw allowed amount is multiplied by the
        plan's mail_order_discount_rate … for RETAIL_30 and SPECIALTY
        no channel multiplier is applied."
        PRD §3.4: "The submission-time deductible-remaining is the
        plan's deductible_cents minus the member's current
        ytd_deductible_paid_cents, clamped at zero so it never goes
        negative. The portion of the allowed charge that falls under
        the deductible is the smaller of the allowed charge and that
        remaining deductible."

        Setup: plan(ded=50000, oop_max=200000, coins=0.20, tier 3).
        Drug unit=10000, quantity=10, RETAIL_30 -> allowed=100000.
        Member YTD=0 -> ded_portion=min(100000,50000)=50000,
        post_ded=50000, member_share=50000*0.20=10000,
        member_pre_card=60000, oop_remaining=200000 (cap not hit).
        Expected estimate = 60000.
        """
        plan = create_plan(deductible_cents=50_000,
                           oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=10_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=10,
        )
        claim = validate_success(
            api.create_claim(payload, prescriber_headers), 201,
        )
        assert claim["estimated_member_cost_cents"] == 60_000

    def test_estimate_mail_order_applies_discount(
        self, api, prescriber_headers,
    ):
        """PRD §3.4: "When the channel is MAIL_ORDER_90, the raw
        allowed amount is multiplied by the plan's
        mail_order_discount_rate and the product is rounded half-up
        to the nearest whole cent".

        Setup: plan(ded=0, oop_max=200000, coins=0.20, mor=0.90,
        tier 3). Drug unit=5000, q=10 -> raw=50000, allowed=
        round_half_up(50000*0.90)=45000. ded_portion=0, post_ded=
        45000, member_share=45000*0.20=9000, member_pre_card=9000.
        Expected estimate = 9000.
        """
        plan = create_plan(deductible_cents=0,
                           oop_max_cents=200_000,
                           coinsurance_rate=0.20,
                           mail_order_discount_rate=0.90)
        drug = create_drug(unit_allowed_cents=5_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel="MAIL_ORDER_90", days_supply=90, quantity=10,
        )
        claim = validate_success(
            api.create_claim(payload, prescriber_headers), 201,
        )
        assert claim["estimated_member_cost_cents"] == 9_000

    def test_estimate_tier_one_uses_flat_copay(
        self, api, prescriber_headers,
    ):
        """PRD §3.4: "If the formulary entry's tier is 1 or 2, the
        member's share of the post-deductible balance is the smaller
        of copay_cents and that post-deductible balance — a flat
        formulary copay capped at whatever post-deductible spend
        actually exists."

        Setup: plan(ded=0, oop_max=200000, coins=0.20, tier 1
        copay=1500). Drug unit=5000, q=10 -> allowed=50000, ded=0,
        post_ded=50000, member_share=min(1500,50000)=1500,
        member_pre_card=1500.
        """
        plan = create_plan(deductible_cents=0,
                           oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=5_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=1, copay_cents=1500)
        member = create_member(plan_id=plan["id"])
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=10,
        )
        claim = validate_success(
            api.create_claim(payload, prescriber_headers), 201,
        )
        assert claim["estimated_member_cost_cents"] == 1500

    def test_estimate_oop_cap_clamps_member_pre_card(
        self, api, prescriber_headers,
    ):
        """PRD §3.4: "the member's pre-card cost is then capped to be
        no greater than this remaining out-of-pocket headroom."

        Setup: plan(ded=0, oop_max=1000, coins=0.20, tier 3). Drug
        unit=5000, q=10 -> allowed=50000, ded=0, post_ded=50000,
        member_share=10000, member_pre_card=10000. But
        oop_remaining=1000, so member_pre_card clamps to 1000.
        Expected estimate = 1000.
        """
        plan = create_plan(deductible_cents=0,
                           oop_max_cents=1_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=5_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        payload = create_claim_payload(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=10,
        )
        claim = validate_success(
            api.create_claim(payload, prescriber_headers), 201,
        )
        assert claim["estimated_member_cost_cents"] == 1_000
