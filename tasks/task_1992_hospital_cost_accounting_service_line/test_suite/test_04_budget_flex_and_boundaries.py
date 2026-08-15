"""Budget-period flex tiers, boundaries, and static-vs-flexed variants (PRD §3.5)."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_budget_period,
    create_budget_period,
    get_success_data,
    setup_card_rvu,
    setup_case_with_lines,
    setup_ortho_tdabc,
    setup_posted_card_case,
    post_case,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]
CA = TEST_USERS["cost_analyst_headers"]


class TestStaticVsFlexedVariant:
    def test_static_vs_flexed_overhead_budget_diverge(self, api):
        """PRD §3.5: "A static view exists alongside the flexed one: when variance
        is reported against the static budget without flexing,
        `static_budget_amount` itself serves as the overhead baseline and no
        tiering applies, so the same period can legitimately report a different
        budget under the two views."
        PRD §3.5: "when it is above 20,000 the tier rate is 0.35."

        Design: Difficulty/dual_variant_calc/static_vs_flexed_overhead_budget_diverge
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        bp = scenario["budget_period"]
        # LAB 4 * 2500 = 10000.00; RAD 6 * 3000 = 18000.00 -> pre-overhead 28000.00
        setup_posted_card_case(scenario, lab_qty=4, rad_qty=6)

        fetched = validate_success(api.get_budget_period(bp["id"], FC))
        assert_budget_period(fetched)
        assert fetched["static_budget_amount"] == pytest.approx(7000.00, abs=0.005)
        assert fetched["actual_indirect_volume"] == pytest.approx(28000.00, abs=0.005)
        assert fetched["flexed_overhead"] == pytest.approx(9800.00, abs=0.005)
        assert fetched["variance_amount"] == pytest.approx(2800.00, abs=0.005)
        assert fetched["variance_direction"] == "UNFAVORABLE"
        assert fetched["static_budget_amount"] != fetched["flexed_overhead"]

    def test_static_baseline_remains_input_value_after_flex(self, api):
        """PRD §3.5: "The `flexed_overhead` is the tier rate multiplied by
        `actual_indirect_volume`, rounded half-up to two decimal places. The
        `variance_amount` is `flexed_overhead` minus `static_budget_amount`, and
        the `variance_direction` reads `FAVORABLE` when the variance is negative,
        `ON_BUDGET` when it is exactly zero, and `UNFAVORABLE` when it is
        positive."

        Design: Difficulty/dual_variant_calc/static_vs_flexed_overhead_budget_diverge
        """
        scenario = setup_card_rvu(period="2026-08", with_budget_period=True,
                                  static_budget_amount=7000.00)
        setup_posted_card_case(scenario, lab_qty=4, rad_qty=6)

        fetched = validate_success(
            api.get_budget_period(scenario["budget_period"]["id"], FC)
        )
        # static view untouched by the flex computation
        assert fetched["static_budget_amount"] == pytest.approx(7000.00, abs=0.005)
        # flex = 0.35 * 28000.00 = 9800.00; variance = 9800 - 7000 = +2800 -> UNFAVORABLE
        assert fetched["flexed_overhead"] == pytest.approx(9800.00, abs=0.005)
        assert fetched["variance_amount"] == pytest.approx(
            fetched["flexed_overhead"] - fetched["static_budget_amount"], abs=0.005
        )
        assert fetched["variance_direction"] == "UNFAVORABLE"


