"""Mitigation-measure pricing and the project burden ledger."""
import pytest

from test_helpers import (
    U_LICENSEE_A,
    U_LICENSEE_B,
    assert_ledger_matches,
    assert_measure_costs,
    assert_postures,
    file_pad,
    new_measure,
    new_project,
    patch_project,
    read_measure,
    read_project,
    record_definitive_estimate,
    set_clock,
)

FISH_LADDER = dict(
    measure_name="Upstream fish ladder",
    resource_category="FISH_PASSAGE",
    source="AGENCY_PRESCRIPTION",
    capital_cost_usd=1200000.00,
    annual_om_cost_usd=45000.00,
    construction_start_year=2029,
    implementation_months=18,
    flow_release_cfs=120,
    gross_head_ft=85,
    release_days=180,
)


def _pad_filed_project(**overrides):
    """A project past pre-application filing, so `pad_year` is 2026."""
    set_clock("2026-08-01T00:00:00Z")
    payload = dict(
        project_name="Cascade Falls",
        installed_capacity_mw=24.0,
        base_annual_generation_mwh=250000,
        license_expiration_date="2033-12-31",
    )
    payload.update(overrides)
    project = new_project(**payload)
    return file_pad(project["id"])


class TestDualVariantMeasureEstimation:
    def test_preliminary_estimate_prices_the_fish_ladder_with_the_flow_proxy(self):
        """A PRELIMINARY fish-passage measure carries 25 percent contingency and head-blind generation loss.

        PRD §3.7: "The contingency allowance is 25 percent under the preliminary variant and 10 percent under the definitive variant; a firmer estimate carries less padding."
        PRD §3.7: "Under the **preliminary** variant, loss is a flow-duration proxy that ignores head entirely: `annual_generation_loss_mwh` is `flow_release_cfs` multiplied by `release_days` multiplied by 0.048 megawatt-hours per cubic-foot-per-second-day, rounded half up to one decimal place."

        Design: Difficulty/dual_variant_calc/pme_preliminary_vs_definitive_estimate_diverge_on_both_axes
        """
        project = _pad_filed_project()
        measure = new_measure(project["id"], user_id=U_LICENSEE_A, **FISH_LADDER)

        assert measure["cost_estimate_variant"] == "PRELIMINARY"
        assert_measure_costs(
            measure,
            escalated_capital_usd=1639090.50,
            annualized_capital_usd=54636.35,
            annual_cost_usd=99636.35,
            annual_generation_loss_mwh=1036.8,
            annual_generation_value_usd=43545.60,
            annual_burden_usd=143181.95,
        )
        assert measure["created_by_user_id"] == U_LICENSEE_A
        assert measure["definitive_estimate_by_user_id"] is None

    def test_definitive_switch_lowers_cost_while_raising_generation_loss(self):
        """The definitive estimate moves cost down to 93079.99 and generation loss up to 3174.1.

        PRD §3.7: "The cost component falls while the generation component rises, and the two move independently."
        PRD §3.7: "Under the **definitive** variant, loss is derived from the physical hydraulics: take `flow_release_cfs`, multiply by `gross_head_ft`, multiply by a plant efficiency of 0.85, divide by a hydraulic constant of 11.8 to obtain kilowatts, multiply by 24 hours and by `release_days` to obtain kilowatt-hours per year, divide by 1000 to convert to megawatt-hours, and round half up to one decimal place."

        Design: Difficulty/dual_variant_calc/pme_preliminary_vs_definitive_estimate_diverge_on_both_axes
        """
        project = _pad_filed_project()
        measure = new_measure(project["id"], user_id=U_LICENSEE_A, **FISH_LADDER)

        switched = record_definitive_estimate(measure["id"], user_id=U_LICENSEE_B)

        assert switched["cost_estimate_variant"] == "DEFINITIVE"
        assert_measure_costs(
            switched,
            escalated_capital_usd=1442399.64,
            annualized_capital_usd=48079.99,
            annual_cost_usd=93079.99,
            annual_generation_loss_mwh=3174.1,
            annual_generation_value_usd=133312.20,
            annual_burden_usd=226392.19,
        )
        assert switched["definitive_estimate_by_user_id"] == U_LICENSEE_B

    def test_definitive_switch_reruns_the_whole_project_ledger(self):
        """The switch rewrites every ledger figure of the owning project in the same request.

        PRD §3.7: "When the measure is `INCLUDED` or `IMPLEMENTED`, the rewrite feeds straight through: the project burden ledger is recomputed and then `regulatory_posture`, so a single request moves both the cost path, downward through the smaller contingency, and the generation path, generally upward through the head-based physical model."

        Design: Difficulty/dual_variant_calc/pme_preliminary_vs_definitive_estimate_diverge_on_both_axes
        """
        project = _pad_filed_project()
        measure = new_measure(project["id"], user_id=U_LICENSEE_A, **FISH_LADDER)
        record_definitive_estimate(measure["id"], user_id=U_LICENSEE_B)

        after = read_project(project["id"])

        assert_ledger_matches(
            after,
            total_pme_annual_cost_usd=93079.99,
            total_generation_loss_mwh=3174.1,
            administrative_annual_charge_usd=1861.60,
            total_annual_burden_usd=228253.79,
            burden_ratio_pct=2.17,
        )
        assert after["economically_infeasible"] is False


