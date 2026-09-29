"""
Accuracy variants, per-line variance valuation and the tolerance boundary.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_buckets_sum_to, assert_pct
from test_helpers.test_users import ANALYST, CONTROLLER, SUPERVISOR


class TestShrinkAttributionVariants:
    def test_provisional_parks_the_unresolved_amount_and_final_drops_it(self, api):
        """
        The two attribution variants diverge on the same rows.

        "with one `CLOSED` `THEFT` investigation of 6633 cents, one `IN_REVIEW`
        investigation of 32250 cents and `sales_at_cost_cents` of 5000000, the
        provisional view is a theft bucket of 6633, `unresolved_cents` of 32250,
        a total of 38883 and a rate of 78 basis points, while the final view is
        a theft bucket of 6633, `unresolved_cents` of 0, a total of 6633 and a
        rate of 13 basis points."

        Design: Difficulty/dual_variant_calc/shrink_attribution_provisional_vs_final_diverge
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line_a = fx.add_line(api, world["task_id"], world["item_id"], 105)
        line_b = fx.add_line(api, world["task_id"], world["item_b_id"], 62)
        fx.submit_task(api, world["task_id"])

        inv_a = fx.investigation_for_line(api, line_a["id"])
        inv_b = fx.investigation_for_line(api, line_b["id"])
        fx.drive_to_closed(api, inv_a["id"], "THEFT")
        fx.drive_to_in_review(api, inv_b["id"])

        attribution = validate_success(
            api.get_shrink_period_attribution(world["shrink_period_id"], CONTROLLER)
        )

        assert attribution["theft_cents"] == 6633
        assert attribution["unresolved_cents"] == 32250
        assert attribution["damage_cents"] == 0
        assert attribution["process_error_cents"] == 0
        assert attribution["vendor_shortage_cents"] == 0
        assert attribution["provisional_total_shrink_cents"] == 38883
        assert attribution["final_total_shrink_cents"] == 6633
        assert attribution["provisional_shrink_rate_bps"] == 78
        assert attribution["final_shrink_rate_bps"] == 13
        assert attribution["total_attributable_variance_cents"] == 38883
        assert_buckets_sum_to(attribution, 38883)

        assert fx.read_investigation(api, inv_b["id"])["status"] == "IN_REVIEW"

    def test_period_status_open_keeps_the_stored_rate_on_the_provisional_total(self, api):
        """
        A period that has not been finally closed reports the provisional rate.

        "the active total is `final_total_shrink_cents` when the period's
        `status` is `FINAL_CLOSED` and `provisional_total_shrink_cents` in every
        other status."

        Design: Difficulty/dual_variant_calc/shrink_attribution_provisional_vs_final_diverge
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line_a = fx.add_line(api, world["task_id"], world["item_id"], 105)
        line_b = fx.add_line(api, world["task_id"], world["item_b_id"], 62)
        fx.submit_task(api, world["task_id"])

        inv_a = fx.investigation_for_line(api, line_a["id"])
        inv_b = fx.investigation_for_line(api, line_b["id"])
        fx.drive_to_closed(api, inv_a["id"], "THEFT")
        fx.drive_to_in_review(api, inv_b["id"])

        period = validate_success(
            api.get_shrink_period(world["shrink_period_id"], CONTROLLER)
        )
        assert period["status"] == "OPEN"
        assert period["provisional_total_shrink_cents"] == 38883
        assert period["final_total_shrink_cents"] == 6633
        assert period["shrink_rate_bps"] == 78


class TestStockAccuracyVariants:
    def test_unit_and_value_accuracy_diverge_by_the_landed_cost_uplift(self, api):
        """
        One count of one position scores differently on the two variants.

        "the unit variant is blind to the landed-cost uplift that the value
        variant's numerator carries while its denominator remains pure book
        cost, so whenever the category's `landed_cost_uplift_bps` is greater
        than 0 an identical unit discrepancy scores strictly lower on the value
        variant than on the unit variant."

        Design: Difficulty/dual_variant_calc/stock_accuracy_unit_vs_value_diverge
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)

        accuracy = validate_success(
            api.get_stock_position_accuracy(world["position_id"], ANALYST)
        )

        assert accuracy["last_count_system_units"] == 100
        assert accuracy["last_count_book_value_cents"] == 123400
        assert accuracy["last_variance_units"] == 5
        assert accuracy["last_variance_value_cents"] == 6633
        assert_pct(accuracy["unit_accuracy_pct"], 95.00)
        assert_pct(accuracy["value_accuracy_pct"], 94.62)
        assert accuracy["unit_accuracy_pct"] != accuracy["value_accuracy_pct"]
        assert accuracy["value_accuracy_pct"] < accuracy["unit_accuracy_pct"]

    def test_the_value_variant_is_the_one_the_category_floor_consults(self, api):
        """
        The gate reads the value variant against the category floor.

        "Note that the value-basis variant, not the unit-basis variant, is the
        one the accuracy floor consults."

        Design: Difficulty/dual_variant_calc/stock_accuracy_unit_vs_value_diverge
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)

        accuracy = validate_success(
            api.get_stock_position_accuracy(world["position_id"], ANALYST)
        )
        assert_pct(accuracy["min_accuracy_pct"], 97.00)
        assert accuracy["promising_state"] == "RESTRICTED"

        position = fx.read_position(api, world["position_id"])
        assert_pct(position["unit_accuracy_pct"], 95.00)
        assert_pct(position["value_accuracy_pct"], 94.62)
        assert position["promising_state"] == "RESTRICTED"


class TestVarianceValuationRoundingOrder:
    def test_each_line_rounds_before_the_task_total_sums_them(self, api):
        """
        The rollup adds already-rounded line values.

        "a line of 5 units at 1234 cents under a 750-basis-point uplift values
        at 6632.750 and rounds to 6633, while a line of 3 units at 2500 cents
        under the same uplift values at 8062.500 and rounds to 8063; rounding
        per line and then summing gives 14696, whereas summing first and
        rounding once would give 14695. Only 14696 is correct."

        Design: Difficulty/combinatorial_formula/variance_valuation_round_per_line_then_sum
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line_a = fx.add_line(api, world["task_id"], world["item_id"], 105)
        line_b = fx.add_line(api, world["task_id"], world["item_b_id"], 53)

        submitted = validate_success(api.submit_count_task(world["task_id"], ANALYST))

        assert submitted["status"] == "COUNTED"
        assert submitted["in_scope_position_count"] == 2
        assert submitted["counted_line_count"] == 2
        assert_pct(submitted["coverage_pct"], 100.00)
        assert submitted["variance_line_count"] == 2
        assert submitted["total_variance_value_cents"] == 14696
        assert submitted["total_variance_value_cents"] != 14695

        stored_a = validate_success(api.get_count_line(line_a["id"], ANALYST))
        assert stored_a["variance_units"] == 5
        assert stored_a["variance_value_cents"] == 6633
        assert stored_a["within_tolerance"] is False

        stored_b = validate_success(api.get_count_line(line_b["id"], ANALYST))
        assert stored_b["variance_units"] == 3
        assert stored_b["variance_value_cents"] == 8063
        assert stored_b["within_tolerance"] is False

    def test_the_period_receives_the_per_line_rounded_total(self, api):
        """
        The two opened investigations carry the same already-rounded amounts.

        "Each opened investigation immediately enlarges the covering period's
        `unresolved_cents` by its `variance_value_cents` under the provisional
        variant of §3.8"

        Design: Difficulty/combinatorial_formula/variance_valuation_round_per_line_then_sum
        """
        world = fx.apparel_two_item_world(api, baseline_a=100, baseline_b=50)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        fx.add_line(api, world["task_id"], world["item_id"], 105)
        fx.add_line(api, world["task_id"], world["item_b_id"], 53)
        fx.submit_task(api, world["task_id"])

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["unresolved_cents"] == 14696
        assert attribution["total_attributable_variance_cents"] == 14696