class TestVolumeTierSelection:
    def test_flex_budget_volume_tier_selection(self, api):
        """PRD §3.5: "When `actual_indirect_volume` is at or below 6,000 the tier
        rate is 0.20; when it is above 6,000 and at or below 20,000 the tier rate
        is 0.30; when it is above 20,000 the tier rate is 0.35."

        Design: Difficulty/combinatorial_formula/flex_budget_volume_tier_selection
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00, period="2026-09")
        bp = create_budget_period(cost_center_id=scenario["cc_overhead"]["id"],
                                  period="2026-09", static_budget_amount=7000.00)

        # Case X: 13000 min * 1.50/min = 19500.00 activity -> tier 0.30
        case_x = setup_case_with_lines(scenario, [13000], case_period="2026-09",
                                       expected_reimbursement=40000.00)
        post_case(case_x["id"], scenario["model_version"])
        after_x = validate_success(api.get_budget_period(bp["id"], FC))
        assert after_x["actual_indirect_volume"] == pytest.approx(19500.00, abs=0.005)
        assert after_x["flexed_overhead"] == pytest.approx(5850.00, abs=0.005)
        assert after_x["variance_amount"] == pytest.approx(-1150.00, abs=0.005)
        assert after_x["variance_direction"] == "FAVORABLE"

        # Case Y: 334 min * 1.50 = 501.00 -> cumulative 20001.00 -> tier 0.35
        case_y = setup_case_with_lines(scenario, [334], case_period="2026-09",
                                       expected_reimbursement=40000.00)
        post_case(case_y["id"], scenario["model_version"])
        after_y = validate_success(api.get_budget_period(bp["id"], FC))
        assert after_y["actual_indirect_volume"] == pytest.approx(20001.00, abs=0.005)
        assert after_y["flexed_overhead"] == pytest.approx(7000.35, abs=0.005)
        assert after_y["variance_amount"] == pytest.approx(0.35, abs=0.005)
        assert after_y["variance_direction"] == "UNFAVORABLE"

    def test_flex_tier_one_boundary_region(self, api):
        """PRD §3.5: "Boundary inclusion is exact: a volume of exactly 6,000.00
        flexes at the 0.20 rate and a volume of exactly 20,000.00 at the 0.30
        rate."

        Design: Difficulty/combinatorial_formula/flex_budget_volume_tier_selection
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00, period="2026-11")
        bp = create_budget_period(cost_center_id=scenario["cc_overhead"]["id"],
                                  period="2026-11", static_budget_amount=7000.00)

        # 4000 min * 1.50 = 6000.00 exactly -> 0.20 tier -> flex 1200.00
        case = setup_case_with_lines(scenario, [4000], case_period="2026-11",
                                     expected_reimbursement=40000.00)
        post_case(case["id"], scenario["model_version"])
        fetched = validate_success(api.get_budget_period(bp["id"], FC))
        assert fetched["actual_indirect_volume"] == pytest.approx(6000.00, abs=0.005)
        assert fetched["flexed_overhead"] == pytest.approx(1200.00, abs=0.005)
        assert fetched["variance_amount"] == pytest.approx(-5800.00, abs=0.005)
        assert fetched["variance_direction"] == "FAVORABLE"


class TestTierBoundaryPrecision:
    def test_flex_tier_boundary_exactly_20000_uses_030(self, api):
        """PRD §3.5: "Boundary inclusion is exact: a volume of exactly 6,000.00
        flexes at the 0.20 rate and a volume of exactly 20,000.00 at the 0.30
        rate."

        Design: Difficulty/boundary_precision_check/flex_tier_boundary_exactly_20000_uses_030
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00, period="2026-10")
        bp = create_budget_period(cost_center_id=scenario["cc_overhead"]["id"],
                                  period="2026-10", static_budget_amount=7000.00)

        # qty 13333.33 * 1.50 = 19999.995 -> per-line round-half-up -> 20000.00
        case = setup_case_with_lines(scenario, [13333.33], case_period="2026-10",
                                     expected_reimbursement=40000.00)
        post_case(case["id"], scenario["model_version"])

        fetched = validate_success(api.get_budget_period(bp["id"], FC))
        assert fetched["actual_indirect_volume"] == pytest.approx(20000.00, abs=0.005)
        # 20000.00 is <= 20000 -> 0.30 tier, not 0.35
        assert fetched["flexed_overhead"] == pytest.approx(6000.00, abs=0.005)

    def test_flex_tier_one_unit_above_20000_uses_035(self, api):
        """PRD §3.5: "when it is above 6,000 and at or below 20,000 the tier rate
        is 0.30; when it is above 20,000 the tier rate is 0.35."

        Design: Difficulty/boundary_precision_check/flex_tier_boundary_exactly_20000_uses_030
        """
        scenario = setup_ortho_tdabc(rate_factor=1.00, period="2026-12")
        bp = create_budget_period(cost_center_id=scenario["cc_overhead"]["id"],
                                  period="2026-12", static_budget_amount=7000.00)

        # Two cases: 13000 min (19500.00) + 334 min (501.00) = 20001.00 -> 0.35 tier
        case_a = setup_case_with_lines(scenario, [13000], case_period="2026-12",
                                       expected_reimbursement=40000.00)
        post_case(case_a["id"], scenario["model_version"])
        case_b = setup_case_with_lines(scenario, [334], case_period="2026-12",
                                       expected_reimbursement=40000.00)
        post_case(case_b["id"], scenario["model_version"])

        fetched = validate_success(api.get_budget_period(bp["id"], FC))
        assert fetched["actual_indirect_volume"] == pytest.approx(20001.00, abs=0.005)
        assert fetched["flexed_overhead"] == pytest.approx(7000.35, abs=0.005)
