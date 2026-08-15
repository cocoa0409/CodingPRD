"""Quantitative reserve: scenario blending, reversion, rounding order (PRD §3.4, §3.6, §2.6)."""
from test_helpers import (
    adverse_scenario_payload,
    assert_model_run_totals,
    create_active_model,
    create_draft_run,
    execute_run,
    get_allowance_summary,
    get_model,
    get_segment,
    prime_loan_spec,
    record_charge_off,
    setup_executed_run,
    setup_run_environment,
    substandard_loan_spec,
    validate_success,
)


class TestScenarioWeightingVariants:
    def test_single_scenario_run_rate_and_reserve(self, api):
        """PRD §3.6: "When the weights hold exactly one entry, M is that scenario's multiplier — computed per §3.4 — divided by ten thousand: an exact decimal with no weighting applied."
        PRD §3.6: "The segment's `lifetime_loss_rate_bps` is its `base_loss_rate_bps` multiplied by E, rounded half-up to a whole basis point. Its collective exposure is the sum of `amortized_cost_cents` over its loans that are `ACTIVE` and not individually evaluated. Its quantitative reserve is that exposure multiplied by the lifetime loss rate and divided by ten thousand, rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/scenario_weighted_vs_baseline_only_rate
        """
        env = setup_executed_run(
            loan_specs=[prime_loan_spec(10_000_000)],
            scenario_specs=[{}], weights_bps=[10_000],
        )
        summary = get_allowance_summary(env.run["id"])
        # BASELINE at neutral macro values -> multiplier 10000 bps -> M = 1.0;
        # E = (2*1.0 + 6*1.0)/8 = 1.0; rate = 50 bps; reserve = 50000.
        assert summary["segments_breakdown"][0]["lifetime_loss_rate_bps"] == 50
        assert summary["quantitative_reserve_cents"] == 50_000
        assert_model_run_totals(summary)

    def test_weighted_scenarios_run_rate_and_reserve(self, api):
        """PRD §3.6: "When the weights hold two or more entries, each entry's `weight_bps` is multiplied by its scenario's multiplier, the products are summed, and the sum is divided by ten thousand and then by ten thousand again, again yielding M as an exact decimal; because the weights blend the multipliers, the same portfolio under a weighted blend produces a different rate than under a single scenario."

        Design: Difficulty/dual_variant_calc/scenario_weighted_vs_baseline_only_rate
        """
        env = setup_run_environment(
            loan_specs=[prime_loan_spec(10_000_000)],
            scenario_specs=[{}, adverse_scenario_payload()],
        )
        base_id, adv_id = env.scenarios[0]["id"], env.scenarios[1]["id"]

        run_a = create_draft_run(env.model["id"],
                                 [{"scenario_id": base_id, "weight_bps": 10_000}],
                                 as_of_period="2026-Q1")
        execute_run(run_a["id"])
        run_b = create_draft_run(env.model["id"],
                                 [{"scenario_id": base_id, "weight_bps": 6_000},
                                  {"scenario_id": adv_id, "weight_bps": 4_000}],
                                 as_of_period="2026-Q2")
        execute_run(run_b["id"])

        summary_a = get_allowance_summary(run_a["id"])
        summary_b = get_allowance_summary(run_b["id"])
        # ADVERSE (u=900, g=0) -> mult 20000 bps; M = 0.6*1.0 + 0.4*2.0 = 1.4;
        # E = (2*1.4 + 6*1.0)/8 = 1.1; rate = round_half_up(50 * 1.1) = 55.
        assert summary_b["segments_breakdown"][0]["lifetime_loss_rate_bps"] == 55
        assert summary_b["quantitative_reserve_cents"] == 55_000
        assert summary_a["quantitative_reserve_cents"] == 50_000
        assert summary_a["quantitative_reserve_cents"] != summary_b["quantitative_reserve_cents"]


