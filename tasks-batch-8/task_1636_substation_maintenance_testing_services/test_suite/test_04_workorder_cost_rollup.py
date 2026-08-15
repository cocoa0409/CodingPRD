"""Work-order cost rollup (PRD §3.6, §2.5): pinned per-line rounding order and
pinned tier evaluation order (subtotal -> tier -> fee -> total)."""
from test_helpers import (
    api_client,
    assert_money_equals,
    complete_work_order,
    setup_work_order_in_progress,
)


def _setup_in_progress(window_date: str, clock_ts: str) -> dict:
    return setup_work_order_in_progress(
        f"{window_date}T08:00:00Z", f"{window_date}T16:00:00Z", clock_ts,
        estimated_hours=4,
    )


class TestWorkOrderCostRounding:
    def test_per_line_rounding_before_summation(self):
        """PRD §2.5: "Work-order costing rounds each individual labor and parts
        line to 2 decimal places half-up before any summation, and only then
        sums the rounded lines into `cost_subtotal`; the mobilization fee is
        then computed from that subtotal and itself rounded to 2 decimal places
        half-up. Summing first and rounding once at the end produces different
        cents and is forbidden."

        Design: Difficulty/combinatorial_formula/workorder_cost_rounding_mode_b
        """
        ctx = _setup_in_progress("2026-08-10", "2026-08-10T09:00:00Z")
        completed = complete_work_order(
            ctx["work_order"]["id"], ctx["tech_headers"],
            labor_lines=[
                {"hours": 2.5, "rate_per_hour": 133.33},
                {"hours": 1.0, "rate_per_hour": 88.885},
            ],
            parts_lines=[{"quantity": 3, "unit_price": 19.99}],
        )
        # Per line: 333.325 -> 333.33, 88.885 -> 88.89, 59.97 -> 59.97.
        # Sum-then-round would yield 482.18; per-line-then-sum yields 482.19.
        assert_money_equals(completed["cost_subtotal"], "482.19")

    def test_fee_and_total_derive_from_rounded_subtotal(self):
        """PRD §3.6: "The mobilization tier is then keyed on `cost_subtotal` —
        never on `total_cost`: a subtotal of at least 500.00 earns a fee rate
        of 0.04, anything below earns 0.05. `mobilization_fee` is the fee rate
        multiplied by `cost_subtotal`, rounded half-up to 2 decimal places.
        `total_cost` is `cost_subtotal` plus `mobilization_fee`."

        Design: Difficulty/combinatorial_formula/workorder_cost_rounding_mode_b
        """
        ctx = _setup_in_progress("2026-08-10", "2026-08-10T09:00:00Z")
        completed = complete_work_order(
            ctx["work_order"]["id"], ctx["tech_headers"],
            labor_lines=[
                {"hours": 2.5, "rate_per_hour": 133.33},
                {"hours": 1.0, "rate_per_hour": 88.885},
            ],
            parts_lines=[{"quantity": 3, "unit_price": 19.99}],
        )
        # Subtotal 482.19 < 500 -> 5% -> 24.1095 -> 24.11; total 506.30
        # (the forbidden sum-then-round order would produce 506.29).
        assert_money_equals(completed["mobilization_fee"], "24.11")
        assert_money_equals(completed["total_cost"], "506.30")


class TestFeeTierEvaluationOrder:
    def test_subtotal_at_threshold_earns_low_fee_rate(self):
        """PRD §3.6: "The mobilization tier is then keyed on `cost_subtotal` —
        never on `total_cost`: a subtotal of at least 500.00 earns a fee rate
        of 0.04, anything below earns 0.05."

        Design: Difficulty/combinatorial_formula/workorder_fee_tier_evaluation_order_mode_c
        """
        ctx = _setup_in_progress("2026-08-11", "2026-08-11T09:00:00Z")
        completed = complete_work_order(
            ctx["work_order"]["id"], ctx["tech_headers"],
            labor_lines=[{"hours": 10.0, "rate_per_hour": 44.00}],
            parts_lines=[{"quantity": 2, "unit_price": 30.00}],
        )
        # Lines: 440.00 + 60.00 = 500.00 exactly; 500.00 >= 500.00 -> 4% tier.
        assert_money_equals(completed["cost_subtotal"], "500.00")
        assert_money_equals(completed["mobilization_fee"], "20.00")

    def test_total_at_threshold_uses_subtotal_keyed_tier(self):
        """PRD §3.6: "The mobilization tier is then keyed on `cost_subtotal` —
        never on `total_cost`: a subtotal of at least 500.00 earns a fee rate
        of 0.04, anything below earns 0.05. `mobilization_fee` is the fee rate
        multiplied by `cost_subtotal`, rounded half-up to 2 decimal places.
        `total_cost` is `cost_subtotal` plus `mobilization_fee`."

        Design: Difficulty/combinatorial_formula/workorder_fee_tier_evaluation_order_mode_c
        """
        ctx = _setup_in_progress("2026-08-11", "2026-08-11T09:00:00Z")
        completed = complete_work_order(
            ctx["work_order"]["id"], ctx["tech_headers"],
            labor_lines=[{"hours": 10.0, "rate_per_hour": 44.00}],
            parts_lines=[{"quantity": 2, "unit_price": 30.00}],
        )
        # Tier keyed on the subtotal: total is 500.00 + 20.00 = 520.00,
        # NOT the 525.00 the 5% reading would produce.
        assert_money_equals(completed["total_cost"], "520.00")
