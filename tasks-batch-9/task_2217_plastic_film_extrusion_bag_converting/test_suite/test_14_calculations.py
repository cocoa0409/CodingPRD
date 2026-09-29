"""Derived figures: blend metrics, cap bands, seal variants and capability."""
import pytest

from test_helpers import (
    CONVERTER,
    ENGINEER,
    EXTRUDER,
    SEAL_OPERATOR,
    ADMIN,
    add_gauge_readings,
    append_seal_specimens,
    create_blend_recipe_payload,
    create_component_payload,
    create_extrusion_run_payload,
    create_seal_test_payload,
    get_success_data,
    pcr_grade_payload,
    setup_approved_non_food_recipe,
    setup_bag_lot_converting,
    setup_non_food_catalog,
    setup_non_food_run_completed,
    validate_paginated,
    validate_success,
)


def _draft_recipe(api, world, recipe_code):
    return get_success_data(api.create_blend_recipe(
        create_blend_recipe_payload(world["product"]["id"],
                                    recipe_code=recipe_code,
                                    layer_count=1),
        ENGINEER))


def _append(api, recipe_id, grade_id, weight_pct):
    return validate_success(api.add_recipe_component(
        recipe_id,
        create_component_payload(weight_pct=weight_pct, resin_grade_id=grade_id),
        ENGINEER), 201)


class TestSingleComponentBlendDerivation:
    """One 100 % LLDPE line still exercises every accumulator in the block."""

    @staticmethod
    def _one_line_recipe(api):
        world = setup_non_food_catalog(api)
        recipe = _draft_recipe(api, world, "R-NF-0")
        _append(api, recipe["id"], world["g_ll"]["id"], 100.0)
        world["recipe"] = get_success_data(
            api.get_blend_recipe(recipe["id"], ENGINEER))
        return world

    def test_the_composition_cost_and_density_come_off_the_single_line(self, api):
        """The lone line carries the whole weight, cost and density.

        PRD: "`blend_cost_per_kg` is then the sum of the rounded cost lines,
        rounded again to two decimals, and `blended_density_kg_m3` is the sum of
        the rounded density lines, rounded again to two decimals."

        Design: Corner/calculations/single_component_recipe_derives_every_blend_metric
        """
        world = self._one_line_recipe(api)
        recipe = world["recipe"]

        assert recipe["total_weight_pct"] == pytest.approx(100.000, abs=0.001)
        assert recipe["regrind_pct"] == pytest.approx(0.000, abs=0.001)
        assert recipe["additive_pct"] == pytest.approx(0.000, abs=0.001)
        assert recipe["blend_cost_per_kg"] == pytest.approx(1.45, abs=0.01)
        assert recipe["blended_density_kg_m3"] == pytest.approx(918.00, abs=0.01)

    def test_the_three_indices_and_the_cap_block_are_all_written(self, api):
        """A haze of 8.0 and a friction of 0.42 give 80.00 and 30.00.

        PRD: "`clarity_index` is then one hundred minus 2.500 multiplied by the
        haze sum, floored at 0.00 and rounded to two decimals."

        Design: Corner/calculations/single_component_recipe_derives_every_blend_metric
        """
        world = self._one_line_recipe(api)
        recipe = world["recipe"]

        assert recipe["strength_index"] == pytest.approx(42.00, abs=0.01)
        assert recipe["clarity_index"] == pytest.approx(80.00, abs=0.01)
        assert recipe["slip_index"] == pytest.approx(30.00, abs=0.01)
        assert recipe["barrier_layer_present"] is False
        assert recipe["food_contact_eligible"] is True
        assert recipe["virgin_pcr_pct"] == pytest.approx(0.000, abs=0.001)
        assert recipe["regrind_cap_pct"] == pytest.approx(35.000, abs=0.001)