class TestVarianceValueToleranceBoundary:
    def test_a_value_exactly_at_the_tolerance_is_out_of_tolerance(self, api):
        """
        The value tolerance is a strict comparison.

        "`within_tolerance` is then true when **both** of two conditions hold:
        the absolute value of `variance_units` is at most the category's
        `variance_tolerance_units`, and `variance_value_cents` is strictly less
        than the category's `variance_tolerance_value_cents`."

        Design: Difficulty/boundary_precision_check/variance_value_exactly_at_tolerance_opens_investigation
        """
        world = fx.home_reference_world(
            api, item_payload_builder=f.pan_item_payload, baseline=100
        )
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 104)

        submitted = validate_success(api.submit_count_task(world["task_id"], ANALYST))

        stored = validate_success(api.get_count_line(line["id"], ANALYST))
        assert stored["variance_units"] == 4
        assert stored["variance_value_cents"] == 6000
        assert stored["within_tolerance"] is False

        assert submitted["status"] == "COUNTED"
        assert submitted["variance_line_count"] == 1
        assert submitted["total_variance_value_cents"] == 6000

        investigation = fx.investigation_for_line(api, line["id"])
        assert investigation["status"] == "OPEN"
        assert investigation["variance_value_cents"] == 6000

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["unresolved_cents"] == 6000

    def test_one_step_below_the_value_tolerance_stays_within_tolerance(self, api):
        """
        A value under the tolerance opens nothing.

        "`variance_tolerance_value_cents`, the landed-cost variance value in
        cents at or above which a line is out of tolerance regardless of unit
        count, which must be greater than 0"

        Design: Difficulty/boundary_precision_check/variance_value_exactly_at_tolerance_opens_investigation
        """
        world = fx.home_reference_world(
            api, item_payload_builder=f.pan_item_payload, baseline=100
        )
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 103)

        submitted = validate_success(api.submit_count_task(world["task_id"], ANALYST))

        stored = validate_success(api.get_count_line(line["id"], ANALYST))
        assert stored["variance_units"] == 3
        assert stored["variance_value_cents"] == 4500
        assert stored["within_tolerance"] is True
        assert submitted["variance_line_count"] == 0

        found = validate_success(
            api.list_investigations(SUPERVISOR, {"count_line_id": line["id"]})
        )
        assert found == []

    def test_one_step_above_the_value_tolerance_is_also_out_of_tolerance(self, api):
        """
        Above the tolerance the line is out of tolerance as well.

        "If either condition fails the line is out of tolerance."

        Design: Difficulty/boundary_precision_check/variance_value_exactly_at_tolerance_opens_investigation
        """
        world = fx.home_reference_world(
            api, item_payload_builder=f.pan_item_payload, baseline=100
        )
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 105)

        fx.submit_task(api, world["task_id"])

        stored = validate_success(api.get_count_line(line["id"], ANALYST))
        assert stored["variance_units"] == 5
        assert stored["variance_value_cents"] == 7500
        assert stored["within_tolerance"] is False

        investigation = fx.investigation_for_line(api, line["id"])
        assert investigation["variance_value_cents"] == 7500