class TestMeasureEstimateComposition:
    def test_escalated_estimate_composes_contingency_escalation_amortization_and_head(self):
        """A 2029 construction start escalates the 2026 base capital by three compounded years.

        PRD §3.7: "The number of escalation years is `construction_start_year` minus the project's `pad_year`, floored at zero so that a measure built before or during the pre-application year is never de-escalated."
        PRD §3.7: "Next, `annualized_capital_usd` is `escalated_capital_usd` divided by the amortization life of the measure's `resource_category`, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/pme_estimate_combines_contingency_escalation_amortization_and_head
        """
        project = _pad_filed_project(project_name="Granite Gorge", installed_capacity_mw=30.0)

        escalated = new_measure(
            project["id"],
            measure_name="Escalated ladder",
            resource_category="FISH_PASSAGE",
            source="LICENSEE_PROPOSED",
            capital_cost_usd=1200000.00,
            annual_om_cost_usd=45000.00,
            construction_start_year=2029,
            implementation_months=18,
            flow_release_cfs=120,
            gross_head_ft=85,
            release_days=180,
        )

        assert_measure_costs(
            escalated,
            escalated_capital_usd=1639090.50,
            annualized_capital_usd=54636.35,
            annual_cost_usd=99636.35,
            annual_generation_loss_mwh=1036.8,
        )

    def test_construction_start_in_the_pad_year_removes_escalation_only(self):
        """Building in the pre-application year drops the escalation factor while the flow proxy is unchanged.

        PRD §3.7: "`escalated_capital_usd` is `capital_cost_usd`, multiplied by one plus the contingency allowance, multiplied by 1.03 raised to the power of the escalation years — a 3 percent annual escalation compounded over the interval — and the product is rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/pme_estimate_combines_contingency_escalation_amortization_and_head
        """
        project = _pad_filed_project(project_name="Granite Gorge", installed_capacity_mw=30.0)

        escalated = new_measure(
            project["id"],
            measure_name="Escalated ladder",
            resource_category="FISH_PASSAGE",
            source="LICENSEE_PROPOSED",
            capital_cost_usd=1200000.00,
            annual_om_cost_usd=45000.00,
            construction_start_year=2029,
            implementation_months=18,
            flow_release_cfs=120,
            gross_head_ft=85,
            release_days=180,
        )
        immediate = new_measure(
            project["id"],
            measure_name="Immediate ladder",
            resource_category="FISH_PASSAGE",
            source="LICENSEE_PROPOSED",
            capital_cost_usd=1200000.00,
            annual_om_cost_usd=45000.00,
            construction_start_year=2026,
            implementation_months=18,
            flow_release_cfs=120,
            gross_head_ft=85,
            release_days=180,
        )

        assert_measure_costs(
            immediate,
            escalated_capital_usd=1500000.00,
            annualized_capital_usd=50000.00,
            annual_cost_usd=95000.00,
            annual_generation_loss_mwh=1036.8,
        )
        assert immediate["annual_generation_loss_mwh"] == pytest.approx(
            escalated["annual_generation_loss_mwh"], abs=0.05
        )
        after = read_project(project["id"])
        assert after["total_pme_annual_cost_usd"] == pytest.approx(194636.35, abs=0.01)
        assert after["total_generation_loss_mwh"] == pytest.approx(2073.6, abs=0.05)


