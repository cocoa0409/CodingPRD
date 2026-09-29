"""Arithmetic pinned at the points where a plausible shortcut gives a different
answer: a tier boundary, a filtered input set, a rounding boundary, a ceiling, a
left-endpoint integration, a branch-specific penalty rate, and a greedy waterfall.
"""

from test_helpers import (
    ApiClient,
    CHICK_PROCESSOR,
    FLOCK_MANAGER,
    HATCHERY_MANAGER,
    INCUBATION_OPERATOR,
    VETERINARIAN,
    AssignmentStatus,
    ChickBatchStatus,
    EnvironmentStatus,
    FlockStatus,
    HatcherLoadStatus,
    ItemStatus,
    OrderStatus,
    PullClass,
    QualityFlag,
    SetterLoadStatus,
    assert_breeder_flock,
    assert_chick_batch,
    assert_chick_conservation,
    assert_delivery_assignment,
    assert_forecast_chain,
    assert_four_dp,
    assert_hatch_window,
    assert_hatcher_load,
    assert_instant,
    assert_one_dp,
    assert_placement_order,
    assert_setter_load,
    assert_setter_load_item,
    assert_three_dp,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_paginated,
    validate_success,
)

#: Sexing counts summing to a 9000-chick pull with 450 sexing culls, which puts the
#: preliminary yield exactly on the lower edge of the 0.008 vaccine band.
TIER_B_SEXING = {
    "male_count": 4275,
    "female_count": 4275,
    "unsexed_count": 0,
    "sexing_cull_count": 450,
}


class TestForecastTiersAndFactors:
    """The age tier, the base fallbacks and the four-decimal factors."""

    def test_a_flock_below_every_step_forecasts_zero_then_enters_the_first_tier(
        self, api
    ):
        """PRD 3.2: "when the flock is younger than the first lighting step it sits on the
        base photoperiod of 8.0 hours" and "when no step applies yet the flock is fed the
        target ration of 160.0 grams per hen per day." And: "it is 0.0 for a flock younger
        than 21 weeks, 45.0 for a flock of 21 through 24 weeks inclusive".

        Design: Corner/calculations/forecast_age_tier_zero_below_stimulation_then_first_tier
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)

        placed = fx.create_flock(
            api, program["id"], hatch_date="2026-03-14T00:00:00Z"
        )

        assert_forecast_chain(
            placed,
            age_weeks=20,
            production_rate_pct=0.0,
            photoperiod_hours=8.0,
            feed_grams_per_hen_day=160.0,
            lighting_factor=0.7000,
            nutrition_factor=1.0000,
            settable_forecast=0,
        )

        fx.set_clock(api, "2026-08-08T12:00:00Z")
        recomputed = validate_success(
            api.recompute_forecast(placed["id"], FLOCK_MANAGER), 200
        )

        assert_forecast_chain(
            recomputed,
            age_weeks=21,
            production_rate_pct=45.0,
            photoperiod_hours=12.0,
            feed_grams_per_hen_day=150.0,
            lighting_factor=0.7300,
            nutrition_factor=0.9375,
            settable_forecast=2605,
        )
        assert_breeder_flock(recomputed, status=FlockStatus.PLACED.value)

    def test_the_nutrition_factor_rounds_half_up_before_it_enters_the_product(self, api):
        """PRD 3.2: "The `nutrition_factor` rewards feeding to target. Divide
        `feed_grams_per_hen_day` by the target ration of 160.0 grams, then clamp that ratio
        so it is never below 0.80 and never above 1.10, and round the clamped value half up
        to four decimal places." And: "Both factors are rounded to four decimal places
        *before* they enter the product; no other intermediate rounding occurs, and the floor
        is applied once, to the completed product."

        Design: Corner/calculations/nutrition_factor_rounds_half_up_before_multiplication
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(
            api,
            code="P2",
            feed_steps=[
                {"age_weeks": 21, "feed_grams_per_hen_day": 150.0},
                {"age_weeks": 26, "feed_grams_per_hen_day": 155.0},
            ],
        )

        flock = fx.create_flock(api, program["id"], code="F2", house_code="H2")

        assert_forecast_chain(
            flock,
            age_weeks=29,
            production_rate_pct=82.0,
            photoperiod_hours=14.0,
            feed_grams_per_hen_day=155.0,
            lighting_factor=0.7900,
            nutrition_factor=0.9688,
            settable_forecast=5309,
        )
        assert_four_dp(flock["nutrition_factor"], 0.9688, "nutrition_factor")

        recomputed = validate_success(
            api.recompute_forecast(flock["id"], FLOCK_MANAGER), 200
        )
        assert_four_dp(recomputed["nutrition_factor"], 0.9688, "nutrition_factor")
        assert recomputed["settable_forecast"] == 5309, (
            "the forecast is deterministic: a truncating factor of 0.9687 would give 5308"
        )


