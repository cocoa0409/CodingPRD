"""Capital replacement forecasting: variant divergence, factor-table and
past-life clamp interaction, and decommissioned-asset exclusion."""
from test_helpers import (
    TEST_USERS,
    validate_success,
    ApiErrorId,
    api_client,
    create_property, create_building, create_unit, create_asset,
    create_template, create_plan, create_batch, add_visit, publish_batch,
    set_clock, start_visit, complete_visit,
    create_forecast_payload,
    setup_property_scaffold,
)

TEST_PM = TEST_USERS["property_manager_headers"]


class TestForecastAgeVsConditionBucketDivergence:
    """One HVAC asset installed 2020-08-01, expected_life_months=84,
    replacement_cost_cents=500000, condition_score=5 recorded via a completed PM
    visit. The clock is returned to the default 2026-08-01 before forecasting so
    year zero covers [2026-08-01, 2027-08-01)."""

    def _setup(self):
        ctx = setup_property_scaffold(
            occupancy="OCCUPIED", component_type="HVAC",
            installed_on="2020-08-01T00:00:00Z", expected_life_months=84,
            replacement_cost_cents=500000, estimated_labor_minutes=60,
            frequency_days=180, budget_cents=100000000,
        )
        batch = create_batch(ctx["property"]["id"], window_start="2026-08-02T08:00:00Z",
                             window_end="2026-08-02T18:00:00Z")
        visit = add_visit(batch["id"], ctx["unit"]["id"], ctx["template"]["id"],
                          ctx["asset"]["id"], ctx["plan"]["id"],
                          scheduled_start="2026-08-02T09:00:00Z")
        publish_batch(batch["id"])
        set_clock("2026-08-02T09:00:00Z")
        start_visit(visit["id"], technician_id="tech-1")
        complete_visit(visit["id"], 55, 5, technician_id="tech-1")
        # Return the logical clock to the default reading so the horizon
        # intervals are anchored at 2026-08-01.
        set_clock("2026-08-01T00:00:00Z")
        return ctx

    def test_age_based_buckets_nominal_life_into_year_one(self, api):
        """PRD §3.7: "`AGE_BASED` uses the asset's `expected_life_months`
        unchanged and ignores condition entirely". A nominal 84-month life from
        2020-08-01 ends 2027-08-01, inside year one's [2027-08-01, 2028-08-01)
        interval. PRD §3.7: "The snapshot's `per_year_cents` is an array of
        exactly `horizon_years` integers, each the sum of `replacement_cost_cents`
        over the assets bucketed to that year; `total_projected_cents` is the sum
        of that array; and `asset_count_projected` is the number of assets
        bucketed anywhere within the horizon."

        Design: Difficulty/dual_variant_calc/forecast_age_vs_condition_bucket_divergence
        """
        ctx = self._setup()
        resp = api.create_capital_forecast(
            create_forecast_payload(ctx["property"]["id"], horizon_years=5, variant="AGE_BASED"),
            TEST_PM,
        )
        snap = validate_success(resp, expected_status=201)
        assert snap["per_year_cents"] == [0, 500000, 0, 0, 0], (
            f"AGE_BASED replacement 2027-08-01 must bucket to year 1, got {snap['per_year_cents']}"
        )
        assert snap["total_projected_cents"] == 500000
        assert snap["asset_count_projected"] == 1

    def test_condition_based_defers_replacement_to_year_three(self, api):
        """PRD §3.7: "`CONDITION_BASED` multiplies `expected_life_months` by a
        condition factor — 0.60 for a `condition_score` of 1, 0.80 for 2, 1.00
        for 3, 1.15 for 4, and 1.30 for 5" and "The scaled figure is rounded down
        to a whole number of months before any date arithmetic." A score of 5
        scales 84 months to floor(109.2)=109 months, ending 2029-09-01, inside
        year three — a different bucket than the AGE_BASED reading of identical
        inputs.

        Design: Difficulty/dual_variant_calc/forecast_age_vs_condition_bucket_divergence
        """
        ctx = self._setup()
        snap_age = validate_success(api.create_capital_forecast(
            create_forecast_payload(ctx["property"]["id"], horizon_years=5, variant="AGE_BASED"),
            TEST_PM,
        ), expected_status=201)
        snap_cond = validate_success(api.create_capital_forecast(
            create_forecast_payload(ctx["property"]["id"], horizon_years=5, variant="CONDITION_BASED"),
            TEST_PM,
        ), expected_status=201)
        assert snap_cond["per_year_cents"] == [0, 0, 0, 500000, 0], (
            f"CONDITION_BASED replacement 2029-09-01 must bucket to year 3, got {snap_cond['per_year_cents']}"
        )
        assert snap_cond["total_projected_cents"] == 500000
        assert snap_cond["asset_count_projected"] == 1
        assert snap_age["per_year_cents"] != snap_cond["per_year_cents"]