class TestAdministrativeChargeTier:
    def test_tier_is_keyed_on_the_measure_cost_total_and_not_on_the_burden_total(self):
        """Two measures totalling 495000.00 draw the 2 percent tier for a charge of 9900.00.

        PRD §3.7: "The administrative charge tier is selected by comparing the step-1 total and nothing else — the charge never re-enters its own tier lookup."
        PRD §3.7: "A `total_pme_annual_cost_usd` of 500,000.00 or less attracts a rate of 2 percent; a total above 500,000.00 but not above 2,000,000.00 attracts 3.5 percent; a total above 2,000,000.00 attracts 5 percent."

        Design: Difficulty/combinatorial_formula/admin_charge_tier_keyed_on_pre_charge_pme_cost_only
        """
        project = _pad_filed_project(
            project_name="Tier Boundary Falls", installed_capacity_mw=20.0
        )
        recreation = new_measure(
            project["id"],
            measure_name="Boat launch rebuild",
            resource_category="RECREATION",
            source="AGENCY_PRESCRIPTION",
            capital_cost_usd=1500000.00,
            annual_om_cost_usd=0.00,
            construction_start_year=2026,
            implementation_months=12,
            flow_release_cfs=0,
            gross_head_ft=50,
            release_days=0,
        )
        cultural = new_measure(
            project["id"],
            measure_name="Archaeological monitoring",
            resource_category="CULTURAL",
            source="AGENCY_PRESCRIPTION",
            capital_cost_usd=2960000.00,
            annual_om_cost_usd=0.00,
            construction_start_year=2026,
            implementation_months=6,
            flow_release_cfs=0,
            gross_head_ft=50,
            release_days=0,
        )

        assert_measure_costs(
            recreation, annual_cost_usd=125000.00, annual_generation_loss_mwh=0.0
        )
        assert_measure_costs(
            cultural,
            escalated_capital_usd=3700000.00,
            annualized_capital_usd=370000.00,
            annual_cost_usd=370000.00,
        )
        after = read_project(project["id"])
        assert after["total_pme_annual_cost_usd"] == pytest.approx(495000.00, abs=0.01)
        assert after["administrative_annual_charge_usd"] == pytest.approx(9900.00, abs=0.01)

    def test_burden_total_above_the_tier_boundary_does_not_reselect_the_rate(self):
        """The burden total of 504900.00 sits above 500000.00 yet the charge stays on the 2 percent tier.

        PRD §3.7: "`total_annual_burden_usd` is then `total_pme_annual_cost_usd` plus `administrative_annual_charge_usd` plus that energy value."

        Design: Difficulty/combinatorial_formula/admin_charge_tier_keyed_on_pre_charge_pme_cost_only
        """
        project = _pad_filed_project(
            project_name="Tier Boundary Falls", installed_capacity_mw=20.0
        )
        new_measure(
            project["id"],
            measure_name="Boat launch rebuild",
            resource_category="RECREATION",
            source="AGENCY_PRESCRIPTION",
            capital_cost_usd=1500000.00,
            annual_om_cost_usd=0.00,
            construction_start_year=2026,
            implementation_months=12,
            flow_release_cfs=0,
            gross_head_ft=50,
            release_days=0,
        )
        new_measure(
            project["id"],
            measure_name="Archaeological monitoring",
            resource_category="CULTURAL",
            source="AGENCY_PRESCRIPTION",
            capital_cost_usd=2960000.00,
            annual_om_cost_usd=0.00,
            construction_start_year=2026,
            implementation_months=6,
            flow_release_cfs=0,
            gross_head_ft=50,
            release_days=0,
        )

        after = read_project(project["id"])

        assert_ledger_matches(
            after,
            total_pme_annual_cost_usd=495000.00,
            total_generation_loss_mwh=0.0,
            administrative_annual_charge_usd=9900.00,
            total_annual_burden_usd=504900.00,
            burden_ratio_pct=4.81,
        )
        assert after["economically_infeasible"] is False