class TestInputSetFiltering:
    """A voided draw must leave the weighted mean, and with it the hatch window."""

    def test_a_voided_draw_drops_out_of_the_weighted_mean_and_shifts_the_window(
        self, api
    ):
        """PRD 3.5: "First, `weighted_age_days` is the egg-count weighted mean storage age
        of the eggs actually loaded: multiply each `ACTIVE` draw's `eggs_taken` by its frozen
        `effective_age_days_at_set`, sum those products across all `ACTIVE` draws, divide by
        the sum of `eggs_taken` across the same draws, and round half up to four decimal
        places. Voided draws take no part."

        Design: Corner/calculations/weighted_age_excludes_voided_item_from_pull_window
        """
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        old_lot = fx.stored_lot(
            api,
            flock["id"],
            grade={
                "grade_a_count": 4000,
                "cracked_count": 150,
                "dirty_count": 100,
                "small_count": 50,
            },
            storage_temp_c=15.0,
            collected_at="2026-07-24T12:00:00Z",
            collected_count=4300,
        )
        fresh_lot = fx.stored_lot(
            api,
            flock["id"],
            grade={
                "grade_a_count": 6000,
                "cracked_count": 150,
                "dirty_count": 100,
                "small_count": 50,
            },
            storage_temp_c=15.0,
            collected_at="2026-07-30T12:00:00Z",
            collected_count=6300,
        )
        unit = fx.sanitized_unit(api, code="U1", capacity_eggs=20000)
        profile = fx.create_profile(api)
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(
                    unit["id"], profile["id"], fx.STANDARD_PLANNED_SET_AT
                ),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        old_item = fx.draw_eggs(api, load["id"], old_lot["id"], 4000)
        fx.draw_eggs(api, load["id"], fresh_lot["id"], 6000)
        assert_two_dp(
            old_item["effective_age_days_at_set"], 8.00, "effective_age_days_at_set"
        )
        assert_setter_load(fx.read_load(api, load["id"]), total_eggs_set=10000)

        validate_success(
            api.condemn_egg_lot(old_lot["id"], "SHELL_QUALITY", VETERINARIAN), 200
        )

        after_condemn = fx.read_load(api, load["id"])
        assert_setter_load(
            after_condemn,
            status=SetterLoadStatus.PLANNED.value,
            total_eggs_set=6000,
        )
        voided = [
            item
            for item in fx.list_items_of_load(api, load["id"])
            if item["item_status"] == ItemStatus.VOIDED.value
        ]
        assert len(voided) == 1, f"exactly the old lot's draw is voided, got {voided}"
        assert_setter_load_item(voided[0], egg_lot_id=old_lot["id"], eggs_taken=4000)
        assert_two_dp(
            voided[0]["effective_age_days_at_set"],
            8.00,
            "effective_age_days_at_set",
        )

        fx.set_clock(api, fx.STANDARD_PLANNED_SET_AT)
        started = validate_success(
            api.start_setter_load(load["id"], INCUBATION_OPERATOR), 200
        )

        assert_four_dp(started["weighted_age_days"], 2.0000, "weighted_age_days")
        assert_setter_load(started, storage_delay_hours=0)
        assert_instant(
            started["planned_transfer_at"], "2026-08-20T18:00:00Z", "planned_transfer_at"
        )
        assert_hatch_window(
            started,
            planned_pull_at="2026-08-22T18:00:00Z",
            pull_window_start_at="2026-08-22T12:00:00Z",
            pull_window_end_at="2026-08-23T00:00:00Z",
        )