class TestReversionBranches:
    def test_straight_line_reversion_rate(self, api):
        """PRD §3.6: "Under `STRAIGHT_LINE`, the multiplier steps down from M toward 1.0 in equal increments across the reversion period: during reversion quarter i, counting from one up to the model's `reversion_period_quarters`, the multiplier is M minus the following step-down amount: (M minus 1.0) multiplied by i and then divided by the reversion period plus one. E is then the forecast horizon times M, plus the sum of those reversion-quarter multipliers, plus the product of the quarters of the eight-quarter life covered by neither the forecast horizon nor the reversion period and exactly 1.0, all divided by eight."

        Design: Difficulty/combinatorial_formula/reversion_straight_line_vs_immediate
        """
        env = setup_executed_run(
            model_overrides={
                "name": "CECL-SL", "reversion_method": "STRAIGHT_LINE",
                "forecast_period_quarters": 2, "reversion_period_quarters": 2,
            },
            segment_specs=[{"name": "Auto NearPrime", "product_type": "AUTO",
                            "risk_rating_band": "NEAR_PRIME"}],
            loan_specs=[{"amortized_cost_cents": 100_000, "risk_rating": "PASS"}],
            scenario_specs=[adverse_scenario_payload()],
        )
        summary = get_allowance_summary(env.run["id"])
        # ADVERSE (u=900, g=0) -> M = 2.0; REV = (2 - 1/3) + (2 - 2/3) = 3.0;
        # E = (2*2 + 3.0 + 4*1.0)/8 = 11/8 = 1.375; rate = round_half_up(150*1.375) = 206.
        assert summary["segments_breakdown"][0]["lifetime_loss_rate_bps"] == 206
        assert summary["quantitative_reserve_cents"] == 2_060

    def test_immediate_reversion_rate_and_auto_retire(self, api):
        """PRD §3.6: "Under an `IMMEDIATE` reversion method, the effective horizon multiplier E averages the eight quarters of remaining life with the forecast multiplier holding for the horizon and neutral thereafter: E is the model's `forecast_period_quarters` times M, plus the product of eight minus the forecast horizon and exactly 1.0, all divided by eight."
        PRD §3.1: "a `ModelValidator` activates a `DRAFT` model, moving it to `ACTIVE`, and any other loss model that happens to be `ACTIVE` at that moment is automatically retired to `RETIRED` — at most one model is ever in production."

        Design: Difficulty/combinatorial_formula/reversion_straight_line_vs_immediate
        """
        sl = setup_executed_run(
            model_overrides={
                "name": "CECL-SL", "reversion_method": "STRAIGHT_LINE",
                "forecast_period_quarters": 2, "reversion_period_quarters": 2,
            },
            segment_specs=[{"name": "Auto NearPrime", "product_type": "AUTO",
                            "risk_rating_band": "NEAR_PRIME"}],
            loan_specs=[{"amortized_cost_cents": 100_000, "risk_rating": "PASS"}],
            scenario_specs=[adverse_scenario_payload()],
            as_of_period="2026-Q1",
        )
        # Activating a second model auto-retires the first.
        model_im = create_active_model(name="CECL-IM")  # IMMEDIATE F=2 R=0
        run_im = create_draft_run(
            model_im["id"],
            [{"scenario_id": sl.scenarios[0]["id"], "weight_bps": 10_000}],
            as_of_period="2026-Q2",
        )
        execute_run(run_im["id"])

        summary = get_allowance_summary(run_im["id"])
        row = next(
            r for r in summary["segments_breakdown"]
            if r["segment_id"] == sl.segments[0]["id"]
        )
        # IMMEDIATE F=2, M = 2.0: E = (2*2.0 + 6*1.0)/8 = 1.25;
        # rate = round_half_up(150 * 1.25) = round_half_up(187.5) = 188.
        assert row["lifetime_loss_rate_bps"] == 188
        assert summary["quantitative_reserve_cents"] == 1_880
        assert get_model(sl.model["id"])["status"] == "RETIRED"


class TestRoundingOrder:
    def test_run_total_rounds_per_segment_then_sums(self, api):
        """PRD §2.6: "Second, run-level money totals are sums of components that have already been rounded to whole cents per segment or per evaluation; the sum itself is never re-rounded."
        PRD §3.6: "The run's `quantitative_reserve_cents` is the sum of the per-segment quantitative reserves, each already rounded to whole cents before summing; `qualitative_adjustment_cents` is the corresponding sum of per-segment qualitative adjustments."

        Design: Difficulty/combinatorial_formula/per_segment_round_then_sum_order
        """
        env = setup_executed_run(
            segment_specs=[{"risk_rating_band": "NEAR_PRIME"},
                           {"name": "NearPrime B", "risk_rating_band": "NEAR_PRIME"}],
            loan_specs=[{"amortized_cost_cents": 10_100, "risk_rating": "PASS", "segment_index": 0},
                        {"amortized_cost_cents": 10_100, "risk_rating": "PASS", "segment_index": 1}],
        )
        summary = get_allowance_summary(env.run["id"])
        # Per segment: round_half_up(10100 * 150 / 10000) = round_half_up(151.5) = 152.
        # Pinned order: 152 + 152 = 304; the forbidden sum-then-round yields 303.
        assert summary["quantitative_reserve_cents"] == 304
        assert summary["quantitative_reserve_cents"] != 303
        assert_model_run_totals(summary)

    def test_segments_breakdown_per_segment_reserves(self, api):
        """PRD §3.6: "The rounding order is pinned: the rate is rounded to whole basis points first, and only then is the per-segment reserve rounded to whole cents."
        PRD §3.6: "The `total_allowance_cents` is the sum of those four components, and `total_exposure_cents` is the sum of the per-segment collective exposures plus the amortized cost of every individually evaluated `ACTIVE` loan."

        Design: Difficulty/combinatorial_formula/per_segment_round_then_sum_order
        """
        env = setup_executed_run(
            segment_specs=[{"risk_rating_band": "NEAR_PRIME"},
                           {"name": "NearPrime B", "risk_rating_band": "NEAR_PRIME"}],
            loan_specs=[{"amortized_cost_cents": 10_100, "risk_rating": "PASS", "segment_index": 0},
                        {"amortized_cost_cents": 10_100, "risk_rating": "PASS", "segment_index": 1}],
        )
        summary = get_allowance_summary(env.run["id"])
        reserves = sorted(
            row["quantitative_reserve_cents"] for row in summary["segments_breakdown"]
        )
        assert reserves == [152, 152]
        for row in summary["segments_breakdown"]:
            assert row["exposure_cents"] == 10_100
            assert row["lifetime_loss_rate_bps"] == 150
        assert summary["total_exposure_cents"] == 20_200


