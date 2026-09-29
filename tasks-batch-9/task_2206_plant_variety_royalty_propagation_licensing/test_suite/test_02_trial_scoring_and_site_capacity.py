"""Trial scoring boundaries, the performance premium, and site plot capacity."""

from test_helpers import (
    BREEDER,
    COORDINATOR,
    ApiErrorId,
    advance_clock,
    assert_decimal_equals,
    assert_instant_equals,
    create_trial_site,
    create_variety,
    create_variety_trial_payload,
    evaluate_trial_payload,
    licensed_quota,
    planted_trial,
    submitted_report,
    two_region_passed_trials,
    validate_error,
    validate_success,
)

#: Component scores weighting to a raw score of exactly 76.80:
#: 32.80 + 14.80 + 15.60 + 13.60.
_RAW_76_80 = {
    "yield_index": 82,
    "vigor_score": 74,
    "uniformity_score": 78,
    "disease_resistance_score": 68,
}


class TestPropagationPassRateThreshold:
    """POST /variety-trials/{trial_id}/certify at the 0.9500 boundary."""

    def _two_evaluated_trials(self, api):
        variety = create_variety(
            api, denomination="Northlight Pear", species="Pyrus communis",
            breeder_code="NP", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        site = create_trial_site(
            api, site_name="Okanogan Station", region_code="PNW", plot_capacity=100
        )
        trial_on = planted_trial(api, variety["id"], site["id"], plot_count=20)
        trial_under = planted_trial(
            api, variety["id"], site["id"], plot_count=20, advance_to_plant_date=False
        )
        advance_clock(api, "2026-09-20T00:00:00Z", COORDINATOR)
        evaluated_on = validate_success(
            api.evaluate_variety_trial(
                trial_on["id"],
                evaluate_trial_payload(propagation_pass_rate=0.9500, **_RAW_76_80),
                COORDINATOR,
            )
        )
        evaluated_under = validate_success(
            api.evaluate_variety_trial(
                trial_under["id"],
                evaluate_trial_payload(propagation_pass_rate=0.9499, **_RAW_76_80),
                COORDINATOR,
            )
        )
        return variety, evaluated_on, evaluated_under

    def test_pass_rate_of_exactly_the_threshold_passes_the_trial(self, api):
        """A raw score of 76.80 scaled by exactly 0.9500 indexes at 72.96, and
        both certification boundaries are inclusive, so the trial passes and
        lifts the variety's aggregate.

        PRD 3.4: "A trial passes when its `performance_index` is at least 72.00 **and** its `propagation_pass_rate` is at least 0.9500 — both boundaries inclusive, so a trial indexing exactly 72.00 with a pass rate of exactly 0.9500 passes."

        Design: Difficulty/boundary_precision_check/propagation_pass_rate_inclusive_at_exactly_four_decimal_threshold
        """
        variety, evaluated_on, _under = self._two_evaluated_trials(api)
        assert_decimal_equals(evaluated_on["performance_index"], "72.96", "performance_index")

        certified = validate_success(api.certify_variety_trial(evaluated_on["id"], BREEDER))
        assert certified["status"] == "PASSED"

        parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert parent["passed_trial_region_count"] == 1
        assert_decimal_equals(parent["regional_performance_index"], "72.96",
                              "regional_performance_index")
        assert parent["lifecycle_state"] == "IN_TRIAL"

    def test_pass_rate_one_ten_thousandth_below_the_threshold_fails_the_trial(self, api):
        """The same raw score scaled by 0.9499 indexes at 72.95 and the pass rate
        is below 0.9500, so the trial fails and the variety aggregate is left
        untouched.

        PRD 3.4: "On the **`FAILED`** branch none of that happens. `passed_trial_region_count` is not recomputed, `regional_performance_index` is not recomputed, `lifecycle_state` is not changed, and the variety's `version` is **not** incremented."

        Design: Difficulty/boundary_precision_check/propagation_pass_rate_inclusive_at_exactly_four_decimal_threshold
        """
        variety, evaluated_on, evaluated_under = self._two_evaluated_trials(api)
        assert_decimal_equals(evaluated_under["performance_index"], "72.95", "performance_index")
        validate_success(api.certify_variety_trial(evaluated_on["id"], BREEDER))
        before = validate_success(api.get_variety(variety["id"], BREEDER))

        failed = validate_success(api.certify_variety_trial(evaluated_under["id"], BREEDER))
        assert failed["status"] == "FAILED"

        after = validate_success(api.get_variety(variety["id"], BREEDER))
        assert after["passed_trial_region_count"] == 1
        assert_decimal_equals(after["regional_performance_index"], "72.96",
                             "regional_performance_index")
        assert after["version"] == before["version"]

    def test_one_passed_region_is_not_enough_to_release(self, api):
        """Two trials at a single site cover only one growing region, so the region
        count stays at 1, the variety never reaches `TRIAL_COMPLETE`, and release
        is refused by the generic transition check that precedes the release gates.

        PRD 2.8: "Generic transition legality — `ERR_INVALID_STATE_TRANSITION` (HTTP 409), raised when the target's current state is not a declared origin state for the action being attempted."

        Design: Difficulty/boundary_precision_check/propagation_pass_rate_inclusive_at_exactly_four_decimal_threshold
        """
        variety, evaluated_on, evaluated_under = self._two_evaluated_trials(api)
        validate_success(api.certify_variety_trial(evaluated_on["id"], BREEDER))
        validate_success(api.certify_variety_trial(evaluated_under["id"], BREEDER))

        assert validate_success(
            api.get_variety(variety["id"], BREEDER)
        )["lifecycle_state"] == "IN_TRIAL"

        validate_error(
            api.release_variety(variety["id"], BREEDER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )


class TestEffectiveRateUpperCollar:
    """The four rate multipliers, and the cap that catches their product."""

    def _export_quota_on_a_high_indexing_variety(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_A",
            territory_class="EXPORT",
            allocated_units=20000,
            variety_overrides={
                "denomination": "Summit Pearl",
                "species": "Pyrus communis",
                "breeder_code": "SP",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Coast Range Growers",
        )
        two_region_passed_trials(
            api, chain["variety_id"],
            first_site_name="Yakima Station", second_site_name="Fresno Station",
        )
        return chain

    def test_two_passed_regions_set_the_index_behind_the_premium(self, api):
        """The mean of 85.00 and 72.00 is 78.50, which is the index the fourth
        multiplier reads, and reaching two regions completes trialing.

        PRD 3.4: "`regional_performance_index` becomes the mean of `performance_index` over exactly those `PASSED` trials, rounded half up to 2 decimal places — and 0.00 when the variety has no passed trials at all."

        Design: Difficulty/combinatorial_formula/effective_rate_five_factor_product_clamped_by_upper_collar
        """
        chain = self._export_quota_on_a_high_indexing_variety(api)

        variety = validate_success(api.get_variety(chain["variety_id"], BREEDER))
        assert variety["passed_trial_region_count"] == 2
        assert_decimal_equals(variety["regional_performance_index"], "78.50",
                              "regional_performance_index")
        assert variety["lifecycle_state"] == "TRIAL_COMPLETE"

    def test_multiplier_product_above_the_cap_is_lowered_to_the_cap(self, api):
        """Tier 1.15, export 1.25, volume 1.00 and a premium of 1.065 take the
        35-cent base to 53.5828, above the cap of 52.5000, so the stored rate is
        the cap.

        PRD 3.7: "The floor is the base rate times 0.75, and the cap is the base rate times 1.50, each rounded half-up to 4 decimal places before use."

        Design: Difficulty/combinatorial_formula/effective_rate_five_factor_product_clamped_by_upper_collar
        """
        chain = self._export_quota_on_a_high_indexing_variety(api)

        bundle = submitted_report(api, chain, 8000)

        line = validate_success(api.get_royalty_line_item(bundle["line_item_id"], BREEDER))
        assert line["billable_units"] == 8000
        assert_decimal_equals(line["effective_rate_cents"], "52.5000", "effective_rate_cents")

    def test_line_amount_is_priced_from_the_collared_rate(self, api):
        """8000 units at the collared 52.5000 is 420000 cents; the uncollared
        product would have billed 428662.

        PRD 3.7: "For each line, `billable_units` is set to `reported_units` verbatim, `overrun_flagged` is left false, `effective_rate_cents` is computed as described above, and `provisional_amount_cents` is set to `billable_units` multiplied by `effective_rate_cents`, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/effective_rate_five_factor_product_clamped_by_upper_collar
        """
        chain = self._export_quota_on_a_high_indexing_variety(api)

        bundle = submitted_report(api, chain, 8000)

        line = validate_success(api.get_royalty_line_item(bundle["line_item_id"], BREEDER))
        assert line["provisional_amount_cents"] == 420000
        assert bundle["report"]["provisional_total_cents"] == 420000


class TestTrialSiteWindowCapacity:
    """POST /variety-trials/{trial_id}/plant against a site's plot capacity."""

    def _site_with_one_planted_trial(self, api):
        variety = create_variety(
            api, denomination="Ridgeway Damson", species="Prunus insititia",
            breeder_code="RD", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        site = create_trial_site(
            api, site_name="Ridgeway Station", region_code="PNW", plot_capacity=50
        )
        first = planted_trial(api, variety["id"], site["id"], plot_count=30)
        return variety, site, first

    def test_overlapping_windows_are_summed_against_the_plot_capacity(self, api):
        """A second 30-plot trial whose window sits inside the first one's brings
        the overlapping total to 60 at a site with room for 50, so planting is
        refused while the booking itself stands.

        PRD 3.4: "Take every trial at the same `trial_site_id` whose status is `PLANNED` or `PLANTED` and whose half-open occupancy window overlaps the window of the trial being planted, count this trial among them, and add up their `plot_count` values."

        Design: Difficulty/resource_temporal_overlap/trial_site_aggregate_plot_capacity_over_half_open_windows_with_adjacency_allowed
        """
        variety, site, _first = self._site_with_one_planted_trial(api)
        overlapping = validate_success(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=30,
                    plant_date="2026-09-01T00:00:00Z", harvest_date="2026-09-20T00:00:00Z",
                ),
                COORDINATOR,
            ),
            201,
        )
        assert overlapping["status"] == "PLANNED"
        advance_clock(api, "2026-09-01T00:00:00Z", COORDINATOR)

        validate_error(
            api.plant_variety_trial(overlapping["id"], COORDINATOR),
            ApiErrorId.ERR_TRIAL_SITE_CAPACITY_EXCEEDED.value,
            409,
        )

        unchanged = validate_success(api.get_variety_trial(overlapping["id"], COORDINATOR))
        assert unchanged["status"] == "PLANNED"

    def test_a_window_starting_where_another_ends_is_not_overlap(self, api):
        """A third 30-plot trial whose plant date is exactly the first trial's
        harvest date shares no instant with it, so it plants at the same
        50-plot site.

        PRD 3.4: "Because the windows are half-open, **adjacency is not overlap**: a trial whose `harvest_date` is exactly another trial's `plant_date` does not co-occupy the site within one shared window, and the two may both be planted at a site with room for only one of them."

        Design: Difficulty/resource_temporal_overlap/trial_site_aggregate_plot_capacity_over_half_open_windows_with_adjacency_allowed
        """
        variety, site, _first = self._site_with_one_planted_trial(api)
        adjacent = validate_success(
            api.create_variety_trial(
                create_variety_trial_payload(
                    variety["id"], site["id"], plot_count=30,
                    plant_date="2026-09-20T00:00:00Z", harvest_date="2026-11-01T00:00:00Z",
                ),
                COORDINATOR,
            ),
            201,
        )
        advance_clock(api, "2026-09-20T00:00:00Z", COORDINATOR)

        planted = validate_success(api.plant_variety_trial(adjacent["id"], COORDINATOR))
        assert planted["status"] == "PLANTED"

        parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert parent["lifecycle_state"] == "IN_TRIAL"


class TestTheFourWeightsSumToOneAtFullMarks:
    """Full marks on every observation index at exactly 100.00."""

    def _trial_ready_for_evaluation(self, api):
        variety = create_variety(
            api, denomination="Hollow Bramble", species="Rubus idaeus",
            breeder_code="HW", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        site = create_trial_site(api, site_name="Hollow Station", region_code="PNW",
                                 plot_capacity=60)
        trial = planted_trial(api, variety["id"], site["id"], plot_count=10)
        advance_clock(api, "2026-09-20T00:00:00Z", COORDINATOR)
        return variety, site, trial

    def test_perfect_observations_index_at_exactly_one_hundred(self, api):
        """The four component weights add to 1.00, so each independently rounded
        component contributes its full share and no drift accumulates across them.

        PRD 3.4: "The four weights add to exactly 1.00, so a trial that scored 100 on every observation with a pass rate of 1.0000 would index at 100.00."

        Design: Corner/calculations/trial_performance_index_weights_sum_to_one_at_full_marks
        """
        _variety, _site, trial = self._trial_ready_for_evaluation(api)

        evaluated = validate_success(
            api.evaluate_variety_trial(
                trial["id"],
                evaluate_trial_payload(
                    yield_index=100.00, vigor_score=100.00, uniformity_score=100.00,
                    disease_resistance_score=100.00, propagation_pass_rate=1.0000,
                ),
                COORDINATOR,
            )
        )
        assert evaluated["status"] == "EVALUATED"
        assert_decimal_equals(evaluated["performance_index"], "100.00",
                              "performance_index")

    def test_evaluation_alone_moves_no_variety_aggregate(self, api):
        """Recording the observations writes the trial's own index and stamps its
        evaluation instant; the variety-level aggregate is a certification effect,
        so it is still at its clean baseline.

        PRD 3.4: "Evaluation stores the five observations, writes `performance_index`, stamps `evaluated_at` with the present instant, drives the trial `PLANTED → EVALUATED`, and increments the trial's `version`."

        Design: Corner/calculations/trial_performance_index_weights_sum_to_one_at_full_marks
        """
        variety, _site, trial = self._trial_ready_for_evaluation(api)

        evaluated = validate_success(
            api.evaluate_variety_trial(
                trial["id"],
                evaluate_trial_payload(
                    yield_index=100.00, vigor_score=100.00, uniformity_score=100.00,
                    disease_resistance_score=100.00, propagation_pass_rate=1.0000,
                ),
                COORDINATOR,
            )
        )
        assert_instant_equals(evaluated["evaluated_at"], "2026-09-20T00:00:00Z",
                              "evaluated_at")

        parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert parent["passed_trial_region_count"] == 0
        assert_decimal_equals(parent["regional_performance_index"], "0.00",
                              "regional_performance_index")

    def test_certifying_the_single_region_lifts_the_index_but_not_the_lifecycle(self, api):
        """One passed trial makes the mean equal to that trial's own index, and the
        region count of one leaves the variety short of the two regions release
        demands, so it stays in trialing.

        PRD 3.4: "Then, if the freshly recomputed `passed_trial_region_count` has reached 2 or more, the variety's lifecycle moves `IN_TRIAL → TRIAL_COMPLETE` and its `regional_performance_index` is re-derived as part of that transition."

        Design: Corner/calculations/trial_performance_index_weights_sum_to_one_at_full_marks
        """
        variety, _site, trial = self._trial_ready_for_evaluation(api)
        validate_success(
            api.evaluate_variety_trial(
                trial["id"],
                evaluate_trial_payload(
                    yield_index=100.00, vigor_score=100.00, uniformity_score=100.00,
                    disease_resistance_score=100.00, propagation_pass_rate=1.0000,
                ),
                COORDINATOR,
            )
        )

        certified = validate_success(api.certify_variety_trial(trial["id"], BREEDER))
        assert certified["status"] == "PASSED"

        parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert parent["passed_trial_region_count"] == 1
        assert_decimal_equals(parent["regional_performance_index"], "100.00",
                              "regional_performance_index")
        assert parent["lifecycle_state"] == "IN_TRIAL"
