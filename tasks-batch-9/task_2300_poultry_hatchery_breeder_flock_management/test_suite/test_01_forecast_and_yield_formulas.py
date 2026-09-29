"""Multi-factor arithmetic: the settable-egg forecast, the hatch-window delay
and the chick yield resolution.

Each of these numbers is the product or the quotient of several independently
derived inputs, so a test that only moves one input cannot tell a correct
implementation from one that dropped a factor.
"""

from test_helpers import (
    ApiClient,
    CHICK_PROCESSOR,
    FLOCK_MANAGER,
    INCUBATION_OPERATOR,
    assert_boxed_batch_pool,
    assert_chick_batch,
    assert_cull_resolution,
    assert_forecast_chain,
    assert_four_dp,
    assert_hatch_window,
    assert_instant,
    assert_setter_load,
    assert_setter_load_item,
    assert_two_dp,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_success,
)

#: A 6500-egg collection that grades out to 6200 settable eggs.
GRADE_6200 = {
    "grade_a_count": 6200,
    "cracked_count": 150,
    "dirty_count": 100,
    "small_count": 50,
}

#: A 4400-egg collection that grades out to 4200 settable eggs.
GRADE_4200 = {
    "grade_a_count": 4200,
    "cracked_count": 100,
    "dirty_count": 60,
    "small_count": 40,
}


class TestSettableEggForecast:
    """The five-factor product behind ``settable_forecast``."""

    def test_photostimulation_forecast_multiplies_every_factor_in_order(self, api):
        """PRD 3.2: "Finally `settable_forecast`, the forecast settable hatching eggs
        per day, is produced by starting from `hen_count` and multiplying it in this
        exact order by `production_rate_pct` divided by 100, then by `lighting_factor`,
        then by `nutrition_factor`, then by the settable ratio of 0.94 that expresses
        the share of eggs laid that grade out as settable, then by the derate — and
        taking the floor of the final product to a whole number of eggs." And: "Both
        factors are rounded to four decimal places *before* they enter the product; no
        other intermediate rounding occurs, and the floor is applied once, to the
        completed product."

        Design: Difficulty/combinatorial_formula/flock_forecast_five_factor_product
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        program = fx.create_program(api)
        flock = fx.create_flock(api, program["id"])
        fx.salmonella_clearance(api, flock["id"])

        response = api.start_lay(flock["id"], FLOCK_MANAGER)
        started = validate_success(response, 200)

        assert_forecast_chain(
            started,
            age_weeks=29,
            photoperiod_hours=14.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=82.0,
            lighting_factor=0.7900,
            nutrition_factor=1.0500,
            settable_forecast=5754,
        )

    def test_recompute_moves_the_age_tier_and_the_lighting_step_together(self, api):
        """PRD 3.2: "it is 0.0 for a flock younger than 21 weeks, 45.0 for a flock of 21
        through 24 weeks inclusive, 82.0 for 25 through 30 weeks inclusive, 74.0 for 31
        through 45 weeks inclusive, and 61.0 once the flock reaches 46 weeks or more."
        And: "`photoperiod_hours` is the `photoperiod_hours` of the applicable entry of
        the programme's `lighting_steps` — the last entry whose `age_weeks` is at most
        the flock's `age_weeks`".

        Design: Difficulty/combinatorial_formula/flock_forecast_five_factor_product
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        assert flock["settable_forecast"] == 5754

        fx.set_clock(api, "2026-08-22T00:00:00Z")
        response = api.recompute_forecast(flock["id"], FLOCK_MANAGER)
        recomputed = validate_success(response, 200)

        assert_forecast_chain(
            recomputed,
            age_weeks=32,
            photoperiod_hours=16.0,
            feed_grams_per_hen_day=168.0,
            production_rate_pct=74.0,
            lighting_factor=0.8500,
            nutrition_factor=1.0500,
            settable_forecast=5587,
        )
        assert recomputed["settable_forecast"] != 5193, (
            "moving only the age tier and leaving the lighting step behind gives 5193"
        )
        assert recomputed["settable_forecast"] != 6191, (
            "moving only the lighting step and leaving the age tier behind gives 6191"
        )


