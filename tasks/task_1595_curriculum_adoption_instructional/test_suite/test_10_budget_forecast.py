"""The replacement budget forecast: ROLLING vs STRAIGHT_LINE variants, the
pinned evaluation order, and the contingency tier boundaries."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_cycle,
    create_framework,
    setup_cycle_active,
    validate_success,
)

DIRECTOR = TEST_USERS["curriculum_director_headers"]


def _forecast(api, cycle_id, variant):
    return validate_success(api.get_budget_forecast(cycle_id, DIRECTOR,
                                                    variant=variant))


class TestRollingVsStraightLine:
    @staticmethod
    def _setup(api):
        """Cycle H (MATHEMATICS 2026) fully driven to ACTIVE with
        expended_total 1000.00; cycle C (SCIENCE 2028, enrollment 100) fresh."""
        ctx_h = setup_cycle_active(
            appropriation=2000, quote_unit_price=10.00, po_print_quantity=100)
        assert ctx_h["ledger"]["expended_total"] == pytest.approx(1000.00,
                                                                  abs=0.01)
        fw_s = create_framework(code="FW-SCI-K5", subject_area="SCIENCE")
        cycle_c = create_cycle(fw_s["id"], subject_area="SCIENCE",
                               school_year_start=2028, district_enrollment=100)
        return ctx_h, cycle_c

    def test_rolling_variant_enrollment_driven(self, api):
        """PRD §3.10: "Under `ROLLING`, the model is forward-looking and
        ignores historical spend: the base is the cycle's
        `district_enrollment` multiplied by a per-pupil rate of 120.00
        dollars, by a replacement ratio of 0.20, and by a five-year horizon,
        rounded half-up to two decimal places."
        PRD §3.10: "a base below 100,000.00 dollars carries a rate of 0.05"

        Design: Difficulty/dual_variant_calc/forecast_rolling_vs_straight_line
        """
        _, cycle_c = self._setup(api)
        forecast = _forecast(api, cycle_c["id"], "ROLLING")
        # 100 * 120.00 * 0.20 * 5 = 12000.00; tier 0.05; total 12600.00.
        assert forecast["base_amount"] == pytest.approx(12000.00, abs=0.01)
        assert forecast["contingency_rate"] == pytest.approx(0.05, abs=0.001)
        assert forecast["forecast_total"] == pytest.approx(12600.00, abs=0.01)

    def test_straight_line_variant_history_driven(self, api):
        """PRD §3.10: "Under `STRAIGHT_LINE`, the model is chronological: it
        gathers the `expended_total` of the three most recent other cycles in
        `ACTIVE` or `SUNSET` status — the queried cycle is excluded even when
        it qualifies — ordered by `school_year_start` descending with ties
        broken by `created_at` ascending, never by `id`; when that history is
        empty the base is 0.00, and otherwise the base is the mean of those
        expenditures multiplied by 1.03 raised to the fifth power"

        Design: Difficulty/dual_variant_calc/forecast_rolling_vs_straight_line
        """
        _, cycle_c = self._setup(api)
        forecast = _forecast(api, cycle_c["id"], "STRAIGHT_LINE")
        # History is [1000.00] (the ACTIVE cycle H): 1000.00 * 1.03^5 =
        # 1159.2740... -> 1159.27; tier 0.05; total 1217.23.
        assert forecast["base_amount"] == pytest.approx(1159.27, abs=0.01)
        assert forecast["contingency_rate"] == pytest.approx(0.05, abs=0.001)
        assert forecast["forecast_total"] == pytest.approx(1217.23, abs=0.01)

        rolling = _forecast(api, cycle_c["id"], "ROLLING")
        assert rolling["forecast_total"] != forecast["forecast_total"], (
            "the two variants answer different questions on identical state")


class TestContingencyTierOrder:
    def test_rolling_base_rounded_before_tier_selection(self, api):
        """PRD §3.10: "first the base amount is computed and rounded half-up
        to two decimal places; second the contingency rate is selected from
        the tier table keyed on that rounded base; third the forecast total
        is the base multiplied by one plus the contingency rate, rounded
        half-up to two decimal places."
        PRD §3.10: "a base of at least 100,000.00 and below 500,000.00
        carries 0.08"

        Design: Difficulty/combinatorial_formula/forecast_contingency_tier_order
        """
        fw = create_framework()
        cycle = create_cycle(fw["id"], district_enrollment=4000)
        forecast = _forecast(api, cycle["id"], "ROLLING")
        # 4000 * 120.00 * 0.20 * 5 = 480000.00 -> tier 0.08 -> 518400.00.
        assert forecast["base_amount"] == pytest.approx(480000.00, abs=0.01)
        assert forecast["contingency_rate"] == pytest.approx(0.08, abs=0.001)
        assert forecast["forecast_total"] == pytest.approx(518400.00, abs=0.01)

    def test_straight_line_empty_history_zero_base(self, api):
        """PRD §3.10: "when that history is empty the base is 0.00"
        PRD §3.10: "a base below 100,000.00 dollars carries a rate of 0.05"

        Design: Difficulty/combinatorial_formula/forecast_contingency_tier_order
        """
        fw = create_framework()
        cycle = create_cycle(fw["id"], district_enrollment=4000)
        forecast = _forecast(api, cycle["id"], "STRAIGHT_LINE")
        # No other cycles in ACTIVE/SUNSET: empty history.
        assert forecast["base_amount"] == pytest.approx(0.00, abs=0.01)
        assert forecast["contingency_rate"] == pytest.approx(0.05, abs=0.001)
        assert forecast["forecast_total"] == pytest.approx(0.00, abs=0.01)


class TestTierBoundaryBracket:
    def test_forecast_tier_boundary_bracket(self, api):
        """PRD §3.10: "a base of at least 100,000.00 and below 500,000.00
        carries 0.08; a base of at least 500,000.00 carries 0.12."

        Design: Corner/calculations/forecast_tier_boundary_bracket
        """
        fw = create_framework()
        cycle_a = create_cycle(fw["id"], district_enrollment=4166,
                               school_year_start=2027)
        cycle_b = create_cycle(fw["id"], district_enrollment=4167,
                               school_year_start=2028)

        # 4166 * 120 * 0.2 * 5 = 499920.00 -> still the 0.08 tier.
        forecast_a = _forecast(api, cycle_a["id"], "ROLLING")
        assert forecast_a["base_amount"] == pytest.approx(499920.00, abs=0.01)
        assert forecast_a["contingency_rate"] == pytest.approx(0.08, abs=0.001)
        assert forecast_a["forecast_total"] == pytest.approx(539913.60,
                                                             abs=0.01)

        # 4167 * 120 * 0.2 * 5 = 500040.00 -> crosses into the 0.12 tier.
        forecast_b = _forecast(api, cycle_b["id"], "ROLLING")
        assert forecast_b["base_amount"] == pytest.approx(500040.00, abs=0.01)
        assert forecast_b["contingency_rate"] == pytest.approx(0.12, abs=0.001)
        assert forecast_b["forecast_total"] == pytest.approx(560044.80,
                                                             abs=0.01)
