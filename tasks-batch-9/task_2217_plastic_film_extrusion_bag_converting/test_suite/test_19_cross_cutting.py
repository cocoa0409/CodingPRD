"""Cross-cutting layers: pool versioning, reconciliation, hold rates, immediacy."""
import pytest

from test_helpers import (
    CLOCK_D1_1500,
    ENGINEER,
    EXTRUDER,
    ApiErrorId,
    add_gauge_readings,
    build_non_food_recipe_draft,
    create_component_payload,
    create_extrusion_run_payload,
    create_film_roll_payload,
    get_success_data,
    read_pool_version,
    set_logical_clock,
    setup_approved_non_food_recipe,
    setup_non_food_catalog,
    setup_second_non_food_run_running,
    validate_error,
    validate_success,
)


def _draw(pool_id, kg, version):
    return {"pool_id": pool_id, "kg": kg,
            "expected_regrind_pool_version": version}


class TestPoolVersionAdvancesOnEveryDraw:
    """The stale-version gate is what separates two individually valid draws."""

    @staticmethod
    def _pool_after_a_sixty_kilogram_draw(api):
        world = setup_second_non_food_run_running(api)
        world["captured_version"] = read_pool_version(api, world["pool"]["id"])
        world["first_draw"] = validate_success(api.create_regrind_reincorporation(
            world["run2"]["id"],
            _draw(world["pool"]["id"], 60.0, world["captured_version"]),
            EXTRUDER), 201)
        world["pool"] = get_success_data(
            api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        return world

    def test_the_first_draw_settles_the_pool_and_advances_the_version(self, api):
        """One hundred kilograms in, sixty out, and the version moves on.

        PRD: "Every accepted draw, and every reversal booked against the pool,
        increments the pool's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/pool_version_advances_on_every_write_and_only_the_current_one_is_accepted
        """
        world = self._pool_after_a_sixty_kilogram_draw(api)

        assert world["pool"]["available_kg"] == pytest.approx(40.000, abs=0.01)
        assert world["pool"]["cumulative_out_kg"] == pytest.approx(60.000, abs=0.01)
        assert world["pool"]["version"] > world["captured_version"]

    def test_replaying_the_captured_version_is_refused(self, api):
        """Ten more kilograms would have fitted; the superseded view does not.

        PRD: "If that value does not equal the pool's current `version`, the draw
        is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/pool_version_advances_on_every_write_and_only_the_current_one_is_accepted
        """
        world = self._pool_after_a_sixty_kilogram_draw(api)

        error = validate_error(api.create_regrind_reincorporation(
            world["run2"]["id"],
            _draw(world["pool"]["id"], 10.0, world["captured_version"]),
            EXTRUDER), ApiErrorId.ERR_STALE_POOL_VERSION, 412)

        assert error["error_id"] != ApiErrorId.ERR_REGRIND_INSUFFICIENT
        assert error["error_id"] != ApiErrorId.ERR_REGRIND_BUDGET_EXCEEDED

    def test_the_refused_replay_leaves_the_ledger_untouched(self, api):
        """A 412 books nothing: one outbound row, same balance.

        PRD: "`generation_count` counts the non-reversed inbound rows and
        `reincorporation_count` the non-reversed outbound rows. A second invariant
        holds system-wide and is checkable at any point: `available_kg` plus the
        total non-reversed outbound mass always equals the total non-reversed
        inbound mass."

        Design: Corner/cross_cutting_complexity_layers/pool_version_advances_on_every_write_and_only_the_current_one_is_accepted
        """
        world = self._pool_after_a_sixty_kilogram_draw(api)
        validate_error(api.create_regrind_reincorporation(
            world["run2"]["id"],
            _draw(world["pool"]["id"], 10.0, world["captured_version"]),
            EXTRUDER), ApiErrorId.ERR_STALE_POOL_VERSION, 412)

        pool = get_success_data(
            api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["available_kg"] == pytest.approx(40.000, abs=0.01)
        assert pool["reincorporation_count"] == 1
        assert pool["generation_count"] == 1

    def test_reading_the_current_version_makes_the_second_draw_land(self, api):
        """The draw was never illegitimate — only the version it declared was.

        PRD: "the same run may draw from the same pool many times, and two draws
        that each individually fit inside `available_kg` would each succeed on
        their own merits."

        Design: Corner/cross_cutting_complexity_layers/pool_version_advances_on_every_write_and_only_the_current_one_is_accepted
        """
        world = self._pool_after_a_sixty_kilogram_draw(api)
        validate_error(api.create_regrind_reincorporation(
            world["run2"]["id"],
            _draw(world["pool"]["id"], 10.0, world["captured_version"]),
            EXTRUDER), ApiErrorId.ERR_STALE_POOL_VERSION, 412)

        fresh = read_pool_version(api, world["pool"]["id"])
        validate_success(api.create_regrind_reincorporation(
            world["run2"]["id"], _draw(world["pool"]["id"], 10.0, fresh),
            EXTRUDER), 201)

        pool = get_success_data(
            api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["available_kg"] == pytest.approx(30.000, abs=0.01)
        assert pool["reincorporation_count"] == 2


class TestRecipeDerivedVectorIsReconciledPerWrite:
    """No derived field is a running accumulator over the append stream."""

    @staticmethod
    def _empty_draft(api):
        world = setup_non_food_catalog(api)
        world["recipe"] = build_non_food_recipe_draft(api, world,
                                                      recipe_code="R-NF-0",
                                                      components=())
        return world

    @staticmethod
    def _append(api, world, weight_pct):
        get_success_data(api.add_recipe_component(
            world["recipe"]["id"],
            create_component_payload(layer_index=1, component_kind="VIRGIN",
                                     weight_pct=weight_pct,
                                     resin_grade_id=world["g_ll"]["id"]),
            ENGINEER))
        return get_success_data(
            api.get_blend_recipe(world["recipe"]["id"], ENGINEER))

    def test_the_first_append_publishes_a_partial_but_complete_vector(self, api):
        """At 60.000 percent the whole block is already derived, not deferred.

        PRD: "Every append recomputes the whole derived block. `total_weight_pct`
        is the sum of `weight_pct` across all components, rounded to three
        decimals."

        Design: Corner/cross_cutting_complexity_layers/recipe_derived_fields_are_reconciled_after_every_component_write
        """
        world = self._empty_draft(api)
        recipe = self._append(api, world, 60.0)

        assert recipe["total_weight_pct"] == pytest.approx(60.000, abs=0.01)
        assert recipe["blend_cost_per_kg"] == pytest.approx(0.87, abs=0.01)
        assert recipe["blended_density_kg_m3"] == pytest.approx(550.80, abs=0.01)
        assert recipe["status"] == "DRAFT"

    def test_the_indices_of_the_partial_recipe_are_weighted_the_same_way(self, api):
        """Dart, haze and friction sums all run over the single 60.000 line.

        PRD: "A dart base is accumulated as the sum, over every component, of its
        `weight_pct` divided by one hundred multiplied by that component's dart
        contribution".

        Design: Corner/cross_cutting_complexity_layers/recipe_derived_fields_are_reconciled_after_every_component_write
        """
        world = self._empty_draft(api)
        recipe = self._append(api, world, 60.0)

        assert recipe["strength_index"] == pytest.approx(25.20, abs=0.01)
        assert recipe["clarity_index"] == pytest.approx(88.00, abs=0.01)
        assert recipe["slip_index"] == pytest.approx(58.00, abs=0.01)

    def test_the_second_append_reaches_the_one_component_answer(self, api):
        """A 60/40 split lands exactly where a single 100.000 line would.

        PRD: "`blend_cost_per_kg` is then the sum of the rounded cost lines,
        rounded again to two decimals, and `blended_density_kg_m3` is the sum of
        the rounded density lines, rounded again to two decimals."

        Design: Corner/cross_cutting_complexity_layers/recipe_derived_fields_are_reconciled_after_every_component_write
        """
        world = self._empty_draft(api)
        self._append(api, world, 60.0)
        recipe = self._append(api, world, 40.0)

        assert recipe["total_weight_pct"] == pytest.approx(100.000, abs=0.01)
        assert recipe["blend_cost_per_kg"] == pytest.approx(1.45, abs=0.01)
        assert recipe["blended_density_kg_m3"] == pytest.approx(918.00, abs=0.01)
        assert recipe["strength_index"] == pytest.approx(42.00, abs=0.01)
        assert recipe["clarity_index"] == pytest.approx(80.00, abs=0.01)
        assert recipe["slip_index"] == pytest.approx(30.00, abs=0.01)
        assert recipe["status"] == "DRAFT"


class TestTheSecondActiveHoldRestrictsTheLine:
    """The hold counter is a live gauge that falls again on resume."""

    @staticmethod
    def _one_held_run_and_one_running_run(api):
        world = setup_approved_non_food_recipe(api)
        first = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-NF-1",
                                         scheduled_start="2026-08-05T06:00:00Z",
                                         scheduled_end="2026-08-05T14:00:00Z"),
            EXTRUDER))
        get_success_data(api.start_extrusion_run(first["id"], EXTRUDER))
        world["run"] = get_success_data(
            api.hold_extrusion_run(first["id"], "gauge drift", EXTRUDER))

        set_logical_clock(api, CLOCK_D1_1500)
        second = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-NF-H",
                                         scheduled_start="2026-08-05T15:00:00Z",
                                         scheduled_end="2026-08-05T20:00:00Z"),
            EXTRUDER))
        world["run_h"] = get_success_data(
            api.start_extrusion_run(second["id"], EXTRUDER))
        return world

    def test_one_active_hold_leaves_the_line_open(self, api):
        """A single held run is below the restriction threshold.

        PRD: "Otherwise it is `RESTRICTED` when `incapable_run_count` is exactly
        one, or when `active_hold_count` has reached two or more. Otherwise it is
        `OPEN`."

        Design: Corner/cross_cutting_complexity_layers/the_second_active_hold_restricts_the_line_and_a_resume_reopens_it
        """
        world = self._one_held_run_and_one_running_run(api)

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], EXTRUDER))
        assert line["active_hold_count"] == 1
        assert line["posture"] == "OPEN"
        assert line["incapable_run_count"] == 0

    def test_the_second_hold_tips_the_line_to_restricted(self, api):
        """Holding the running run crosses the threshold in the same request.

        PRD: "increments the line's `active_hold_count` and re-derives `posture` —
        which is why a second concurrent hold on the same line tips that line from
        `OPEN` to `RESTRICTED`."

        Design: Corner/cross_cutting_complexity_layers/the_second_active_hold_restricts_the_line_and_a_resume_reopens_it
        """
        world = self._one_held_run_and_one_running_run(api)

        held = validate_success(
            api.hold_extrusion_run(world["run_h"]["id"], "bubble instability",
                                   EXTRUDER), 200)
        assert held["status"] == "HELD"
        assert held["hold_count"] == 1

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], EXTRUDER))
        assert line["active_hold_count"] == 2
        assert line["posture"] == "RESTRICTED"

    def test_resuming_either_run_reopens_the_line(self, api):
        """The counter is not cumulative: it falls back to one and reopens.

        PRD: "Resuming moves `HELD → RUNNING`, requires that the line's `posture`
        not be `FROZEN`, clears `hold_reason`, decrements the line's
        `active_hold_count` and re-derives `posture`."

        Design: Corner/cross_cutting_complexity_layers/the_second_active_hold_restricts_the_line_and_a_resume_reopens_it
        """
        world = self._one_held_run_and_one_running_run(api)
        get_success_data(api.hold_extrusion_run(world["run_h"]["id"],
                                                "bubble instability", EXTRUDER))

        resumed = validate_success(
            api.resume_extrusion_run(world["run_h"]["id"], EXTRUDER), 200)
        assert resumed["status"] == "RUNNING"
        assert resumed["hold_count"] == 1

        line = get_success_data(api.get_extrusion_line(world["line"]["id"], EXTRUDER))
        assert line["active_hold_count"] == 1
        assert line["posture"] == "OPEN"
        assert line["incapable_run_count"] == 0
        still_held = get_success_data(
            api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert still_held["status"] == "HELD"


class TestRunCompletionIsFinalInItsOwnResponse:
    """Nothing about closure lags behind the write that caused it."""

    @staticmethod
    def _running_run_with_one_roll(api):
        world = setup_approved_non_food_recipe(api)
        run = get_success_data(api.create_extrusion_run(
            create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                         run_code="RUN-NF-1",
                                         scheduled_start="2026-08-05T06:00:00Z",
                                         scheduled_end="2026-08-05T14:00:00Z"),
            EXTRUDER))
        get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
        add_gauge_readings(api, run["id"], (40.0,) * 5)
        world["roll"] = get_success_data(api.create_film_roll(
            create_film_roll_payload(run["id"], 1, 100.0), EXTRUDER))
        world["run"] = run
        return world

    def test_the_completion_response_carries_the_whole_mass_balance(self, api):
        """Status, masses and recycled-content figures arrive together.

        PRD: "`net_good_kg` is `gross_output_kg` minus `scrap_kg`, rounded to three
        decimals." And "`regrind_actual_pct` is `regrind_consumed_kg` divided by
        `gross_output_kg`, multiplied by one hundred, rounded to three decimals."

        Design: Corner/consistency_model/run_completion_returns_every_derived_field_in_the_same_response
        """
        world = self._running_run_with_one_roll(api)

        completed = validate_success(api.complete_extrusion_run(
            world["run"]["id"], 500.0, 100.0, EXTRUDER), 200)

        assert completed["status"] == "COMPLETED"
        assert completed["gross_output_kg"] == pytest.approx(500.000, abs=0.01)
        assert completed["scrap_kg"] == pytest.approx(100.000, abs=0.01)
        assert completed["net_good_kg"] == pytest.approx(400.000, abs=0.01)
        assert completed["regrind_consumed_kg"] == pytest.approx(0.000, abs=0.01)
        assert completed["regrind_actual_pct"] == pytest.approx(0.000, abs=0.01)
        assert completed["actual_recycled_content_pct"] == pytest.approx(0.000,
                                                                        abs=0.01)

    def test_the_same_response_carries_the_capability_verdict(self, api):
        """The gauge verdict is not a separately computed read.

        PRD: "When the standard deviation is exactly zero the raw index is taken
        as the ceiling value 4.000."

        Design: Corner/consistency_model/run_completion_returns_every_derived_field_in_the_same_response
        """
        world = self._running_run_with_one_roll(api)

        completed = validate_success(api.complete_extrusion_run(
            world["run"]["id"], 500.0, 100.0, EXTRUDER), 200)

        assert completed["gauge_sample_count"] == 5
        assert completed["gauge_capability_index"] == pytest.approx(4.000, abs=0.01)
        assert completed["gauge_capability_state"] == "CAPABLE"

    def test_the_pool_is_already_at_its_new_balance_on_the_next_read(self, api):
        """The scrap booking needs no settling step.

        PRD: "A dedicated computed read re-derives all of these from the rows and
        returns the reconciled pool, so a caller can verify the balance without
        trusting the stored copy."

        Design: Corner/consistency_model/run_completion_returns_every_derived_field_in_the_same_response
        """
        world = self._running_run_with_one_roll(api)
        validate_success(api.complete_extrusion_run(
            world["run"]["id"], 500.0, 100.0, EXTRUDER), 200)

        balance = get_success_data(
            api.get_regrind_pool_balance(world["pool"]["id"], EXTRUDER))
        assert balance["available_kg"] == pytest.approx(100.000, abs=0.01)
        assert balance["cumulative_in_kg"] == pytest.approx(100.000, abs=0.01)
        assert balance["generation_count"] == 1

    def test_the_wound_roll_already_carries_the_runs_as_built_fraction(self, api):
        """The copy onto the roll happens inside the completion request.

        PRD: "The run's `actual_recycled_content_pct` is copied onto every film
        roll wound by the run."

        Design: Corner/consistency_model/run_completion_returns_every_derived_field_in_the_same_response
        """
        world = self._running_run_with_one_roll(api)
        validate_success(api.complete_extrusion_run(
            world["run"]["id"], 500.0, 100.0, EXTRUDER), 200)

        roll = get_success_data(api.get_film_roll(world["roll"]["id"], EXTRUDER))
        assert roll["status"] == "WOUND"
        assert roll["actual_recycled_content_pct"] == pytest.approx(0.000, abs=0.01)
