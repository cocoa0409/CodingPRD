"""Pipeline spend forecasting: dual variants, launch-year proration, horizon
exclusion, and in-line spend annualization (PRD §3.8)."""
from test_helpers import (
    assert_spend_forecast_run,
    pay_claim,
    register_pipeline_drug,
    run_forecast,
    set_clock,
    setup_approved_scenario,
    submit_claim,
    TEST_USERS,
    validate_success,
)

ANALYST = TEST_USERS["pharmacy_analyst_headers"]


def _register_reference_pipeline_drug():
    """Pipeline drug from the PRD §3.8 arithmetic: approval 2027-01-15 (inside
    forecast year 1 [2026-08-01, 2027-08-01)), prevalence 50/100k on 1,000,000
    members -> 500 patients, annual cost 1,200,000 cents, uptakes 0.30 / 0.60,
    erosion 0.25."""
    return register_pipeline_drug(
        drug_name="PipelineX",
        expected_approval_date="2027-01-15",
        prevalence_per_100k=50,
        projected_annual_cost_cents=1200000,
        year1_uptake_pct=0.30,
        steady_state_uptake_pct=0.60,
        biosimilar_erosion_pct=0.25,
    )


# Year 1: 500 patients x 1,200,000 x 0.30 x 198/365 -> round_half_up = 97,643,836
# (198 days from 2027-01-15 to the year-1 end 2027-08-01).
# Year 2 (approval precedes the year): 500 x 1,200,000 x 0.60 = 360,000,000.
EXPECTED_PIPELINE_TOTAL = 97_643_836 + 360_000_000  # 457,643,836
EXPECTED_POLICY_ADJUSTED = 343_232_877  # round_half_up(457,643,836 x 0.75)


class TestForecastVariants:
    def test_baseline_forecast_literal_totals(self, api):
        """PRD §3.8: "when approval falls inside the year, the fraction is
        `year1_uptake_pct` prorated by the number of days from the approval date to that
        year's end, divided by 365; and when approval precedes the year, the fraction is
        `steady_state_uptake_pct`"; "`total_projected_cents` is `pipeline_total_cents`
        plus `inline_annualized_cents` multiplied by `horizon_years`."

        Design: Difficulty/dual_variant_calc/forecast_baseline_vs_policy_adjusted
        """
        _register_reference_pipeline_drug()
        run = run_forecast("BASELINE", horizon_years=2, enrollment_projection=1000000)
        assert_spend_forecast_run(run)
        assert run["pipeline_total_cents"] == 457_643_836
        assert run["inline_annualized_cents"] == 0, "no PAID/ADJUSTED claims exist"
        assert run["total_projected_cents"] == 457_643_836

    def test_policy_adjusted_applies_erosion_multiplier(self, api):
        """PRD §3.8: "Under the `POLICY_ADJUSTED` variant, each included drug's summed
        projection is then multiplied by one minus its `biosimilar_erosion_pct`, rounded
        half-up once per drug, modeling biosimilar substitution savings — totals strictly
        lower than `BASELINE` whenever any included drug has positive erosion."

        Design: Difficulty/dual_variant_calc/forecast_baseline_vs_policy_adjusted
        """
        _register_reference_pipeline_drug()
        baseline = run_forecast("BASELINE", horizon_years=2, enrollment_projection=1000000)
        adjusted = run_forecast(
            "POLICY_ADJUSTED", horizon_years=2, enrollment_projection=1000000
        )
        assert adjusted["pipeline_total_cents"] == 343_232_877
        assert adjusted["total_projected_cents"] == 343_232_877
        assert adjusted["pipeline_total_cents"] < baseline["pipeline_total_cents"]