class TestMultiplierClamp:
    def test_scenario_multiplier_clamped_at_max(self, api):
        """PRD §3.4: "The result is clamped last, after both sensitivity terms are applied: the multiplier never falls below five thousand basis points, half the neutral level, and never exceeds thirty thousand basis points, three times the neutral level. All of this arithmetic is exact integer work in basis points; nothing is rounded."

        Design: Corner/calculations/scenario_multiplier_clamped_at_max
        """
        env = setup_executed_run(
            loan_specs=[prime_loan_spec(10_000_000)],
            scenario_specs=[adverse_scenario_payload(
                name="Severe", unemployment_rate_bps=2_000, gdp_growth_bps=-1_000,
            )],
        )
        summary = get_allowance_summary(env.run["id"])
        row = summary["segments_breakdown"][0]
        # raw mult = 10000 + (2000-500)*20 + (200-(-1000))*10 = 52000 -> clamp 30000
        assert row["scenario_mult_bps"] == 30_000
        # M = 3.0; E = (2*3.0 + 6*1.0)/8 = 1.5; rate = round_half_up(50*1.5) = 75
        assert row["lifetime_loss_rate_bps"] == 75
        assert summary["quantitative_reserve_cents"] == 75_000


class TestExposureInputSet:
    def test_collective_exposure_excludes_individual_and_charged_off(self, api):
        """PRD §3.6: "Its collective exposure is the sum of `amortized_cost_cents` over its loans that are `ACTIVE` and not individually evaluated."
        PRD §3.6: "The `total_allowance_cents` is the sum of those four components, and `total_exposure_cents` is the sum of the per-segment collective exposures plus the amortized cost of every individually evaluated `ACTIVE` loan."

        Design: Corner/calculations/collective_exposure_excludes_individual_and_charged_off
        """
        env = setup_run_environment(
            loan_specs=[
                prime_loan_spec(10_000_000),
                substandard_loan_spec(500_000, collateral_value_cents=460_000),
                prime_loan_spec(80_000),
            ],
        )
        # Fully charge off the third loan before the run is executed.
        record_charge_off(env.loans[2]["id"], 80_000)

        executed = execute_run(env.run["id"])
        summary = get_allowance_summary(env.run["id"])
        row = summary["segments_breakdown"][0]
        assert row["exposure_cents"] == 10_000_000, (
            "SUBSTANDARD (individually evaluated) and CHARGED_OFF loans are excluded"
        )
        assert summary["quantitative_reserve_cents"] == 50_000  # 50 bps on 10000000
        assert executed["individual_evaluation_count"] == 1
        assert summary["individual_reserve_cents"] == 86_000  # 500000 - (460000 - 46000)
        assert summary["total_exposure_cents"] == 10_500_000
        assert_model_run_totals(summary)

        # Charge-off rate 76 bps stays under the watch threshold.
        seg = get_segment(env.segments[0]["id"])
        assert seg["charge_off_rate_bps"] == 76  # round_half_up(80000*10000/10580000)
        assert seg["status"] == "OPEN"


class TestImmediateConsistency:
    def test_execute_response_immediately_consistent(self, api, credit_analyst_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §2.10: "Two principles govern all such cascades: every mutated resource, primary or collateral, has its `updated_at` refreshed and its `version` incremented; and derived totals are always re-derived from their current components rather than adjusted incrementally, so repeated operations cannot drift the totals away from the true sum of their parts."

        Design: Corner/consistency_model/execute_response_immediately_consistent
        """
        env = setup_run_environment(loan_specs=[prime_loan_spec(10_000_000)])
        execute_res = api.execute_model_run(env.run["id"], credit_analyst_headers)
        executed = validate_success(execute_res, 200)
        assert executed["total_allowance_cents"] == 50_000

        reread = validate_success(api.get_model_run(env.run["id"], credit_analyst_headers), 200)
        assert reread["total_allowance_cents"] == executed["total_allowance_cents"]
        assert reread["quantitative_reserve_cents"] == executed["quantitative_reserve_cents"]