class TestForecastModeNonlinearInteraction:
    """Two assets in one unit: A1 installed 2020-08-01, life 84, cost 500000,
    condition_score=1; A2 installed 2024-08-01, life 96, cost 300000,
    condition_score=3. Clock is returned to 2026-08-01 before forecasting."""

    def _setup(self):
        prop = create_property()
        building = create_building(prop["id"])
        unit = create_unit(building["id"], occupancy_status="VACANT")
        a1 = create_asset(unit["id"], component_type="HVAC",
                          installed_on="2020-08-01T00:00:00Z", warranty_months=12,
                          expected_life_months=84, replacement_cost_cents=500000)
        a2 = create_asset(unit["id"], component_type="WATER_HEATER",
                          installed_on="2024-08-01T00:00:00Z", warranty_months=12,
                          expected_life_months=96, replacement_cost_cents=300000)
        t1 = create_template(prop["id"], component_type="HVAC", task_name="HVAC svc",
                             estimated_labor_minutes=60)
        t2 = create_template(prop["id"], component_type="WATER_HEATER", task_name="WH svc",
                             estimated_labor_minutes=60)
        plan = create_plan(prop["id"], budget_cents=100000000, adopt=True)
        batch = create_batch(prop["id"], window_start="2026-08-02T08:00:00Z",
                             window_end="2026-08-02T20:00:00Z")
        v1 = add_visit(batch["id"], unit["id"], t1["id"], a1["id"], plan["id"],
                       scheduled_start="2026-08-02T09:00:00Z")
        v2 = add_visit(batch["id"], unit["id"], t2["id"], a2["id"], plan["id"],
                       scheduled_start="2026-08-02T11:00:00Z")
        publish_batch(batch["id"])
        set_clock("2026-08-02T09:00:00Z")
        start_visit(v1["id"], technician_id="tech-1")
        complete_visit(v1["id"], 60, 1, technician_id="tech-1")
        set_clock("2026-08-02T11:00:00Z")
        start_visit(v2["id"], technician_id="tech-1")
        complete_visit(v2["id"], 60, 3, technician_id="tech-1")
        set_clock("2026-08-01T00:00:00Z")
        return prop

    def test_condition_based_past_life_clamp_and_horizon_cutoff(self, api):
        """PRD §3.7: "A replacement date already before the clock buckets into
        year zero; otherwise the date falls into the year whose interval contains
        it, and dates at or beyond the end of the horizon are not projected at
        all." Score 1 scales A1's life to floor(84*0.60)=50 months, ending
        2024-10-01 — already past — so it buckets to year zero; A2's unscaled
        96-month life ends 2032-08-01, beyond the 5-year horizon.

        Design: Difficulty/combinatorial_formula/forecast_mode_a_nonlinear_interaction
        """
        prop = self._setup()
        snap = validate_success(api.create_capital_forecast(
            create_forecast_payload(prop["id"], horizon_years=5, variant="CONDITION_BASED"),
            TEST_PM,
        ), expected_status=201)
        assert snap["per_year_cents"] == [500000, 0, 0, 0, 0], (
            f"A1 must clamp into year zero, got {snap['per_year_cents']}"
        )
        assert snap["total_projected_cents"] == 500000
        assert snap["asset_count_projected"] == 1

    def test_age_based_buckets_both_assets_by_nominal_life(self, api):
        """PRD §3.7: "`AGE_BASED` uses the asset's `expected_life_months`
        unchanged and ignores condition entirely". A1's nominal life ends
        2027-08-01 (year one); A2's ends 2032-08-01, beyond the horizon.

        Design: Difficulty/combinatorial_formula/forecast_mode_a_nonlinear_interaction
        """
        prop = self._setup()
        snap = validate_success(api.create_capital_forecast(
            create_forecast_payload(prop["id"], horizon_years=5, variant="AGE_BASED"),
            TEST_PM,
        ), expected_status=201)
        assert snap["per_year_cents"] == [0, 500000, 0, 0, 0], (
            f"A1 must bucket to year 1 under nominal life, got {snap['per_year_cents']}"
        )
        assert snap["total_projected_cents"] == 500000
        assert snap["asset_count_projected"] == 1


class TestForecastExcludesDecommissionedAssets:
    def test_decommissioned_asset_dropped_from_input_set(self, api):
        """PRD §3.7: "The input set is every asset of the property that is not
        `DECOMMISSIONED`." PRD §3.7: "The snapshot's `per_year_cents` is an array
        of exactly `horizon_years` integers".

        Design: Corner/calculations/forecast_excludes_decommissioned_assets
        """
        ctx = setup_property_scaffold(
            installed_on="2020-08-01T00:00:00Z", warranty_months=12,
            expected_life_months=84, replacement_cost_cents=500000,
        )
        validate_success(api.decommission_asset(ctx["asset"]["id"], TEST_PM))
        snap = validate_success(api.create_capital_forecast(
            create_forecast_payload(ctx["property"]["id"], horizon_years=5, variant="AGE_BASED"),
            TEST_PM,
        ), expected_status=201)
        assert snap["per_year_cents"] == [0, 0, 0, 0, 0], (
            f"decommissioned asset must be excluded, got {snap['per_year_cents']}"
        )
        assert snap["total_projected_cents"] == 0
        assert snap["asset_count_projected"] == 0