class TestTiersCeilingsAndPenalties:
    """Chick yield and quality, where each constant is chosen by a branch or band."""

    def _tier_b_batch(self, api: ApiClient):
        return fx.pulled_batch_context(
            api, fertile_count=9600, hatched_count=9000
        )

    def test_the_middle_vaccine_band_rate_and_the_box_ceiling(self, api):
        """PRD 3.7: "The `vaccine_reject_rate` is selected from a four-band tier on the
        **rounded** `preliminary_yield_pct` (step 3): 0.004 when the preliminary yield is
        96.0 percent or above; 0.008 when it is at least 92.0 and below 96.0". And: "Then
        `vaccine_cull_count` is the ceiling of `hatched_count` less `sexing_cull_count`,
        multiplied by `vaccine_reject_rate` (step 4)." And: "`box_count` is computed as the
        ceiling of `saleable_count` divided by the standard box of 100 chicks (step 7)".

        Design: Corner/calculations/chick_yield_tier_b_rate_and_box_ceiling
        """
        ctx = self._tier_b_batch(api)
        assert_hatcher_load(
            ctx["hatcher_load"],
            status=HatcherLoadStatus.WINDOW_PULLED.value,
            pull_class=PullClass.WINDOW.value,
            quality_flag=QualityFlag.NONE.value,
        )
        assert_hatch_window(
            ctx["hatcher_load"],
            planned_pull_at="2026-08-22T18:00:00Z",
            pull_window_start_at="2026-08-22T12:00:00Z",
            pull_window_end_at="2026-08-23T00:00:00Z",
        )
        assert_two_dp(
            ctx["hatcher_load"]["pull_offset_hours"], 0.00, "pull_offset_hours"
        )
        assert ctx["hatcher_load"]["hold_release_at"] is None
        assert_two_dp(
            ctx["batch"]["quality_score_provisional"],
            100.00,
            "quality_score_provisional",
        )

        sexed = validate_success(
            api.sex_chick_batch(
                ctx["batch"]["id"], f.sexing_payload(**TIER_B_SEXING), CHICK_PROCESSOR
            ),
            200,
        )
        assert_two_dp(sexed["preliminary_yield_pct"], 95.00, "preliminary_yield_pct")

        vaccinated = validate_success(
            api.vaccinate_chick_batch(
                ctx["batch"]["id"], "MAREKS_HVT", CHICK_PROCESSOR
            ),
            200,
        )
        assert_four_dp(
            vaccinated["vaccine_reject_rate"], 0.0080, "vaccine_reject_rate"
        )
        assert_chick_batch(
            vaccinated,
            vaccine_cull_count=69,
            cull_count=519,
            saleable_count=8481,
        )
        assert_two_dp(vaccinated["final_yield_pct"], 94.23, "final_yield_pct")

        boxed = validate_success(
            api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200
        )
        assert_chick_batch(
            boxed,
            status=ChickBatchStatus.BOXED.value,
            box_count=85,
            unassigned_chicks=8481,
        )
        assert_two_dp(boxed["quality_score_final"], 94.81, "quality_score_final")

        flock = fx.read_flock(api, ctx["flock"]["id"])
        assert_two_dp(
            flock["hatchability_rolling_pct"], 84.81, "hatchability_rolling_pct"
        )
        assert_two_dp(
            flock["hatchability_fertile_pct"], 88.34, "hatchability_fertile_pct"
        )
        _rows, meta = validate_paginated(
            api.list_corrective_actions(
                HATCHERY_MANAGER, {"flock_id": ctx["flock"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "84.81 percent is not below the threshold, so no action is opened"
        )

    def test_a_late_pull_charges_the_late_rate_and_bumps_the_flock_counter(self, api):
        """PRD 3.6: "When the logical clock is strictly after `pull_window_end_at`, the load
        moves `HATCHING → LATE_PULLED`, `pull_class` is `LATE` and `pull_offset_hours` is
        positive, being the hours from `pull_window_end_at` forward to the pull instant. The
        `quality_flag` becomes `DEHYDRATION`, `hold_release_at` stays null, and the batch's
        primary breeder flock has its `late_pull_count` incremented by 1". And PRD 3.6: "The
        late penalty applies only when `pull_class` is `LATE`: multiply 2.40 by
        `pull_offset_hours` and round half up to two decimal places." And: "the gap between
        the two scores is exactly the cull penalty plus the flag penalty."

        Design: Corner/calculations/late_pull_penalty_constants_and_flock_counter
        """
        ctx = fx.pulled_batch_context(
            api, pull_at="2026-08-23T02:00:00Z", hatched_count=9400
        )

        assert_hatcher_load(
            ctx["hatcher_load"],
            status=HatcherLoadStatus.LATE_PULLED.value,
            pull_class=PullClass.LATE.value,
            quality_flag=QualityFlag.DEHYDRATION.value,
        )
        assert_two_dp(
            ctx["hatcher_load"]["pull_offset_hours"], 2.00, "pull_offset_hours"
        )
        assert ctx["hatcher_load"]["hold_release_at"] is None, (
            "only the early branch stamps a hold"
        )
        provisional = ctx["batch"]["quality_score_provisional"]
        assert_two_dp(provisional, 95.20, "quality_score_provisional")
        assert fx.read_flock(api, ctx["flock"]["id"])["late_pull_count"] == 1

        sexed = validate_success(
            api.sex_chick_batch(
                ctx["batch"]["id"],
                f.sexing_payload(**fx.HEALTHY_SEXING),
                CHICK_PROCESSOR,
            ),
            200,
        )
        assert_two_dp(sexed["preliminary_yield_pct"], 98.94, "preliminary_yield_pct")
        vaccinated = validate_success(
            api.vaccinate_chick_batch(
                ctx["batch"]["id"], "MAREKS_HVT", CHICK_PROCESSOR
            ),
            200,
        )
        assert_four_dp(
            vaccinated["vaccine_reject_rate"], 0.0040, "vaccine_reject_rate"
        )
        assert_chick_batch(
            vaccinated,
            vaccine_cull_count=38,
            cull_count=138,
            saleable_count=9262,
        )

        boxed = validate_success(
            api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200
        )

        assert_chick_batch(boxed, status=ChickBatchStatus.BOXED.value)
        assert_two_dp(boxed["quality_score_final"], 89.88, "quality_score_final")
        assert_two_dp(
            boxed["quality_score_final"] - provisional,
            -5.32,
            "final less provisional",
        )


class TestAccumulationOverTime:
    """Degree-hours charged at the left endpoint of each segment."""

    def test_a_segment_is_charged_at_the_previous_readings_excess(self, api):
        """PRD 3.5: "Ingesting a reading closes the segment that runs from the *previous*
        reading's `recorded_at` up to this reading's `recorded_at`, and charges that whole
        segment at the **previous** reading's excess deviation held constant across it." And:
        "The first reading of a load closes no segment, so its `segment_degree_hours` is 0."
        And: "a segment of exactly 1.500 degree-hours does **not** open a deviation."

        Design: Corner/calculations/deviation_segment_charges_previous_reading_excess
        """
        ctx = fx.incubating_load_context(api, set_at=fx.CLOCK_SET_AT)
        load_id = ctx["load"]["id"]

        first = fx.ingest_reading(api, load_id, "2026-08-01T18:00:00Z", 38.6)
        fx.set_clock(api, "2026-08-01T20:00:00Z")
        second = fx.ingest_reading(api, load_id, "2026-08-01T20:00:00Z", 37.8)
        after_second = fx.read_load(api, load_id)
        fx.set_clock(api, "2026-08-01T23:00:00Z")
        third = fx.ingest_reading(api, load_id, "2026-08-01T23:00:00Z", 37.8)

        assert_one_dp(first["elapsed_hours"], 0.0, "elapsed_hours")
        assert_two_dp(first["target_temp_c"], 37.8, "target_temp_c")
        assert_two_dp(first["abs_deviation_c"], 0.80, "abs_deviation_c")
        assert_three_dp(
            first["segment_degree_hours"], 0.000, "segment_degree_hours"
        )

        assert_two_dp(second["abs_deviation_c"], 0.00, "abs_deviation_c")
        assert_three_dp(
            second["segment_degree_hours"], 1.000, "segment_degree_hours"
        )
        assert_three_dp(
            after_second["deviation_degree_hours"], 1.000, "deviation_degree_hours"
        )
        assert_setter_load(
            after_second,
            status=SetterLoadStatus.INCUBATING.value,
            environment_status=EnvironmentStatus.NOMINAL.value,
        )

        assert_three_dp(
            third["segment_degree_hours"], 0.000, "segment_degree_hours"
        )
        final = fx.read_load(api, load_id)
        assert_three_dp(
            final["deviation_degree_hours"], 1.000, "deviation_degree_hours"
        )
        assert final["deviation_opened_at"] is None, (
            "1.000 degree-hours never crosses the 1.50 threshold"
        )
        assert_setter_load(
            final,
            status=SetterLoadStatus.INCUBATING.value,
            environment_status=EnvironmentStatus.NOMINAL.value,
        )


class TestGreedyAllocation:
    """Whole boxes down a ranked list, earliest order first."""

    def test_the_earliest_order_is_filled_before_any_chick_reaches_the_later_one(
        self, api
    ):
        """PRD 3.8: "Otherwise take the smaller of the order's `remaining_need` and the pool,
        divide by 100 discarding the remainder, and multiply back by 100: that whole-box
        figure is the grant." And: "Earlier orders are filled to the whole box before any
        chicks reach a later order, even when that leaves a later order with nothing at all."
        And: "any sub-box remainder simply stays there — it is never allocated."

        Design: Corner/calculations/allocation_waterfall_fills_ranked_order_before_next
        """
        ctx = fx.allocation_ready_context(
            api,
            farm_capacity=20000,
            orders=[
                {
                    "requested_chicks": 5000,
                    "requested_placement_date": "2026-08-22T00:00:00Z",
                },
                {
                    "requested_chicks": 4000,
                    "requested_placement_date": "2026-08-23T00:00:00Z",
                },
            ],
            fertile_count=9600,
            hatched_count=9000,
            sexing=TIER_B_SEXING,
        )
        assert_chick_batch(
            fx.read_batch(api, ctx["batch"]["id"]),
            saleable_count=8481,
            unassigned_chicks=8481,
        )
        first_order, second_order = ctx["orders"]

        assignments = fx.run_allocation(api, ctx["batch"]["id"])

        assert len(assignments) == 2, (
            f"the pool serves exactly two orders, got {assignments}"
        )
        assert_delivery_assignment(
            assignments[0],
            chick_batch_id=ctx["batch"]["id"],
            placement_order_id=first_order["id"],
            chicks_assigned=5000,
            boxes_assigned=50,
            scheduled_delivery_date="2026-08-22T00:00:00Z",
            status=AssignmentStatus.ASSIGNED.value,
        )
        assert_delivery_assignment(
            assignments[1],
            placement_order_id=second_order["id"],
            chicks_assigned=3400,
            boxes_assigned=34,
            scheduled_delivery_date="2026-08-23T00:00:00Z",
            status=AssignmentStatus.ASSIGNED.value,
        )
        assert_placement_order(
            fx.read_order(api, first_order["id"]),
            status=OrderStatus.FULFILLED.value,
            allocated_chicks=5000,
            remaining_need=0,
        )
        assert_placement_order(
            fx.read_order(api, second_order["id"]),
            status=OrderStatus.PARTIALLY_FULFILLED.value,
            allocated_chicks=3400,
            remaining_need=600,
        )
        batch = fx.read_batch(api, ctx["batch"]["id"])
        assert_chick_batch(batch, unassigned_chicks=81)
        assert_chick_conservation(
            batch, fx.list_assignments_of_batch(api, ctx["batch"]["id"])
        )