class TestRegrindCapBandDeltas:
    """Half a blend of post-consumer resin drives the cap band to HIGH."""

    @staticmethod
    def _half_pcr_recipe(api):
        world = setup_non_food_catalog(api)
        world["g_pc"] = get_success_data(
            api.create_resin_grade(pcr_grade_payload(), ADMIN))
        recipe = _draft_recipe(api, world, "R-NF-6")
        _append(api, recipe["id"], world["g_ll"]["id"], 50.0)
        _append(api, recipe["id"], world["g_pc"]["id"], 50.0)
        world["recipe"] = get_success_data(
            api.get_blend_recipe(recipe["id"], ENGINEER))
        return world

    def test_the_high_band_takes_five_points_off_the_non_food_base_cap(self, api):
        """A virgin PCR share of 50.000 sits well past the 20.0 threshold.

        PRD: "The band then shifts the cap: `HIGH` subtracts 5.0 percentage
        points, `MID` subtracts 2.0, and `LOW` leaves it unchanged." And: "Step
        five computes `nominal_recycled_content_pct` as `virgin_pcr_pct` plus
        `regrind_pct` divided by one hundred multiplied by the product's
        `assumed_regrind_pcr_pct`, rounded to three decimals".

        Design: Corner/calculations/regrind_cap_band_uses_the_declared_threshold_and_delta_constants
        """
        recipe = self._half_pcr_recipe(api)["recipe"]

        assert recipe["virgin_pcr_pct"] == pytest.approx(50.000, abs=0.001)
        assert recipe["regrind_cap_pct"] == pytest.approx(30.000, abs=0.001)
        assert recipe["nominal_recycled_content_pct"] == pytest.approx(50.000,
                                                                      abs=0.001)

    def test_the_two_lines_are_rounded_before_they_are_summed(self, api):
        """A half share of 1.45 rounds up to 0.73 before it joins 0.55.

        PRD: "Each line's contribution is its `weight_pct` divided by one
        hundred, multiplied by the relevant unit value, and **rounded to two
        decimals at the line**." And: "`slip_index` is then the reference
        coefficient 0.600 minus that sum, divided by 0.600, multiplied by one
        hundred, then clamped to the inclusive range 0.00 through 100.00 and
        rounded to two decimals."

        Design: Corner/calculations/regrind_cap_band_uses_the_declared_threshold_and_delta_constants
        """
        recipe = self._half_pcr_recipe(api)["recipe"]

        assert recipe["blend_cost_per_kg"] == pytest.approx(1.28, abs=0.01)
        assert recipe["blended_density_kg_m3"] == pytest.approx(919.00, abs=0.01)
        assert recipe["strength_index"] == pytest.approx(36.00, abs=0.01)
        assert recipe["clarity_index"] == pytest.approx(52.50, abs=0.01)
        assert recipe["slip_index"] == pytest.approx(19.17, abs=0.01)


class TestCompletedRunReleasesItsLineWindow:
    """Occupancy is a function of status, so closure frees the window."""

    def test_the_closed_run_is_capable_and_leaves_the_line_open(self, api):
        """Five identical readings give a zero spread and the ceiling index.

        PRD: "When the standard deviation is exactly zero the raw index is taken
        as the ceiling value 4.000."

        Design: Corner/calculations/a_completed_run_no_longer_occupies_its_line_window
        """
        world = setup_non_food_run_completed(api)

        assert world["run"]["status"] == "COMPLETED"
        assert world["run"]["gauge_capability_index"] == pytest.approx(4.000,
                                                                      abs=0.001)
        assert world["run"]["gauge_capability_state"] == "CAPABLE"

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["posture"] == "OPEN"

    def test_a_new_run_may_be_booked_inside_the_vacated_window(self, api):
        """07:00 to 13:00 sits entirely inside the closed run's window.

        PRD: "Only runs whose `status` is `SCHEDULED`, `RUNNING` or `HELD`
        occupy the line; `COMPLETED` and `BLOCKED` runs never do."

        Design: Corner/calculations/a_completed_run_no_longer_occupies_its_line_window
        """
        world = setup_non_food_run_completed(api)

        booked = validate_success(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-NF-E",
                                         scheduled_start="2026-08-05T07:00:00Z",
                                         scheduled_end="2026-08-05T13:00:00Z",
                                         target_output_kg=300.0),
            EXTRUDER), 201)
        assert booked["status"] == "SCHEDULED"

        _rows, meta = validate_paginated(api.list_extrusion_runs(
            EXTRUDER, params={"line_id": world["line"]["id"]}))
        assert meta["total_count"] == 2


