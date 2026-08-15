"""RWA computation: dual variants, per-line floor discipline, null ratios.

Covers the standardized vs advanced per-line values (PRD §3.2), the
per-line-floor-then-sum aggregation discipline (PRD §2.6), the capital-stack
caps (PRD §3.3), and the null-ratio rule when RWA is zero (PRD §3.3).
"""
from test_helpers import (
    validate_success,
    get_success_data,
    assert_risk_exposure,
    create_bank,
    create_period,
    add_exposure,
    add_instrument,
    create_prepared_call_report,
    create_bank_payload,
    create_reporting_period_payload,
    create_risk_exposure_payload,
)


def _assert_variant_values(api, headers, bank_id, period_id, exposure_id, expected_std, expected_adv):
    data = validate_success(api.get_risk_exposure(bank_id, period_id, exposure_id, headers))
    assert_risk_exposure(data)
    assert data["rwa_cents_standardized"] == expected_std, (
        f"rwa_cents_standardized: expected {expected_std}, got {data['rwa_cents_standardized']}"
    )
    assert data["rwa_cents_advanced"] == expected_adv, (
        f"rwa_cents_advanced: expected {expected_adv}, got {data['rwa_cents_advanced']}"
    )


class TestDualVariantCalc(object):
    def test_rwa_variants_standardized_bank(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "The standardized line value, aggregated into
        rwa_cents_standardized, is the exposure_at_default_cents multiplied by
        the risk_weight_bps and divided by 10000, floored to a whole cent; the
        collateral haircut plays no part in it. The advanced line value,
        aggregated into rwa_cents_advanced, first reduces the exposure by its
        haircut — multiplying by (10000 minus collateral_haircut_bps) over
        10000 and flooring — then applies the risk weight over 10000 and
        finally the advanced-approaches multiplier of 1.06 (that is, 10600
        over 10000), flooring the line to a whole cent. Both are computed at
        record time, for every bank regardless of methodology, so that the
        later floor comparison and disclosures always have both variants at
        hand."

        Design: Difficulty/dual_variant_calc/rwa_standardized_vs_advanced_on_same_exposure
        """
        bank = create_bank("CH-STD-001", methodology="STANDARDIZED", legal_name="StdBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        exposure = add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=10_000_000_000,
            risk_weight_bps=5000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        # floor(10e9 * 5000 / 10000) = 5_000_000_000
        # floor(floor(10e9 * 10000/10000) * 5000 * 10600 / 1e8) = 5_300_000_000
        _assert_variant_values(
            api, capital_analyst_headers, bank["id"], period["id"], exposure["id"],
            5_000_000_000, 5_300_000_000,
        )

    def test_rwa_variants_advanced_bank(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "The standardized line value, aggregated into
        rwa_cents_standardized, is the exposure_at_default_cents multiplied by
        the risk_weight_bps and divided by 10000, floored to a whole cent; the
        collateral haircut plays no part in it. The advanced line value,
        aggregated into rwa_cents_advanced, first reduces the exposure by its
        haircut — multiplying by (10000 minus collateral_haircut_bps) over
        10000 and flooring — then applies the risk weight over 10000 and
        finally the advanced-approaches multiplier of 1.06 (that is, 10600
        over 10000), flooring the line to a whole cent. Both are computed at
        record time, for every bank regardless of methodology, so that the
        later floor comparison and disclosures always have both variants at
        hand."

        Design: Difficulty/dual_variant_calc/rwa_standardized_vs_advanced_on_same_exposure
        """
        bank = create_bank("CH-ADV-001", methodology="ADVANCED", legal_name="AdvBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        exposure = add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=10_000_000_000,
            risk_weight_bps=5000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        # Identical inputs as a STANDARDIZED bank -> identical per-line variants.
        _assert_variant_values(
            api, capital_analyst_headers, bank["id"], period["id"], exposure["id"],
            5_000_000_000, 5_300_000_000,
        )

    def test_rwa_variants_diverge_on_identical_inputs(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "the collateral haircut plays no part in it. The advanced
        line value, aggregated into rwa_cents_advanced, first reduces the
        exposure by its haircut — multiplying by (10000 minus
        collateral_haircut_bps) over 10000 and flooring — then applies the
        risk weight over 10000 and finally the advanced-approaches multiplier
        of 1.06 (that is, 10600 over 10000), flooring the line to a whole
        cent."

        Design: Difficulty/dual_variant_calc/rwa_standardized_vs_advanced_on_same_exposure
        """
        bank = create_bank("CH-DIV-001", legal_name="DivBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        exposure = add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=10_000_000_000,
            risk_weight_bps=5000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        data = validate_success(
            api.get_risk_exposure(bank["id"], period["id"], exposure["id"], capital_analyst_headers)
        )
        # 1.06 multiplier on zero haircut makes the advanced variant strictly larger.
        assert data["rwa_cents_advanced"] - data["rwa_cents_standardized"] == 300_000_000

    def test_capital_stack_t2_capped_at_two_pct_of_rwa(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "the counted Tier 2 amount is the smallest of the raw T2
        sum, 2 percent of RWA (rwa_cents times 200 over 10000, floored), and
        100 percent of cet1_cents, and total_capital_cents is tier1_cents plus
        that counted Tier 2."

        Design: Difficulty/dual_variant_calc/cet1_total_capital_dual_variant_under_t2_cap
        """
        bank = create_bank("CH-CAP-001", methodology="STANDARDIZED", legal_name="CapStackBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
            risk_weight_bps=10000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        add_instrument(bank["id"], instrument_class="CET1", instrument_subtype="COMMON_STOCK",
                       outstanding_amount_cents=8_000_000_000, issuance_date="2020-01-15",
                       contractual_rate_bps=0)
        add_instrument(bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
                       outstanding_amount_cents=3_000_000_000, issuance_date="2022-01-15",
                       maturity_date="2032-12-31", contractual_rate_bps=500)
        report = create_prepared_call_report(bank["id"], period["id"])
        assert report["cet1_cents"] == 8_000_000_000
        assert report["tier1_cents"] == 8_000_000_000
        assert report["rwa_cents"] == 100_000_000_000
        # t2_counted = min(3e9 raw, 2% RWA = 2e9, 100% CET1 = 8e9) = 2e9
        assert report["total_capital_cents"] == 10_000_000_000, (
            f"total_capital_cents: expected 10000000000, got {report['total_capital_cents']}"
        )

    def test_capital_stack_t2_two_pct_cap_wins_over_raw_and_cet1(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "the counted Tier 2 amount is the smallest of the raw T2
        sum, 2 percent of RWA (rwa_cents times 200 over 10000, floored), and
        100 percent of cet1_cents"

        Design: Difficulty/dual_variant_calc/cet1_total_capital_dual_variant_under_t2_cap
        """
        # Same pinned inputs, asserted from the GET endpoint after prepare so
        # the binding cap is checked independent of the prepare response.
        bank = create_bank("CH-CAP-002", methodology="STANDARDIZED", legal_name="CapStackBank2")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=100_000_000_000,
            risk_weight_bps=10000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        add_instrument(bank["id"], instrument_class="CET1", instrument_subtype="COMMON_STOCK",
                       outstanding_amount_cents=8_000_000_000, issuance_date="2020-01-15",
                       contractual_rate_bps=0)
        add_instrument(bank["id"], instrument_class="T2", instrument_subtype="SUBORDINATED_DEBT",
                       outstanding_amount_cents=3_000_000_000, issuance_date="2022-01-15",
                       maturity_date="2032-12-31", contractual_rate_bps=500)
        report = create_prepared_call_report(bank["id"], period["id"])
        fetched = validate_success(
            api.get_call_report(bank["id"], period["id"], report["id"], capital_analyst_headers)
        )
        # 8e9 tier1 + 2e9 counted T2; neither 11e9 (raw) nor 16e9 (CET1 cap).
        assert fetched["total_capital_cents"] == 10_000_000_000
        assert fetched["tier1_cents"] == 8_000_000_000


class TestPerLineFloorThenSum(object):
    def test_rwa_per_line_floor_then_sum_report_total(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.6: "First, aggregation is per-line, then sum: each exposure
        line, each instrument line, and each projected loss is rounded down —
        floored — to a whole cent before any summation, and division is never
        deferred to the aggregate."

        Design: Difficulty/combinatorial_formula/rwa_per_line_floor_then_sum_mode_b_rounding
        """
        bank = create_bank("CH-RND-001", methodology="STANDARDIZED", legal_name="RoundBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        exposure_ids = []
        for _ in range(3):
            exposure = add_exposure(
                bank["id"], period["id"],
                exposure_class="CORPORATE", exposure_at_default_cents=3,
                risk_weight_bps=9000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
            )
            exposure_ids.append(exposure["id"])
        report = create_prepared_call_report(bank["id"], period["id"])
        # Per-line floor: 3 * floor(3 * 9000 / 10000) = 3 * 2 = 6.
        assert report["rwa_standardized_cents"] == 6, (
            f"rwa_standardized_cents: expected 6, got {report['rwa_standardized_cents']}"
        )

    def test_rwa_per_line_floor_each_line(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §2.6: "each exposure line, each instrument line, and each
        projected loss is rounded down — floored — to a whole cent before any
        summation, and division is never deferred to the aggregate."

        Design: Difficulty/combinatorial_formula/rwa_per_line_floor_then_sum_mode_b_rounding
        """
        bank = create_bank("CH-RND-002", methodology="STANDARDIZED", legal_name="RoundBank2")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        lines = []
        for _ in range(3):
            exposure = add_exposure(
                bank["id"], period["id"],
                exposure_class="CORPORATE", exposure_at_default_cents=3,
                risk_weight_bps=9000, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
            )
            lines.append(exposure["id"])
        total = 0
        for exposure_id in lines:
            data = validate_success(
                api.get_risk_exposure(bank["id"], period["id"], exposure_id, capital_analyst_headers)
            )
            # floor(3 * 9000 / 10000) = floor(2.7) = 2 per line.
            assert data["rwa_cents_standardized"] == 2
            total += data["rwa_cents_standardized"]
        # Sum-of-per-line-floors is 6; sum-then-divide would give
        # floor(9 * 9000 / 10000) = 8 — the aggregate must be 6, not 8.
        assert total == 6
        assert total != 8

    def test_rwa_computed_fields_ignore_input(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.2: "The standardized line value, aggregated into
        rwa_cents_standardized, is the exposure_at_default_cents multiplied by
        the risk_weight_bps and divided by 10000, floored to a whole cent"

        Design: Corner/entities/risk_exposure_computed_fields_ignore_input
        """
        bank = create_bank("CH-CIG-001", legal_name="CompIgnBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        exposure = add_exposure(
            bank["id"], period["id"],
            exposure_class="CORPORATE", exposure_at_default_cents=10_000_000,
            risk_weight_bps=5000, obligor_grade="INVESTMENT_GRADE",
        )
        # floor(10_000_000 * 5000 / 10000) = 5_000_000, computed by the server.
        assert exposure["rwa_cents_standardized"] == 5_000_000


class TestNullRatios(object):
    def test_rwa_zero_division_yields_null_ratios(self, api, system_operator_headers, capital_analyst_headers):
        """PRD §3.3: "When rwa_cents is zero the three capital ratios are
        null; when total_exposure_cents is zero the leverage ratio is null."

        Design: Corner/calculations/rwa_zero_division_yields_null_ratios
        """
        bank = create_bank("CH-ZRO-001", legal_name="ZeroBank")
        period = create_period(bank["id"], "2026-06-30", 2026, "Q2")
        # SOVEREIGN line with risk weight 0 -> rwa_cents == 0, exposure nonzero.
        add_exposure(
            bank["id"], period["id"],
            exposure_class="SOVEREIGN", exposure_at_default_cents=1_000_000_000,
            risk_weight_bps=0, obligor_grade="INVESTMENT_GRADE", collateral_haircut_bps=0,
        )
        add_instrument(bank["id"], outstanding_amount_cents=1_000_000_000)
        report = create_prepared_call_report(bank["id"], period["id"])
        assert report["rwa_cents"] == 0
        assert report["cet1_ratio_bps"] is None
        assert report["tier1_ratio_bps"] is None
        assert report["total_ratio_bps"] is None
        # Leverage divides by total_exposure_cents (1e9 here), so it is computable.
        assert report["leverage_ratio_bps"] is not None
