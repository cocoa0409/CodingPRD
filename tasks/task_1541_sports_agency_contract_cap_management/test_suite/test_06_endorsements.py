"""Endorsement deals: tiered marketing fee vs agency cap, listing filters."""
from test_helpers import (
    TEST_USERS,
    approve_endorsement,
    create_endorsement,
    setup_negotiation_env,
    validate_paginated,
    validate_success,
)

LEAGUE = TEST_USERS["league_officer_headers"]


class TestEndorsementFeeTiers:
    def test_fee_cap_binds_on_mid_tier_deal(self, api):
        """PRD §3.8: "The base rate tiers on deal size: ten percent when the
        deal value is below 100,000,000 cents — the one-million-dollar line;
        fifteen percent when the value is at least that figure but below
        500,000,000 cents — the five-million-dollar line; and twenty percent
        once the value reaches five million dollars or more. The payable fee is
        the smaller of that tiered amount and the agency's marketing ceiling,
        `deal_value_cents` multiplied by the agency's `fee_cap_pct`, with the
        result rounded half up to a whole cent and recorded as
        `agent_fee_cents`."

        A 200,000,000-cent deal sits in the fifteen-percent tier (raw fee
        30,000,000) under an agency capped at 0.03 (ceiling 6,000,000): the cap
        branch wins, agent_fee_cents == 6,000,000.

        Design: Difficulty/dual_variant_calc/endorsement_agent_fee_tiered_vs_flat_variant
        """
        env = setup_negotiation_env(fee_cap_pct=0.03, agency_name="CapBound Agency")
        deal = create_endorsement(env, brand_name="ShoeBrand",
                                  deal_value_cents=200_000_000)
        approved = approve_endorsement(env, deal["id"])
        assert approved["status"] == "ACTIVE"
        assert approved["agent_fee_cents"] == 6_000_000, \
            "min(tiered 30,000,000, cap 6,000,000) — the agency ceiling binds"

    def test_tier_binds_under_generous_cap(self, api):
        """PRD §3.8: "The base rate tiers on deal size: ten percent when the
        deal value is below 100,000,000 cents — the one-million-dollar line;
        fifteen percent when the value is at least that figure but below
        500,000,000 cents — the five-million-dollar line; and twenty percent
        once the value reaches five million dollars or more. The payable fee is
        the smaller of that tiered amount and the agency's marketing ceiling,
        `deal_value_cents` multiplied by the agency's `fee_cap_pct`, with the
        result rounded half up to a whole cent and recorded as
        `agent_fee_cents`."

        A 50,000,000-cent deal sits in the ten-percent tier (raw fee 5,000,000)
        under an agency capped at 0.20 (ceiling 10,000,000): the tier branch
        wins, agent_fee_cents == 5,000,000 — a different binding behavior from
        the same rule.

        Design: Difficulty/dual_variant_calc/endorsement_agent_fee_tiered_vs_flat_variant
        """
        env = setup_negotiation_env(fee_cap_pct=0.20, agency_name="TierBound Agency")
        deal = create_endorsement(env, brand_name="DrinkCo",
                                  deal_value_cents=50_000_000)
        approved = approve_endorsement(env, deal["id"])
        assert approved["status"] == "ACTIVE"
        assert approved["agent_fee_cents"] == 5_000_000, \
            "min(tiered 5,000,000, cap 10,000,000) — the tier binds"


class TestEndorsementListing:
    def test_list_endorsements_filter_by_status(self, api):
        """PRD §3.8: "A new deal waits in `PENDING_APPROVAL`, and deals can be
        listed and filtered by `status`."

        Design: Corner/endpoints/list_endorsements_filter_by_status
        """
        env = setup_negotiation_env(fee_cap_pct=0.05, agency_name="EndA")
        deal = create_endorsement(env, brand_name="Acme", deal_value_cents=1_000_000)
        assert deal["status"] == "PENDING_APPROVAL"
        data, meta = validate_paginated(api.list_endorsements(
            env["agency"]["id"], env["client"]["id"], LEAGUE,
            params={"status": "ACTIVE"}))
        assert meta["total_count"] == 0, "only a PENDING_APPROVAL deal exists"
        assert data == []