class TestYearProrationAndExclusion:
    def test_launch_year_proration_literal(self, api):
        """PRD §3.8: "Each year's cost — the patient pool times
        `projected_annual_cost_cents` times that year's fraction — is rounded half-up to
        whole cents per year, and the drug's projection is the sum of those per-year
        rounded costs, recorded in `per_drug_projections` as a pairing of
        `pipeline_drug_id` with `projected_cents`."

        Design: Difficulty/combinatorial_formula/forecast_year_proration_and_exclusion
        """
        p_in = _register_reference_pipeline_drug()
        run = run_forecast("BASELINE", horizon_years=2, enrollment_projection=1000000)
        entries = {e["pipeline_drug_id"]: e["projected_cents"] for e in run["per_drug_projections"]}
        assert entries.get(p_in["id"]) == 457_643_836, (
            "launch-year proration 97,643,836 + steady-state 360,000,000"
        )
        assert run["pipeline_total_cents"] == 457_643_836

    def test_drug_beyond_horizon_excluded(self, api):
        """PRD §3.8: "A drug whose `expected_approval_date` falls on or after the end of
        the final horizon year is excluded from `per_drug_projections` and contributes
        nothing." The two-year horizon ends 2028-08-01; approval 2030-01-01 is beyond it.

        Design: Difficulty/combinatorial_formula/forecast_year_proration_and_exclusion
        """
        _register_reference_pipeline_drug()
        p_out = register_pipeline_drug(
            drug_name="BeyondHorizon",
            expected_approval_date="2030-01-01",
            prevalence_per_100k=80,
            projected_annual_cost_cents=900000,
            year1_uptake_pct=0.40,
            steady_state_uptake_pct=0.70,
            biosimilar_erosion_pct=0.10,
        )
        run = run_forecast("BASELINE", horizon_years=2, enrollment_projection=1000000)
        ids = [e["pipeline_drug_id"] for e in run["per_drug_projections"]]
        assert len(ids) == 1, "only the in-horizon drug is projected"
        assert p_out["id"] not in ids
        assert run["pipeline_total_cents"] == 457_643_836


class TestInlineAnnualizedSpend:
    def test_window_and_status_filtering(self, api):
        """PRD §3.8: "The observation window is the trailing ninety days ending at — and
        excluding — the as-of date. The base sums `allowed_amount_cents` over claims in
        `PAID` or `ADJUSTED` with a `service_date` inside that window; pended,
        approved-but-unpaid, and denied claims never count. The `inline_annualized_cents`
        is that base scaled by 365 over 90, rounded half-up once at the end."

        Clock plan (forward-only, PRD §2.4): claims are created at the startup clock
        2026-08-01 and the forecast runs at 2026-10-30, so the half-open window is
        [2026-08-01, 2026-10-30). Claim A (paid, service 2026-08-01) counts; claim B
        (paid, service on the as-of date) is excluded; claim C (unpaid) never counts.
        round(1060 x 365 / 90) = 4299.

        Design: Corner/calculations/inline_annualized_input_set_and_window
        """
        scenario = setup_approved_scenario(
            drug_overrides={"j_code": "J5200", "drug_name": "AggDrug"},
            member_id="MEM-C1",
        )
        claim_a = submit_claim(scenario, billed_units=2, service_date="2026-08-01")
        assert claim_a["allowed_amount_cents"] == 1060
        pay_claim(claim_a["id"])

        set_clock("2026-10-30T00:00:00Z")

        claim_b = submit_claim(scenario, billed_units=2, service_date="2026-10-30")
        pay_claim(claim_b["id"])
        claim_c = submit_claim(scenario, billed_units=2, service_date="2026-08-01")
        assert claim_c["status"] == "APPROVED_FOR_PAYMENT"  # unpaid: excluded

        run = run_forecast("BASELINE", horizon_years=1, enrollment_projection=500000)
        assert str(run["as_of_date"]).startswith("2026-10-30"), (
            "the run stamps as_of_date with the current clock date (PRD §3.8)"
        )
        assert run["inline_annualized_cents"] == 4299
        assert run["pipeline_total_cents"] == 0
        assert run["total_projected_cents"] == 4299

        reread = validate_success(api.get_spend_forecast(run["id"], ANALYST))
        assert reread == run, "stored snapshot re-reads identically (immediate consistency)"
