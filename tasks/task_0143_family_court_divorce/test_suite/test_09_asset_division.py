"""Asset division: community-property vs equitable-distribution.

PRD §3.6 — asset division formulas, pinned multiply-before-divide
order, no-drift invariant.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    api_client,
    assert_asset_division_conserved,
    assert_final_judgment,
    create_final_judgment_no_minors,
    setup_case_in_awaiting_judgment_no_minors,
    validate_success,
)


# ===========================================================================
# COMMUNITY_PROPERTY model — PRD §3.6
# ===========================================================================
class TestCommunityProperty:

    def test_community_property_50_50_split_even_pool(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'When jurisdiction_state is CA, TX, or WA, the
        system uses the community-property model ... The net pool is
        split 50/50: the petitioner gets the integer-division half
        plus any odd-cent residual, and the respondent gets the plain
        integer-division half.'

        Claim: CA, P_assets=1000000, R_assets=2000000, no debts →
        net_pool=3000000 (even) → both shares = 1500000.
        """
        ctx = setup_case_in_awaiting_judgment_no_minors(
            jurisdiction_state="CA",
            p_assets_cents=1_000_000, r_assets_cents=2_000_000,
            p_debts_cents=0, r_debts_cents=0,
        )
        fj = create_final_judgment_no_minors(ctx["case"]["id"])
        assert_final_judgment(fj)
        assert fj["division_model"] == "COMMUNITY_PROPERTY"
        assert fj["petitioner_asset_share_cents"] == 1_500_000
        assert fj["respondent_asset_share_cents"] == 1_500_000
        assert_asset_division_conserved(
            fj,
            p_assets=1_000_000, r_assets=2_000_000,
            p_debts=0, r_debts=0,
        )

    def test_community_property_odd_pool_extra_cent_to_petitioner(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'the petitioner gets the integer-division half
        plus any odd-cent residual'.

        Claim: CA, P_assets=1, R_assets=0 → net_pool=1 (odd) →
        petitioner=1, respondent=0.
        """
        ctx = setup_case_in_awaiting_judgment_no_minors(
            jurisdiction_state="CA",
            p_assets_cents=1, r_assets_cents=0,
            p_debts_cents=0, r_debts_cents=0,
        )
        fj = create_final_judgment_no_minors(ctx["case"]["id"])
        assert fj["division_model"] == "COMMUNITY_PROPERTY"
        assert fj["petitioner_asset_share_cents"] == 1
        assert fj["respondent_asset_share_cents"] == 0


# ===========================================================================
# EQUITABLE_DISTRIBUTION model — PRD §3.6
# ===========================================================================
class TestEquitableDistribution:

    def test_equitable_distribution_lower_earner_larger_share(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'When jurisdiction_state is NY, FL, or IL, the
        system uses the equitable-distribution model and records
        division_model as EQUITABLE_DISTRIBUTION. Shares are weighted
        toward the lower earner: the petitioner's share is computed in
        integer arithmetic by multiplying the net pool by the
        respondent's net_monthly_income_cents first and only then
        integer-dividing by the sum of the two parties'
        net_monthly_income_cents'.

        Claim: NY, net_pool=3000000, P_net=300000, R_net=600000 →
        petitioner_share = (3000000 * 600000) // 900000 = 2000000;
        respondent_share = 3000000 - 2000000 = 1000000.
        """
        ctx = setup_case_in_awaiting_judgment_no_minors(
            jurisdiction_state="NY",
            p_assets_cents=1_000_000, r_assets_cents=2_000_000,
            p_debts_cents=0, r_debts_cents=0,
            p_gross_cents=300_000, r_gross_cents=600_000,
        )
        fj = create_final_judgment_no_minors(ctx["case"]["id"])
        assert fj["division_model"] == "EQUITABLE_DISTRIBUTION"
        assert fj["petitioner_asset_share_cents"] == 2_000_000
        assert fj["respondent_asset_share_cents"] == 1_000_000
        assert_asset_division_conserved(
            fj,
            p_assets=1_000_000, r_assets=2_000_000,
            p_debts=0, r_debts=0,
        )

    def test_equitable_distribution_multiply_before_divide_pinned(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'this multiply-first-then-divide order is pinned
        to prevent float drift'.

        Claim: NY, net_pool=1000003, P_net=500000, R_net=500000 →
        petitioner_share = (1000003 * 500000) // 1000000 = 500001;
        respondent_share = 1000003 - 500001 = 500002. The wrong
        divide-first order ((R_inc / (P_inc+R_inc)) * net_pool) under
        integer math would yield 0 — this test pins the correct order.
        """
        ctx = setup_case_in_awaiting_judgment_no_minors(
            jurisdiction_state="NY",
            p_assets_cents=500_003, r_assets_cents=500_000,
            p_debts_cents=0, r_debts_cents=0,
            p_gross_cents=500_000, r_gross_cents=500_000,
        )
        fj = create_final_judgment_no_minors(ctx["case"]["id"])
        assert fj["petitioner_asset_share_cents"] == 500_001
        assert fj["respondent_asset_share_cents"] == 500_002
        assert (
            fj["petitioner_asset_share_cents"]
            + fj["respondent_asset_share_cents"]
        ) == 1_000_003


# ===========================================================================
# Invariant — PRD §3.6
# ===========================================================================
class TestNoDriftInvariant:

    def test_p_share_plus_r_share_equals_net_pool_invariant(
        self, api, judge_headers,
    ):
        """PRD §3.6: 'In both models, the resulting
        petitioner_asset_share_cents plus respondent_asset_share_cents
        equals the net pool exactly.'

        Claim: the petitioner-share-plus-respondent-share-equals-net-
        pool invariant holds for several otherwise-different
        configurations.
        """
        cases = [
            # (jurisdiction, P_assets, R_assets, P_debts, R_debts,
            #  P_gross, R_gross)
            ("CA", 1_000_000, 2_000_000, 0, 0, 300_000, 600_000),
            ("NY", 1_000_000, 2_000_000, 0, 0, 300_000, 600_000),
            ("TX", 555_555, 444_444, 0, 0, 300_000, 600_000),
            ("FL", 700_000, 700_000, 100_000, 100_000, 200_000, 200_000),
        ]
        for jurisdiction, pa, ra, pd, rd, pg, rg in cases:
            ctx = setup_case_in_awaiting_judgment_no_minors(
                jurisdiction_state=jurisdiction,
                p_assets_cents=pa, r_assets_cents=ra,
                p_debts_cents=pd, r_debts_cents=rd,
                p_gross_cents=pg, r_gross_cents=rg,
            )
            fj = create_final_judgment_no_minors(ctx["case"]["id"])
            assert_asset_division_conserved(
                fj, p_assets=pa, r_assets=ra,
                p_debts=pd, r_debts=rd,
            )
