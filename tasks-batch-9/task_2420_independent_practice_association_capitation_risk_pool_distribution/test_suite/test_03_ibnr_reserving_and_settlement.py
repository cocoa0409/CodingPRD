"""IBNR reserving conventions and the pinned settlement waterfall."""

from test_helpers import (
    assert_fields,
    build_final_scorecard,
    build_reserving_scenario,
    list_pool_distributions,
    propose_settlement,
    read_pool,
    reserve_pool,
)


class TestIbnrReserveVariantDivergence:
    def test_pool_ledger_position_before_reserving(self, api):
        """PRD §3.7: "Only claims whose `status` is `PAID` count as reported for
        reserving purposes."

        Design: Difficulty/dual_variant_calc/ibnr_reserve_variant_divergence_on_risk_pool
        """
        pool = build_reserving_scenario(api)["pool"]

        assert_fields(
            pool,
            {
                "funded_cents": 20000,
                "paid_claims_cents": 13520,
                "member_months_bps": 10000,
                "status": "CLOSED_FOR_INCURRAL",
                "ibnr_reserve_cents": 0,
                "ibnr_method_used": None,
            },
        )

    def test_completion_factor_scales_the_paid_triangle_up_to_ultimate(self, api):
        """PRD §3.7: "Under the `COMPLETION_FACTOR` method, an ultimate figure is
        computed as the pool's `paid_claims_cents` multiplied by 10000 and
        divided by the agreement's `ibnr_completion_factor_bps`, rounded half up
        to whole cents; the reserve is that ultimate figure less
        `paid_claims_cents`, floored at zero so it is never negative."

        Design: Difficulty/dual_variant_calc/ibnr_reserve_variant_divergence_on_risk_pool
        """
        built = build_reserving_scenario(api)
        reserved = reserve_pool(api, built["pool"]["id"])

        assert_fields(
            reserved,
            {
                "status": "RESERVED",
                "ibnr_method_used": "COMPLETION_FACTOR",
                "ibnr_reserve_cents": 3380,
            },
        )

    def test_pmpm_loss_ratio_anchors_on_exposure_instead(self, api):
        """PRD §3.7: "Under the `PMPM_LOSS_RATIO` method, an expected figure is
        computed as the agreement's `target_claims_pmpm_cents` multiplied by the
        pool's `member_months_bps` as a proportion of 10000, rounded half up to
        whole cents; the reserve is that expected figure less
        `paid_claims_cents`, again floored at zero."

        Design: Difficulty/dual_variant_calc/ibnr_reserve_variant_divergence_on_risk_pool
        """
        built = build_reserving_scenario(api)
        reserve_pool(api, built["pool"]["id"])
        re_reserved = reserve_pool(
            api, built["pool"]["id"], ibnr_method_override="PMPM_LOSS_RATIO"
        )

        assert_fields(
            re_reserved,
            {
                "status": "RESERVED",
                "ibnr_method_used": "PMPM_LOSS_RATIO",
                "ibnr_reserve_cents": 1480,
            },
        )

    def test_the_override_is_what_lands_in_ibnr_method_used(self, api):
        """PRD §3.7: "The method actually applied is written to
        `ibnr_method_used`: the supplied `ibnr_method_override` when one is
        present, otherwise the agreement's default `ibnr_method`."

        Design: Difficulty/dual_variant_calc/ibnr_reserve_variant_divergence_on_risk_pool
        """
        built = build_reserving_scenario(api)
        assert built["agreement"]["ibnr_method"] == "COMPLETION_FACTOR"

        defaulted = reserve_pool(api, built["pool"]["id"])
        assert defaulted["ibnr_method_used"] == "COMPLETION_FACTOR"

        overridden = reserve_pool(
            api, built["pool"]["id"], ibnr_method_override="PMPM_LOSS_RATIO"
        )
        assert overridden["ibnr_method_used"] == "PMPM_LOSS_RATIO"

    def test_the_two_reserves_diverge_by_more_than_a_factor_of_two(self, api):
        """PRD §3.7: "Same pool, same claims, two reserves differing by more than
        a factor of two, and therefore two entirely different settlement
        waterfalls."

        Design: Difficulty/dual_variant_calc/ibnr_reserve_variant_divergence_on_risk_pool
        """
        built = build_reserving_scenario(api)
        completion_factor = reserve_pool(api, built["pool"]["id"])
        loss_ratio = reserve_pool(
            api, built["pool"]["id"], ibnr_method_override="PMPM_LOSS_RATIO"
        )

        assert completion_factor["ibnr_reserve_cents"] == 3380
        assert loss_ratio["ibnr_reserve_cents"] == 1480
        assert completion_factor["ibnr_reserve_cents"] > 2 * loss_ratio["ibnr_reserve_cents"]


