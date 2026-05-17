"""Claim adjudication: chronological calculation + side-effect order.

PRD §3.5 adjudicated_member_cost.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    adjudicate_claim,
    advance_clock,
    create_copay_card,
    create_drug,
    create_formulary_entry,
    create_member,
    create_plan,
    re_get_claim,
    re_get_copay_card,
    re_get_member,
    setup_adjudicated_claim,
    setup_paid_claim,
    setup_reference_data,
    submit_claim,
    validate_error,
    validate_success,
)


# ===========================================================================
# Computed fields written by ADJUDICATE.
# ===========================================================================
class TestAdjudicateComputesFields:

    def test_adjudicate_writes_four_computed_fields(self, api):
        """PRD §3.5: "The adjudicate transition writes four computed
        fields. adjudicated_allowed_cents records the channel-
        adjusted allowed charge. copay_card_paid_cents records the
        dollars the card actually contributed to the claim.
        adjudicated_member_cost_cents records the member's pre-card
        cost minus the card's contribution — that is, what the member
        ultimately owes. adjudicated_plan_paid_cents records the
        plan's share, computed as the allowed charge minus the
        member's pre-card cost".

        Setup: plan(ded=0, oop_max=200000, coins=0.20, tier 3 copay=0).
        Drug unit=10000, q=10, RETAIL_30 -> allowed=100000.
        ded=0, post_ded=100000, member_share=100000*0.20=20000,
        member_pre_card=20000. No card. Expected:
          adjudicated_allowed_cents == 100000
          adjudicated_member_cost_cents == 20000
          adjudicated_plan_paid_cents == 100000 - 20000 == 80000
          copay_card_paid_cents == 0
        """
        plan = create_plan(deductible_cents=0,
                           oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=10_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        claim_adj = setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=10,
        )
        assert claim_adj["adjudicated_allowed_cents"] == 100_000
        assert claim_adj["adjudicated_member_cost_cents"] == 20_000
        assert claim_adj["adjudicated_plan_paid_cents"] == 80_000
        assert claim_adj["copay_card_paid_cents"] == 0

    def test_adjudicate_applies_mail_order_discount(self, api):
        """PRD §3.5: "compute the allowed charge with the MAIL_ORDER_90
        discount applied (and rounded half-up) where applicable".

        Setup: plan(ded=0, oop_max=200000, coins=0.20, mor=0.90, tier 3).
        Drug unit=5000, q=10 -> raw=50000, allowed=round_half_up(50000*
        0.90)=45000. Expected adjudicated_allowed_cents == 45000.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=200_000,
                           coinsurance_rate=0.20,
                           mail_order_discount_rate=0.90)
        drug = create_drug(unit_allowed_cents=5_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        claim_adj = setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="MAIL_ORDER_90", days_supply=90, quantity=10,
        )
        assert claim_adj["adjudicated_allowed_cents"] == 45_000


# ===========================================================================
# Side-effect order: deductible -> oop -> card.
# ===========================================================================
class TestSideEffectOrder:
    """PRD §3.5 pinned ORDER: deductible -> oop -> card."""

    def test_oop_increments_by_member_pre_card_not_post_card(self, api):
        """PRD §3.5: "first, the member's ytd_deductible_paid_cents
        is incremented by the deductible portion of this claim;
        second, the member's ytd_oop_paid_cents is incremented by the
        member's pre-card cost (the out-of-pocket counter therefore
        tracks the pre-card member share, not the post-card residual);
        third, if a copay card was used, the card's used_cents is
        incremented by copay_card_paid_cents."

        Setup: plan(ded=0, oop_max=100000, coins=0.20, tier 3 copay=0).
        Drug unit=1000, q=30 -> allowed=30000. ded=0, post_ded=30000,
        member_share=30000*0.20=6000, member_pre_card=6000. Card
        (max=1000, pcc=1000): card_payable=min(1000, 1000-0, 6000)=1000.
        adjudicated_member_cost=6000-1000=5000. Member.ytd_oop must
        increment by member_pre_card=6000 (NOT 5000).
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=100_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=1_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=1_000, per_claim_cap_cents=1_000,
        )
        claim_adj = setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=30,
            copay_card_id=card["id"],
        )
        # adjudicated values
        assert claim_adj["adjudicated_member_cost_cents"] == 5_000
        assert claim_adj["copay_card_paid_cents"] == 1_000
        # Member side effects
        m = re_get_member(member["id"])
        assert m["ytd_oop_paid_cents"] == 6_000
        # Card side effect
        c = re_get_copay_card(card["id"])
        assert c["used_cents"] == 1_000

    def test_deductible_portion_increments_member_ytd_deductible(self, api):
        """PRD §3.5: "first, the member's ytd_deductible_paid_cents is
        incremented by the deductible portion of this claim".

        Setup: plan(ded=50000, oop_max=200000, coins=0.20, tier 3
        copay=0). Drug unit=10000, q=3 -> allowed=30000. ded_portion=
        min(30000,50000)=30000. Member.ytd_ded must become 30000.
        """
        plan = create_plan(deductible_cents=50_000,
                           oop_max_cents=200_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=10_000)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=3,
        )
        m = re_get_member(member["id"])
        assert m["ytd_deductible_paid_cents"] == 30_000


# ===========================================================================
# Hard cap on copay card (overflow not funded).
# ===========================================================================
class TestCopayCardHardCap:
    """PRD §3.5: "the cap is a hard cap, so any portion of a claim's
    card-payable amount that would push used_cents above
    max_benefit_cents is simply not funded — the member pays that
    residual." PRD §3.5: "When the card's used_cents reaches
    max_benefit_cents exactly, the card's status flips from ACTIVE to
    EXHAUSTED.\""""

    def test_card_exhausts_when_used_reaches_max(self, api):
        """PRD §3.5: "When the card's used_cents reaches
        max_benefit_cents exactly, the card's status flips from
        ACTIVE to EXHAUSTED".

        Setup: card max=500, per_claim_cap=500. Claim's pre-card
        share = 600 (>500). card_payable=min(500,500,600)=500.
        used=500=max -> card -> EXHAUSTED. Member pays residual.
        """
        plan = create_plan(deductible_cents=0, oop_max_cents=100_000,
                           coinsurance_rate=0.20)
        drug = create_drug(unit_allowed_cents=300)
        create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                               tier=3, copay_cents=0)
        member = create_member(plan_id=plan["id"])
        # allowed = 300 * 10 = 3000; member_share=3000*0.20=600 (>500).
        card = create_copay_card(
            member_id=member["id"], drug_id=drug["id"],
            max_benefit_cents=500, per_claim_cap_cents=500,
        )
        claim_adj = setup_adjudicated_claim(
            member_id=member["id"], drug_id=drug["id"],
            channel="RETAIL_30", days_supply=30, quantity=10,
            copay_card_id=card["id"],
        )
        assert claim_adj["copay_card_paid_cents"] == 500
        assert claim_adj["adjudicated_member_cost_cents"] == 100  # 600-500
        c = re_get_copay_card(card["id"])
        assert c["used_cents"] == 500
        assert c["status"] == "EXHAUSTED"