class TestBurdenRatioFeasibilityBoundary:
    def test_ratio_of_exactly_fifteen_percent_makes_the_project_infeasible(self):
        """A definitive estimate landing the ratio on exactly 15.00 trips the infeasibility flag.

        PRD §3.7: "`economically_infeasible` is true when `burden_ratio_pct` has reached 15.00 or more, and false below it."
        PRD §3.7: "At step 4, `total_annual_burden_usd` is 210,102.94 plus 4,202.06 plus 415,695.00, or exactly 630,000.00."

        Design: Difficulty/boundary_precision_check/burden_ratio_exactly_at_limit_is_infeasible_and_one_mwh_more_is_not
        """
        project = _pad_filed_project(
            project_name="Exact Limit Dam",
            installed_capacity_mw=20.0,
            base_annual_generation_mwh=100000,
        )
        measure = new_measure(
            project["id"],
            measure_name="Cold water release structure",
            resource_category="WATER_QUALITY",
            source="AGENCY_PRESCRIPTION",
            capital_cost_usd=1000000.00,
            annual_om_cost_usd=155102.94,
            construction_start_year=2026,
            implementation_months=12,
            flow_release_cfs=250,
            gross_head_ft=100,
            release_days=229,
        )
        before = read_project(project["id"])
        assert before["burden_ratio_pct"] == pytest.approx(8.03, abs=0.01)
        assert before["economically_infeasible"] is False
        assert_postures(before, regulatory_posture="OPEN")

        switched = record_definitive_estimate(measure["id"], user_id=U_LICENSEE_B)
        at_boundary = read_project(project["id"])

        assert_measure_costs(
            switched, annual_cost_usd=210102.94, annual_generation_loss_mwh=9897.5
        )
        assert_ledger_matches(
            at_boundary,
            total_pme_annual_cost_usd=210102.94,
            total_generation_loss_mwh=9897.5,
            administrative_annual_charge_usd=4202.06,
            total_annual_burden_usd=630000.00,
            burden_ratio_pct=15.00,
        )
        assert at_boundary["economically_infeasible"] is True
        assert_postures(at_boundary, regulatory_posture="RESTRICTED")

    def test_raising_the_generation_baseline_clears_the_same_burden(self):
        """A larger generation denominator moves the identical 630000.00 burden to a feasible 12.50.

        PRD §3.7: "With `base_annual_generation_mwh` of 120,000 instead, the gross revenue is 5,040,000.00, the ratio is 12.50, and the project remains feasible."

        Design: Difficulty/boundary_precision_check/burden_ratio_exactly_at_limit_is_infeasible_and_one_mwh_more_is_not
        """
        project = _pad_filed_project(
            project_name="Exact Limit Dam",
            installed_capacity_mw=20.0,
            base_annual_generation_mwh=100000,
        )
        measure = new_measure(
            project["id"],
            measure_name="Cold water release structure",
            resource_category="WATER_QUALITY",
            source="AGENCY_PRESCRIPTION",
            capital_cost_usd=1000000.00,
            annual_om_cost_usd=155102.94,
            construction_start_year=2026,
            implementation_months=12,
            flow_release_cfs=250,
            gross_head_ft=100,
            release_days=229,
        )
        record_definitive_estimate(measure["id"], user_id=U_LICENSEE_B)

        amended = patch_project(project["id"], base_annual_generation_mwh=120000)

        assert_ledger_matches(
            amended,
            total_pme_annual_cost_usd=210102.94,
            total_generation_loss_mwh=9897.5,
            administrative_annual_charge_usd=4202.06,
            total_annual_burden_usd=630000.00,
            burden_ratio_pct=12.50,
        )
        assert amended["economically_infeasible"] is False
        assert_postures(amended, regulatory_posture="OPEN")
        assert read_measure(measure["id"])["cost_estimate_variant"] == "DEFINITIVE"