class TestSettlementTierPinnedBeforeAdminFee:
    def _propose(self, api):
        built = build_reserving_scenario(api)
        scorecard = build_final_scorecard(
            api,
            built["physician"]["id"],
            hedis_composite_bps=9000,
            access_score_bps=8000,
            patient_experience_bps=7000,
        )
        reserve_pool(api, built["pool"]["id"])
        proposed = propose_settlement(api, built["pool"]["id"])
        return built, scorecard, proposed

    def test_surplus_tier_is_keyed_on_the_pre_administrative_fee_ratio(self, api):
        """PRD §3.8: "The pre-fee ratio truncates to 1550 basis points, placing
        the pool in `TIER_3`, so the fee rate is 1000 basis points and
        `admin_fee_cents` is 310."

        Design: Difficulty/combinatorial_formula/settlement_tier_pinned_before_admin_fee
        """
        _built, _scorecard, proposed = self._propose(api)

        assert_fields(
            proposed,
            {
                "status": "SETTLEMENT_PROPOSED",
                "raw_surplus_cents": 3100,
                "surplus_tier": "TIER_3",
                "admin_fee_cents": 310,
            },
        )

    def test_shared_savings_pool_is_not_recomputed_after_the_fee(self, api):
        """PRD §3.8: "Re-tiering after the fee would have produced a ratio of
        1395, a `TIER_2` classification, a 5000 basis-point share and an answer
        of 1395 — different and wrong."

        Design: Difficulty/combinatorial_formula/settlement_tier_pinned_before_admin_fee
        """
        _built, _scorecard, proposed = self._propose(api)

        assert proposed["distributable_surplus_cents"] == 2790
        assert proposed["shared_savings_pool_cents"] == 1674
        assert proposed["shared_savings_pool_cents"] != 1395
        assert proposed["surplus_tier"] != "TIER_2"

    def test_net_claims_absorb_the_reserve_before_the_surplus_is_taken(self, api):
        """PRD §3.8: "A pool with `funded_cents` 20000, `paid_claims_cents`
        13520, no stop-loss recovery and an `ibnr_reserve_cents` of 3380 has net
        claims of 16900 and a `raw_surplus_cents` of 3100."

        Design: Difficulty/combinatorial_formula/settlement_tier_pinned_before_admin_fee
        """
        _built, _scorecard, proposed = self._propose(api)

        assert proposed["funded_cents"] == 20000
        assert proposed["paid_claims_cents"] == 13520
        assert proposed["stop_loss_recovery_cents"] == 0
        assert proposed["ibnr_reserve_cents"] == 3380
        assert proposed["funded_cents"] - (
            proposed["paid_claims_cents"]
            - proposed["stop_loss_recovery_cents"]
            + proposed["ibnr_reserve_cents"]
        ) == proposed["raw_surplus_cents"]

    def test_the_sole_participant_distribution_snapshots_quality_figures(self, api):
        """PRD §3.8: "Each participant's distribution snapshots two figures at
        proposal time: `composite_score_bps_snapshot` takes the physician's
        current `quality_composite_bps`, and `withhold_release_bps_snapshot`
        takes the `withhold_release_bps` of the `FINAL` scorecard used."

        Design: Difficulty/combinatorial_formula/settlement_tier_pinned_before_admin_fee
        """
        built, scorecard, _proposed = self._propose(api)
        distributions = list_pool_distributions(api, built["pool"]["id"])

        assert len(distributions) == 1
        distribution = distributions[0]
        assert scorecard["composite_score_bps"] == 8200
        assert scorecard["withhold_release_bps"] == 7500
        assert_fields(
            distribution,
            {
                "physician_id": built["physician"]["id"],
                "composite_score_bps_snapshot": 8200,
                "withhold_release_bps_snapshot": 7500,
                "panel_member_months_bps": 10000,
                "status": "PROPOSED",
            },
        )

    def test_the_whole_shared_savings_pool_lands_on_the_only_participant(self, api):
        """PRD §3.8: "`net_distribution_cents` is `withhold_release_cents` plus
        `shared_savings_cents`."

        Design: Difficulty/combinatorial_formula/settlement_tier_pinned_before_admin_fee
        """
        built, _scorecard, _proposed = self._propose(api)
        distribution = list_pool_distributions(api, built["pool"]["id"])[0]

        assert built["agreement"]["quality_withhold_bps"] == 0
        assert_fields(
            distribution,
            {
                "withhold_share_cents": 0,
                "withhold_release_cents": 0,
                "shared_savings_cents": 1674,
                "net_distribution_cents": 1674,
            },
        )
        assert read_pool(api, built["pool"]["id"])["shared_savings_pool_cents"] == 1674