class TestProvisionalSealVariantOnAppend:
    """The provisional figures move on every append; the final ones do not."""

    @staticmethod
    def _lot_with_two_specimens(api):
        world = setup_bag_lot_converting(api)
        append_seal_specimens(api, world["bag_lot"]["id"],
                              ((1, 22.0), (2, 22.0)), SEAL_OPERATOR)
        return world

    def test_the_third_append_publishes_the_provisional_mean_and_verdict(self, api):
        """A 22/22/19 panel means 21.00, short of the 22.0 specification.

        PRD: "Once three or more exist, `seal_provisional_mean_n` is the mean of
        their `measured_n_per_15mm` rounded to two decimals, and
        `seal_provisional_verdict` is `PASS` when that mean is at least the
        product's `min_bottom_seal_n_per_15mm` and `FAIL` otherwise."

        Design: Corner/calculations/the_provisional_seal_variant_is_written_on_append_and_the_final_variant_stays_null
        """
        world = self._lot_with_two_specimens(api)
        pending = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert pending["seal_provisional_verdict"] == "PENDING"
        assert pending["seal_provisional_mean_n"] is None

        validate_success(api.add_seal_test(world["bag_lot"]["id"],
                                          create_seal_test_payload(3, 19.0),
                                          SEAL_OPERATOR), 201)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["status"] == "TESTING"
        assert lot["seal_provisional_mean_n"] == pytest.approx(21.00, abs=0.01)
        assert lot["seal_provisional_verdict"] == "FAIL"

    def test_the_final_variant_stays_null_until_a_manager_finalizes(self, api):
        """Three first passes are logged and none of them is a retest.

        PRD: "The *final* variant is written once, by a `QualityManager`
        finalizing the tests, and it is the only variant the lot's fork reads."
        And: "The server derives the row's `attempt` as one plus the number of
        earlier specimens sharing the same `specimen_index`, derives `is_retest`
        as true exactly when that `attempt` is greater than one".

        Design: Corner/calculations/the_provisional_seal_variant_is_written_on_append_and_the_final_variant_stays_null
        """
        world = self._lot_with_two_specimens(api)
        validate_success(api.add_seal_test(world["bag_lot"]["id"],
                                          create_seal_test_payload(3, 19.0),
                                          SEAL_OPERATOR), 201)

        lot = get_success_data(api.get_bag_lot(world["bag_lot"]["id"], CONVERTER))
        assert lot["seal_final_min_n"] is None
        assert lot["seal_final_mean_n"] is None

        assert len(lot["seal_specimens"]) == 3
        for specimen in lot["seal_specimens"]:
            assert specimen["attempt"] == 1
            assert specimen["is_retest"] is False


class TestCapabilityWithheldUntilTheFifthReading:
    """Four samples publish nothing; the fifth publishes the whole block."""

    @staticmethod
    def _run_with_four_readings(api):
        world = setup_approved_non_food_recipe(api)
        run = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-NF-1",
                                         scheduled_start="2026-08-05T06:00:00Z",
                                         scheduled_end="2026-08-05T14:00:00Z"),
            EXTRUDER))
        world["run"] = get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
        add_gauge_readings(api, run["id"], (40.0,) * 4)
        return world

    def test_four_readings_leave_every_capability_figure_null(self, api):
        """The sample count moves but nothing derived from it does.

        PRD: "The capability block behaves in two regimes. While fewer than five
        samples exist, `gauge_mean_micron`, `gauge_sd_micron`, `gauge_cv_pct` and
        `gauge_capability_index` are all null and `gauge_capability_state` reads
        `INSUFFICIENT_DATA`."

        Design: Corner/calculations/gauge_capability_is_withheld_until_the_fifth_reading_lands
        """
        world = self._run_with_four_readings(api)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["gauge_sample_count"] == 4
        assert run["gauge_mean_micron"] is None
        assert run["gauge_sd_micron"] is None
        assert run["gauge_cv_pct"] is None
        assert run["gauge_capability_index"] is None
        assert run["gauge_capability_state"] == "INSUFFICIENT_DATA"

    def test_the_fifth_reading_publishes_the_whole_block_at_once(self, api):
        """Five readings of 40.0 give a zero spread and the ceiling index.

        PRD: "Once at least five samples exist, the mean thickness is the sum of
        `thickness_micron` divided by the sample count, published as
        `gauge_mean_micron` rounded to three decimals."

        Design: Corner/calculations/gauge_capability_is_withheld_until_the_fifth_reading_lands
        """
        world = self._run_with_four_readings(api)

        validate_success(api.add_gauge_reading(world["run"]["id"],
                                               {"thickness_micron": 40.0},
                                               EXTRUDER), 201)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["gauge_sample_count"] == 5
        assert run["gauge_mean_micron"] == pytest.approx(40.000, abs=0.001)
        assert run["gauge_sd_micron"] == pytest.approx(0.0000, abs=0.0001)
        assert run["gauge_cv_pct"] == pytest.approx(0.000, abs=0.001)
        assert run["gauge_capability_index"] == pytest.approx(4.000, abs=0.001)
        assert run["gauge_capability_state"] == "CAPABLE"
        assert run["status"] == "RUNNING"
