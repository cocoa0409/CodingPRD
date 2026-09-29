"""
The arithmetic the domain pins by worked example: landed-cost line valuation,
weighted coverage, the two accuracy variants at two decimal places, the shrink
attribution input set, the tag verification conjunction, the chargeback tier
boundary and the reconciliation waterfall.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_COUNT_COVERAGE_BELOW_MIN
from test_helpers.assertions import assert_pct
from test_helpers.test_users import (
    ANALYST,
    CONTROLLER,
    SUPERVISOR,
    USER_SUPERVISOR_1,
)


class TestCountVarianceValuation:
    def test_a_one_unit_over_count_values_at_the_uplift_and_stays_in_tolerance(
        self, api
    ):
        """
        The uplift factor is applied once, per line, and rounded half up.

        "The landed-cost uplift factor for the line is 10000 plus the category's
        `landed_cost_uplift_bps`, divided by 10000. The raw line value is the
        absolute value of `variance_units`, multiplied by the SKU's
        `unit_cost_cents`, multiplied by that uplift factor. `variance_value_cents`
        is that raw value rounded half up to a whole number of cents."

        Design: Corner/calculations/count_variance_valuation_correct_result_inside_tolerance
        """
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)

        line = fx.add_line(api, world["task_id"], world["item_id"], 101)
        assert line["variance_units"] == 1
        assert line["variance_value_cents"] == 1327
        assert line["within_tolerance"] is True

        submitted = fx.submit_task(api, world["task_id"])
        assert submitted["status"] == "COUNTED"
        assert_pct(submitted["coverage_pct"], 100.00)
        assert submitted["counted_line_count"] == 1
        assert submitted["variance_line_count"] == 0
        assert submitted["total_variance_value_cents"] == 1327

        rows, meta = validate_paginated(
            api.list_investigations(SUPERVISOR, {"store_id": world["store_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_accuracy_read_reports_both_variants_of_that_one_unit(self, api):
        """
        A within-tolerance line still refreshes the frozen accuracy inputs.

        "For each line, the position it referenced receives `last_counted_at` set to
        the current logical-clock instant, `last_variance_units` set to the line's
        `variance_units`, `last_variance_value_cents` set to the line's
        `variance_value_cents`, `last_count_system_units` set to the line's
        `system_units_snapshot`, and `last_count_book_value_cents` set to that same
        snapshot multiplied by the SKU's `unit_cost_cents`."

        Design: Corner/calculations/count_variance_valuation_correct_result_inside_tolerance
        """
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        fx.add_line(api, world["task_id"], world["item_id"], 101)
        fx.submit_task(api, world["task_id"])

        accuracy = validate_success(
            api.get_stock_position_accuracy(world["position_id"], ANALYST)
        )
        assert accuracy["last_count_system_units"] == 100
        assert accuracy["last_count_book_value_cents"] == 123400
        assert accuracy["last_variance_units"] == 1
        assert accuracy["last_variance_value_cents"] == 1327
        assert_pct(accuracy["unit_accuracy_pct"], 99.00)
        assert_pct(accuracy["value_accuracy_pct"], 98.92)
        assert accuracy["promising_state"] == "PROMISABLE"


class TestWeightedCoverage:
    @staticmethod
    def _four_position_overhead_task(api):
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_shrink_period(api, world)
        items = {"TEE-001": world["item_id"]}
        positions = {"TEE-001": world["position_id"]}
        for sku, description, baseline in (
            ("TEE-002", "V-neck tee", 50),
            ("TEE-003", "Tank", 25),
            ("TEE-004", "Polo", 10),
        ):
            item = fx.create_item(
                api,
                f.item_payload(
                    world["category_id"],
                    world["vendor_id"],
                    sku=sku,
                    description=description,
                ),
            )
            position = fx.create_position(
                api, world["store_id"], item["id"], baseline=baseline
            )
            items[sku] = item["id"]
            positions[sku] = position["id"]
        fx.with_started_task(api, world, reader_mode="OVERHEAD")
        assert world["task"]["in_scope_position_count"] == 4
        world["items"] = items
        world["positions"] = positions
        world["baselines"] = {
            "TEE-001": 100,
            "TEE-002": 50,
            "TEE-003": 25,
            "TEE-004": 10,
        }
        return world

    def test_one_handheld_line_on_an_overhead_task_earns_only_half_credit(self, api):
        """
        A line read with the wrong technology halves its own contribution.

        "Each line's weight is 1.00 when its `read_mode_used` equals the task's
        `reader_mode`; 0.50 when the line was read `HANDHELD` while the task's mode
        is `OVERHEAD`; and 0.00 when the line was read `OVERHEAD` while the task's
        mode is `HANDHELD`. The effective line total is the exact decimal sum of those
        weights over every line currently attached to the task, accumulated in
        ascending line creation order. When `in_scope_position_count` is 0,
        `coverage_pct` is exactly 0.00 by rule. Otherwise `coverage_pct` is 100
        multiplied by the effective line total, divided by `in_scope_position_count`,
        rounded half up to 2 decimal places and clamped into 0.00 through 100.00
        inclusive. For instance, a task whose in-scope population is 4 and whose mode
        is `OVERHEAD` with three overhead lines and one handheld line has an effective
        total of 3.50 and therefore a coverage of 87.50, whereas four overhead lines
        give 4.00 and a coverage of 100.00."

        Design: Corner/calculations/count_coverage_pct_half_weights_wrong_reader_technology
        """
        world = self._four_position_overhead_task(api)
        for sku in ("TEE-001", "TEE-002", "TEE-003"):
            fx.add_line(
                api,
                world["task_id"],
                world["items"][sku],
                world["baselines"][sku],
                read_mode="OVERHEAD",
            )
        fx.add_line(
            api,
            world["task_id"],
            world["items"]["TEE-004"],
            world["baselines"]["TEE-004"],
            read_mode="HANDHELD",
        )

        before = fx.read_task(api, world["task_id"])
        assert before["in_scope_position_count"] == 4
        assert before["counted_line_count"] == 4
        assert_pct(before["coverage_pct"], 87.50)

        validate_error(
            api.submit_count_task(world["task_id"], ANALYST),
            ERR_COUNT_COVERAGE_BELOW_MIN,
            409,
        )

        after = fx.read_task(api, world["task_id"])
        assert after["status"] == "IN_PROGRESS"

        for sku in ("TEE-001", "TEE-002", "TEE-003", "TEE-004"):
            position = fx.read_position(api, world["positions"][sku])
            assert position["last_counted_at"] is None
            assert_pct(position["unit_accuracy_pct"], 100.00)

    def test_four_overhead_lines_reach_full_coverage_and_submit(self, api):
        """
        Reading every line with the task's own technology clears the floor.

        "The task's weighted `coverage_pct` must be at least 90.00, otherwise
        `ERR_COUNT_COVERAGE_BELOW_MIN`; note that this rejection also catches the
        case where lines do exist but every one of them earned a weight of 0.00
        because it was read with an overhead reader on a handheld task."

        Design: Corner/calculations/count_coverage_pct_half_weights_wrong_reader_technology
        """
        world = self._four_position_overhead_task(api)
        for sku in ("TEE-001", "TEE-002", "TEE-003", "TEE-004"):
            fx.add_line(
                api,
                world["task_id"],
                world["items"][sku],
                world["baselines"][sku],
                read_mode="OVERHEAD",
            )

        before = fx.read_task(api, world["task_id"])
        assert_pct(before["coverage_pct"], 100.00)

        submitted = fx.submit_task(api, world["task_id"])
        assert submitted["status"] == "COUNTED"
        assert_pct(submitted["coverage_pct"], 100.00)
        assert submitted["counted_line_count"] == 4
        assert submitted["variance_line_count"] == 0
        assert submitted["total_variance_value_cents"] == 0


class TestAccuracyPrecision:
    def test_a_one_in_three_variance_rounds_half_up_to_two_decimals(self, api):
        """
        Both variants round half up at the second decimal place.

        "The unit-basis variant works from a denominator that is the greater of
        `last_count_system_units` and 1. It takes the absolute value of
        `last_variance_units`, divides it by that denominator, subtracts the quotient
        from 1, multiplies by 100, rounds the result half up to 2 decimal places, and
        clamps it into the range 0.00 through 100.00 inclusive."

        Design: Corner/calculations/stock_accuracy_precision_two_decimals_round_half_up
        """
        world = fx.apparel_reference_world(api, baseline=3)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 4)
        assert line["variance_units"] == 1
        assert line["variance_value_cents"] == 1327
        assert line["within_tolerance"] is True

        submitted = fx.submit_task(api, world["task_id"])
        assert submitted["status"] == "COUNTED"
        assert_pct(submitted["coverage_pct"], 100.00)

        accuracy = validate_success(
            api.get_stock_position_accuracy(world["position_id"], ANALYST)
        )
        assert accuracy["last_count_system_units"] == 3
        assert accuracy["last_count_book_value_cents"] == 3702
        assert accuracy["last_variance_units"] == 1
        assert accuracy["last_variance_value_cents"] == 1327
        assert_pct(accuracy["unit_accuracy_pct"], 66.67)
        assert_pct(accuracy["value_accuracy_pct"], 64.15)

    def test_the_value_variant_alone_decides_the_accuracy_floor(self, api):
        """
        The floor is consulted on the value basis, and the store index on the unit basis.

        "The second clause yields `RESTRICTED` and matches when either of two
        conditions holds. The first is that the position's `value_accuracy_pct` is
        strictly less than the `min_accuracy_pct` of its SKU's category — a position
        whose value accuracy exactly equals the category floor remains promisable,
        because the comparison is strict."

        Design: Corner/calculations/stock_accuracy_precision_two_decimals_round_half_up
        """
        world = fx.apparel_reference_world(api, baseline=3)
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        fx.add_line(api, world["task_id"], world["item_id"], 4)
        fx.submit_task(api, world["task_id"])

        accuracy = validate_success(
            api.get_stock_position_accuracy(world["position_id"], ANALYST)
        )
        assert_pct(accuracy["min_accuracy_pct"], 97.00)
        assert accuracy["promising_state"] == "RESTRICTED"
        assert accuracy["promising_reason"]

        eligibility = fx.read_eligibility(api, world["store_id"])
        assert eligibility["total_position_count"] == 1
        assert eligibility["accuracy_index_bps"] == 6667
        assert eligibility["restricted_position_count"] == 1
        assert eligibility["blocked_position_count"] == 0
        assert eligibility["fulfillment_status"] == "SUSPENDED"


class TestAttributionInputSet:
    def test_an_approved_but_unclosed_cause_still_sits_in_unresolved(self, api):
        """
        Only a closed attribution moves money into a named bucket.

        "Crucially the money does not move yet: the amount stays in the period's
        `unresolved_cents` under the provisional variant, and attribution to a named
        bucket happens only at close. The position also remains `RESTRICTED`, because
        a `CAUSE_APPROVED` investigation is still non-terminal."

        Design: Corner/calculations/shrink_attribution_input_set_excludes_cause_approved_rows
        """
        world = fx.counted_variance_world(api, counted_units=105)
        fx.drive_to_cause_proposed(api, world["investigation_id"], "THEFT")

        approved = validate_success(
            api.approve_cause(world["investigation_id"], SUPERVISOR)
        )
        assert approved["status"] == "CAUSE_APPROVED"
        assert approved["approved_root_cause"] == "THEFT"
        assert approved["approved_by_user_id"] == USER_SUPERVISOR_1

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["theft_cents"] == 0
        assert attribution["damage_cents"] == 0
        assert attribution["process_error_cents"] == 0
        assert attribution["vendor_shortage_cents"] == 0
        assert attribution["unresolved_cents"] == 6633

        assert fx.read_position(api, world["position_id"])["promising_state"] == (
            "RESTRICTED"
        )

    def test_the_two_variants_disagree_until_the_row_closes(self, api):
        """
        The final variant deletes the non-terminal branch outright.

        "Under the **final** variant the loop is identical except that the
        non-terminal branch is deleted outright: `OPEN`, `IN_REVIEW`,
        `CAUSE_PROPOSED` and `CAUSE_APPROVED` investigations are excluded entirely
        rather than parked, and `WAIVED` is still excluded. `final_total_shrink_cents`
        is therefore the sum of the four named buckets alone."

        Design: Corner/calculations/shrink_attribution_input_set_excludes_cause_approved_rows
        """
        world = fx.counted_variance_world(api, counted_units=105)
        fx.drive_to_cause_approved(api, world["investigation_id"], "THEFT")

        before = fx.read_attribution(api, world["shrink_period_id"])
        assert before["provisional_total_shrink_cents"] == 6633
        assert before["final_total_shrink_cents"] == 0
        assert before["provisional_shrink_rate_bps"] == 13
        assert before["final_shrink_rate_bps"] == 0
        assert before["active_variant"]

        closed = validate_success(
            api.close_investigation(world["investigation_id"], SUPERVISOR)
        )
        assert closed["status"] == "CLOSED"

        after = fx.read_attribution(api, world["shrink_period_id"])
        assert after["theft_cents"] == 6633
        assert after["unresolved_cents"] == 0
        assert after["provisional_total_shrink_cents"] == 6633
        assert after["final_total_shrink_cents"] == 6633
        assert after["total_attributable_variance_cents"] == 6633


class TestTagVerificationConjunction:
    def test_one_duplicate_epc_fails_a_perfect_read_rate(self, api):
        """
        The pass test is a three-way conjunction, not a read-rate threshold.

        "The batch passes when and only when all three of the following hold:
        `read_rate_bps` is at least 9800, `duplicate_epc_count` is exactly 0, and
        `unencoded_units` is exactly 0. Otherwise it fails."

        Design: Corner/calculations/tag_verification_duplicate_epc_vetoes_a_perfect_read_rate
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)

        failed = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(
                    sampled_units=50, readable_units=50, duplicate_epc_count=1
                ),
                world["store_headers"],
            )
        )
        assert failed["read_rate_bps"] == 10000
        assert failed["verification_outcome"] == "FAIL"
        assert failed["status"] == "VERIFICATION_FAILED"
        assert failed["duplicate_epc_count"] == 1

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["tag_compliance_score_bps"] == 8500
        assert vendor["required_verification_sample_pct"] == 10

    def test_the_failure_cascades_through_the_hold_to_the_store_posture(self, api):
        """
        A tag-integrity hold dominates the gate and drags the store down with it.

        "Second, caused by the first hop, any stock position for that destination
        store and SKU has `tag_integrity_hold` set to true. Third, caused by the
        second, that position's `promising_state` is re-derived and necessarily
        becomes `BLOCKED`, since a tag-integrity hold dominates the gate."

        Design: Corner/calculations/tag_verification_duplicate_epc_vetoes_a_perfect_read_rate
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)
        validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(
                    sampled_units=50, readable_units=50, duplicate_epc_count=1
                ),
                world["store_headers"],
            )
        )

        position = fx.read_position(api, world["position_id"])
        assert position["tag_integrity_hold"] is True
        assert position["promising_state"] == "BLOCKED"

        eligibility = fx.read_eligibility(api, world["store_id"])
        assert eligibility["blocked_position_count"] == 1
        assert eligibility["blocked_ratio_bps"] == 10000
        assert eligibility["fulfillment_status"] == "SUSPENDED"

    def test_a_single_unencoded_unit_fails_the_same_way(self, api):
        """
        The third conjunct has the same veto as the second.

        "The batch passes when and only when all three of the following hold:
        `read_rate_bps` is at least 9800, `duplicate_epc_count` is exactly 0, and
        `unencoded_units` is exactly 0. Otherwise it fails."

        Design: Corner/calculations/tag_verification_duplicate_epc_vetoes_a_perfect_read_rate
        """
        world = fx.encoded_tag_batch_world(api, quantity=1000, baseline=100)

        failed = validate_success(
            api.verify_tag_batch(
                world["batch_id"],
                f.verify_payload(
                    sampled_units=50, readable_units=49, unencoded_units=1
                ),
                world["store_headers"],
            )
        )
        assert failed["read_rate_bps"] == 9800
        assert failed["verification_outcome"] == "FAIL"
        assert failed["status"] == "VERIFICATION_FAILED"
        assert fx.read_vendor(api, world["vendor_id"])["tag_compliance_score_bps"] == (
            8500
        )


class TestChargebackTierBoundary:
    def test_a_shortage_exactly_on_the_first_ceiling_stays_in_the_first_tier(self, api):
        """
        The first tier's ceiling is inclusive.

        "Step two selects the tier **on the gross shortage**: `TIER_1` when the
        shortage is at most 50000 cents, `TIER_2` when it is at most 200000 cents, and
        `TIER_3` above that. The chargeback rate is 8000 basis points for `TIER_1`,
        9000 for `TIER_2` and 10000 for `TIER_3`, and `chargeback_gross_cents` is the
        shortage multiplied by that rate divided by 10000, rounded half up."

        Design: Corner/calculations/vendor_chargeback_tier_boundary_at_exactly_fifty_thousand
        """
        world = fx.vendor_shortage_world(api, counted_units=90)

        line = validate_success(api.get_count_line(world["line_id"], ANALYST))
        assert line["variance_units"] == -10
        assert line["variance_value_cents"] == 50000
        assert line["within_tolerance"] is False

        before = fx.read_attribution(api, world["shrink_period_id"])
        assert before["vendor_shortage_cents"] == 50000
        assert before["unresolved_cents"] == 0

        charge = get_success_data(
            api.create_chargeback(
                world["vendor_id"],
                f.chargeback_payload(world["shrink_period_id"]),
                CONTROLLER,
            )
        )
        assert charge["attributable_shortage_cents"] == 50000
        assert charge["tier"] == "TIER_1"
        assert charge["chargeback_gross_cents"] == 40000
        assert charge["vendor_credit_cents"] == 6000
        assert charge["net_chargeback_cents"] == 34000
        assert charge["lifetime_chargeback_gross_cents"] == 40000
        assert charge["credited_cents"] == 6000
        assert charge["chargeback_balance_cents"] == 34000

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["shortage_event_count"] == 1
        assert vendor["tag_compliance_score_bps"] == 8500

    def test_one_cent_past_the_ceiling_re_tiers_the_whole_calculation(self, api):
        """
        Both the charge rate and the credit rate move with the gross tier.

        "Step three applies the goodwill credit, and its rate is keyed on **the same
        gross tier selected in step two**, not on the net amount: 1500 basis points
        for `TIER_1`, 1000 for `TIER_2` and 500 for `TIER_3`. `vendor_credit_cents` is
        `chargeback_gross_cents` multiplied by that credit rate divided by 10000,
        rounded half up."

        Design: Corner/calculations/vendor_chargeback_tier_boundary_at_exactly_fifty_thousand
        """
        world = fx.home_reference_world(
            api,
            item_payload_builder=lambda category_id, vendor_id: f.sofa_item_payload(
                category_id, vendor_id, unit_cost_cents=50001
            ),
            baseline=100,
        )
        fx.with_shrink_period(api, world)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 99)
        assert line["variance_units"] == -1
        assert line["variance_value_cents"] == 50001
        assert line["within_tolerance"] is False
        fx.submit_task(api, world["task_id"])

        investigation = fx.investigation_for_line(api, line["id"])
        fx.drive_to_closed(api, investigation["id"], "VENDOR_SHORTAGE")

        charge = get_success_data(
            api.create_chargeback(
                world["vendor_id"],
                f.chargeback_payload(world["shrink_period_id"]),
                CONTROLLER,
            )
        )
        assert charge["attributable_shortage_cents"] == 50001
        assert charge["tier"] == "TIER_2"
        assert charge["chargeback_gross_cents"] == 45001
        assert charge["vendor_credit_cents"] == 4500
        assert charge["net_chargeback_cents"] == 40501
        assert charge["chargeback_balance_cents"] == 40501


class TestReconciliationWaterfall:
    @staticmethod
    def _completed_two_line_pass(api):
        apparel = fx.create_category(api, f.apparel_category_payload())
        home = fx.create_category(api, f.home_category_payload())
        store = fx.create_store(api, f.store_payload())
        vendor = fx.create_vendor(api)
        firm = fx.create_counter_firm(api)
        tee = fx.create_item(api, f.item_payload(apparel["id"], vendor["id"]))
        pan = fx.create_item(api, f.pan_item_payload(home["id"], vendor["id"]))
        pos_tee = fx.create_position(api, store["id"], tee["id"], baseline=100)
        pos_pan = fx.create_position(api, store["id"], pan["id"], baseline=40)
        period = fx.create_shrink_period(api, store["id"])

        schedule = fx.create_schedule(
            api, store["id"], apparel["id"], first_due_date="2026-08-01"
        )
        task = fx.create_task(api, schedule["id"])
        fx.start_task(api, task["id"])
        variance_line = fx.add_line(api, task["id"], tee["id"], 105)
        fx.submit_task(api, task["id"])
        investigation = fx.investigation_for_line(api, variance_line["id"])
        fx.drive_to_closed(api, investigation["id"], "THEFT")
        assert fx.read_attribution(api, period["id"])["theft_cents"] == 6633

        inventory = validate_success(
            api.create_physical_inventory(
                f.physical_inventory_payload(
                    store["id"],
                    firm["id"],
                    scheduled_start_date="2026-08-20",
                    scheduled_end_date="2026-08-22",
                    recount_threshold_bps=2000,
                ),
                CONTROLLER,
            ),
            201,
        )
        started = validate_success(
            api.start_physical_inventory(inventory["id"], CONTROLLER)
        )
        validate_success(
            api.create_physical_inventory_line(
                inventory["id"],
                f.physical_line_payload(tee["id"], 90, started["version"]),
                CONTROLLER,
            ),
            201,
        )
        validate_success(
            api.create_physical_inventory_line(
                inventory["id"],
                f.physical_line_payload(
                    pan["id"], 30, fx.read_physical_inventory(api, inventory["id"])["version"]
                ),
                CONTROLLER,
            ),
            201,
        )
        return {
            "store_id": store["id"],
            "shrink_period_id": period["id"],
            "physical_inventory_id": inventory["id"],
            "position_tee_id": pos_tee["id"],
            "position_pan_id": pos_pan["id"],
        }

    def test_the_pass_rolls_up_to_the_pinned_net_variance(self, api):
        """
        The net variance in basis points is floored, not rounded.

        "Pinned: a pass with a 100-unit book line at 1234 cents counted at 90 units
        and a 40-unit book line at 1500 cents counted at 30 units has a book value of
        183400, a counted value of 156060, a net variance of −27340 and a
        `net_variance_bps` of the floor of 10000 × 27340 ÷ 183400, which is 1490."

        Design: Corner/calculations/physical_reconciliation_waterfall_fills_process_error_then_damage_then_theft
        """
        world = self._completed_two_line_pass(api)

        completed = validate_success(
            api.complete_pass(world["physical_inventory_id"], CONTROLLER)
        )
        assert completed["status"] == "FIRST_PASS_COMPLETE"
        assert completed["line_count"] == 2
        assert completed["book_value_cents"] == 183400
        assert completed["counted_value_cents"] == 156060
        assert completed["net_variance_cents"] == -27340
        assert completed["net_variance_bps"] == 1490

    def test_the_unexplained_pool_fills_the_three_capped_buckets_in_order(self, api):
        """
        The pour order is fixed and every cap is floored.

        "The `process_error_cents` cap is the floor of 27340 × 0.30, which is 8202, so
        it takes 8202 and 12505 remains. The `damage_cents` cap is the floor of 27340 ×
        0.20, which is 5468, so it takes 5468 and 7037 remains. The `theft_cents` cap
        is the floor of 27340 × 0.40, which is 10936, which exceeds the remaining 7037,
        so it takes 7037 and nothing remains. `unresolved_cents` grows by 0."

        Design: Corner/calculations/physical_reconciliation_waterfall_fills_process_error_then_damage_then_theft
        """
        world = self._completed_two_line_pass(api)
        validate_success(api.complete_pass(world["physical_inventory_id"], CONTROLLER))

        reconciled = validate_success(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            )
        )
        assert reconciled["status"] == "RECONCILING"

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["process_error_cents"] == 8202
        assert attribution["damage_cents"] == 5468
        assert attribution["theft_cents"] == 13670
        assert attribution["vendor_shortage_cents"] == 0
        assert attribution["unresolved_cents"] == 0
        assert attribution["total_attributable_variance_cents"] == 27340
        assert attribution["provisional_total_shrink_cents"] == 27340
        assert attribution["final_total_shrink_cents"] == 27340
        assert attribution["provisional_shrink_rate_bps"] == 55
        assert attribution["final_shrink_rate_bps"] == 55

    def test_every_non_zero_line_mints_one_posted_adjustment(self, api):
        """
        The book is moved before the buckets are filled.

        "For every non-superseded line of the current pass whose `variance_units` is
        not zero, walking those lines in ascending line-creation order, an adjustment
        is minted against the stock position for that store and SKU with `delta_units`
        equal to the line's `variance_units`, `reason_code` `PHYSICAL_RECONCILIATION`,
        `investigation_id` null, `approval_state` `NOT_REQUIRED` and `posting_state`
        `POSTED` — posted immediately and exempt from the authority ladder as §3.7
        states."

        Design: Corner/calculations/physical_reconciliation_waterfall_fills_process_error_then_damage_then_theft
        """
        world = self._completed_two_line_pass(api)
        validate_success(api.complete_pass(world["physical_inventory_id"], CONTROLLER))
        validate_success(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            )
        )

        rows, meta = validate_paginated(
            api.list_adjustments(SUPERVISOR, {"posting_state": "POSTED"})
        )
        assert meta["total_count"] == 2
        for row in rows:
            assert row["reason_code"] == "PHYSICAL_RECONCILIATION"
            assert row["approval_state"] == "NOT_REQUIRED"
            assert row["posting_state"] == "POSTED"
            assert row["investigation_id"] is None

        assert fx.read_position(api, world["position_tee_id"])["on_hand_units"] == 90
        assert fx.read_position(api, world["position_pan_id"])["on_hand_units"] == 30


class TestSupersededLinesLeaveTheAggregates:
    @staticmethod
    def _recounted_same_sku(api):
        world = fx.physical_inventory_world(api, baseline=100, with_period=True)
        started = validate_success(
            api.start_physical_inventory(world["physical_inventory_id"], CONTROLLER)
        )
        first = validate_success(
            api.create_physical_inventory_line(
                world["physical_inventory_id"],
                f.physical_line_payload(world["item_id"], 90, started["version"]),
                world["counter_headers"],
            ),
            201,
        )
        second = validate_success(
            api.create_physical_inventory_line(
                world["physical_inventory_id"],
                f.physical_line_payload(
                    world["item_id"],
                    100,
                    fx.read_physical_inventory(api, world["physical_inventory_id"])[
                        "version"
                    ],
                ),
                world["counter_headers"],
            ),
            201,
        )
        world["first_line_id"] = first["id"]
        world["second_line_id"] = second["id"]
        return world

    def test_the_replaced_line_is_flagged_and_dropped_from_the_rollup(self, api):
        """
        A supersede replaces rather than adds.

        "A second line for the same SKU in the same pass supersedes the first: any
        earlier line for the same inventory, SKU and `pass_round` has its `superseded`
        flag set to true. More generally a line is superseded when another line exists
        for the same inventory and SKU with either a strictly greater `pass_round`, or
        the same `pass_round` and a strictly later `created_at`. The number of
        non-superseded lines in the current pass, counting the one being created, may
        not exceed the counting firm's `max_lines_per_pass`, otherwise
        `ERR_MAX_LINES_PER_PASS_EXCEEDED`. Because a superseding line replaces rather
        than adds, re-counting a SKU does not consume additional capacity. The
        inventory's `line_count` is then recomputed over the non-superseded lines of
        the current pass, and its `version` is incremented — which is what makes the
        version check meaningful: a supersede built on a stale reading would silently
        discard a colleague's more recent count of the same SKU."

        Design: Corner/calculations/physical_reconciliation_excludes_superseded_lines
        """
        world = self._recounted_same_sku(api)

        first = validate_success(
            api.get_physical_inventory_line(world["first_line_id"], CONTROLLER)
        )
        assert first["superseded"] is True
        assert first["pass_round"] == 0

        second = validate_success(
            api.get_physical_inventory_line(world["second_line_id"], CONTROLLER)
        )
        assert second["superseded"] is False
        assert second["pass_round"] == 0
        assert second["book_units_snapshot"] == 100
        assert second["variance_units"] == 0

        completed = validate_success(
            api.complete_pass(
                world["physical_inventory_id"], world["counter_headers"]
            )
        )
        assert completed["status"] == "FIRST_PASS_COMPLETE"
        assert completed["line_count"] == 1
        assert completed["book_value_cents"] == 123400
        assert completed["counted_value_cents"] == 123400
        assert completed["net_variance_cents"] == 0
        assert completed["net_variance_bps"] == 0

        rows, meta = validate_paginated(
            api.list_physical_inventory_lines(
                CONTROLLER,
                {"physical_inventory_id": world["physical_inventory_id"]},
            )
        )
        assert meta["total_count"] == 2

    def test_a_zero_variance_pass_mints_no_adjustment(self, api):
        """
        Only a non-zero line moves the book.

        "For every non-superseded line of the current pass whose `variance_units` is
        not zero, walking those lines in ascending line-creation order, an adjustment
        is minted against the stock position for that store and SKU with `delta_units`
        equal to the line's `variance_units`, `reason_code` `PHYSICAL_RECONCILIATION`,
        `investigation_id` null, `approval_state` `NOT_REQUIRED` and `posting_state`
        `POSTED` — posted immediately and exempt from the authority ladder as §3.7
        states."

        Design: Corner/calculations/physical_reconciliation_excludes_superseded_lines
        """
        world = self._recounted_same_sku(api)
        validate_success(
            api.complete_pass(world["physical_inventory_id"], world["counter_headers"])
        )

        reconciled = validate_success(
            api.reconcile_physical_inventory(
                world["physical_inventory_id"], CONTROLLER
            )
        )
        assert reconciled["status"] == "RECONCILING"

        rows, meta = validate_paginated(api.list_adjustments(SUPERVISOR))
        assert rows == []
        assert meta["total_count"] == 0
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 100