class TestHatchWindowStorageDelay:
    """``weighted_age_days`` first, then a single ceiling on the delay."""

    def _two_lot_load(self, api: ApiClient):
        """A load stocked with 6000 four-and-a-half-day eggs and 4000 at five and a half."""
        fx.set_clock(api, fx.CLOCK_SETUP)
        program = fx.create_program(api)
        flock = fx.flock_in_lay(api, program["id"])
        lot_1 = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_6200,
            collected_at="2026-07-28T00:00:00Z",
            collected_count=6500,
        )
        lot_2 = fx.stored_lot(
            api,
            flock["id"],
            grade=GRADE_4200,
            collected_at="2026-07-27T00:00:00Z",
            collected_count=4400,
        )
        unit = fx.sanitized_unit(api, code="U1", capacity_eggs=20000)
        profile = fx.create_profile(api)
        load = get_success_data(
            api.create_setter_load(
                f.setter_load_payload(unit["id"], profile["id"], "2026-08-01T18:00:00Z"),
                INCUBATION_OPERATOR,
            ),
            201,
        )
        item_1 = fx.draw_eggs(api, load["id"], lot_1["id"], 6000)
        item_2 = fx.draw_eggs(api, load["id"], lot_2["id"], 4000)
        return {
            "load": load,
            "item_1": item_1,
            "item_2": item_2,
            "unit": unit,
        }

    def test_window_derives_from_the_rounded_weighted_mean(self, api):
        """PRD 3.5: "`storage_delay_hours` is derived from that mean: subtract the free
        storage allowance of 3 days from `weighted_age_days`, treat a negative
        difference as zero, convert the remainder to hours at one hour of incubation
        delay per day of excess storage, and take the ceiling of that whole expression
        to a whole number of hours, never below zero." And: "`planned_transfer_at` is
        `set_at` advanced by the profile's `transfer_hours` plus `storage_delay_hours`.
        `planned_pull_at` is `set_at` advanced by the profile's `total_hours` plus
        `storage_delay_hours`. The hatch window straddles the nominal pull
        symmetrically: `pull_window_start_at` is 6 hours before `planned_pull_at` and
        `pull_window_end_at` is 6 hours after it."

        Design: Difficulty/combinatorial_formula/setter_storage_delay_sum_then_ceil
        """
        ctx = self._two_lot_load(api)
        fx.set_clock(api, "2026-08-01T18:00:00Z")

        response = api.start_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR)
        started = validate_success(response, 200)

        assert_setter_load(started, total_eggs_set=10000, set_at="2026-08-01T18:00:00Z")
        assert_four_dp(started["weighted_age_days"], 4.9000, "weighted_age_days")
        assert started["storage_delay_hours"] == 2, (
            f"storage_delay_hours: expected 2, got {started['storage_delay_hours']}"
        )
        assert_instant(
            started["planned_transfer_at"], "2026-08-20T20:00:00Z", "planned_transfer_at"
        )
        assert_hatch_window(
            started,
            planned_pull_at="2026-08-22T20:00:00Z",
            pull_window_start_at="2026-08-22T14:00:00Z",
            pull_window_end_at="2026-08-23T02:00:00Z",
        )

    def test_delay_is_not_the_sum_of_per_lot_ceilings(self, api):
        """PRD 3.5: "The order matters and reversing it is wrong: the weighted mean is
        computed and rounded to four decimal places *first*, then the allowance is
        subtracted, then a **single** ceiling is applied — ceilinging each draw's own
        delay and then weighting produces a different answer."

        Design: Difficulty/combinatorial_formula/setter_storage_delay_sum_then_ceil
        """
        ctx = self._two_lot_load(api)
        assert_setter_load_item(ctx["item_1"], eggs_taken=6000)
        assert_two_dp(
            ctx["item_1"]["effective_age_days_at_set"], 4.50, "effective_age_days_at_set"
        )
        assert_two_dp(
            ctx["item_2"]["effective_age_days_at_set"], 5.50, "effective_age_days_at_set"
        )

        fx.set_clock(api, "2026-08-01T18:00:00Z")
        started = validate_success(
            api.start_setter_load(ctx["load"]["id"], INCUBATION_OPERATOR), 200
        )

        assert started["storage_delay_hours"] == 2, (
            "the mean 4.9000 gives a delay of 2 hours; ceilinging each lot first "
            f"gives 3, got {started['storage_delay_hours']}"
        )


class TestChickYieldResolution:
    """The vaccine reject tier keyed on the preliminary yield, then the box ceiling."""

    def test_reject_tier_is_keyed_on_the_preliminary_yield(self, api):
        """PRD 3.7: "`preliminary_yield_pct` is computed (step 2): subtract
        `sexing_cull_count` from `hatched_count`, divide by `hatched_count`, multiply by
        100, and round half up to two decimal places." And: "The `vaccine_reject_rate`
        is selected from a four-band tier on the **rounded** `preliminary_yield_pct`
        (step 3): 0.004 when the preliminary yield is 96.0 percent or above; 0.008 when
        it is at least 92.0 and below 96.0; 0.015 when it is at least 85.0 and below
        92.0; and 0.028 when it is below 85.0." And: "Then `vaccine_cull_count` is the
        ceiling of `hatched_count` less `sexing_cull_count`, multiplied by
        `vaccine_reject_rate` (step 4)."

        Design: Difficulty/combinatorial_formula/chick_yield_tier_from_preliminary
        """
        ctx = fx.pulled_batch_context(api)
        sexed = validate_success(
            api.sex_chick_batch(ctx["batch"]["id"], f.sexing_payload(), CHICK_PROCESSOR),
            200,
        )
        assert_two_dp(sexed["preliminary_yield_pct"], 98.94, "preliminary_yield_pct")

        vaccinated = validate_success(
            api.vaccinate_chick_batch(ctx["batch"]["id"], "MAREKS_HVT", CHICK_PROCESSOR),
            200,
        )

        assert_four_dp(vaccinated["vaccine_reject_rate"], 0.004, "vaccine_reject_rate")
        assert_chick_batch(
            vaccinated,
            vaccine_cull_count=38,
            cull_count=138,
            saleable_count=9262,
        )
        assert_cull_resolution(vaccinated)
        assert_two_dp(vaccinated["final_yield_pct"], 98.53, "final_yield_pct")

    def test_box_count_ceilings_the_saleable_pool(self, api):
        """PRD 3.7: "On success, `box_count` is computed as the ceiling of
        `saleable_count` divided by the standard box of 100 chicks (step 7),
        `unassigned_chicks` is initialised to `saleable_count`, and
        `quality_score_final` is computed from the final variant of the quality score."

        Design: Difficulty/combinatorial_formula/chick_yield_tier_from_preliminary
        """
        ctx = fx.vaccinated_batch_context(api)

        boxed = validate_success(
            api.box_chick_batch(ctx["batch"]["id"], CHICK_PROCESSOR), 200
        )

        assert_chick_batch(boxed, saleable_count=9262, box_count=93)
        assert_two_dp(boxed["final_yield_pct"], 98.53, "final_yield_pct")
        assert_boxed_batch_pool(boxed)
