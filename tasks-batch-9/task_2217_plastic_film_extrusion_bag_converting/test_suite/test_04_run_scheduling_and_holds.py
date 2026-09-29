"""Line occupancy with the conditional purge gap, hold cycles, recipe pinning."""
import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    EXTRUDER,
    ApiErrorId,
    create_blend_recipe_payload,
    create_component_payload,
    create_extrusion_run_payload,
    get_success_data,
    make_blend_engineer_headers,
    make_quality_manager_headers,
    pcr_grade_payload,
    setup_approved_non_food_recipe,
    setup_non_food_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)


def _run_payload(world, recipe, run_code, start, end, target_output_kg=500.0):
    return create_extrusion_run_payload(world["line"]["id"], recipe["id"],
                                        run_code=run_code,
                                        scheduled_start=start,
                                        scheduled_end=end,
                                        target_output_kg=target_output_kg)


class TestLineOccupancyPurgeGap:
    """Abutment is free on the same blend and blocked across a blend change."""

    @staticmethod
    def _two_recipes_and_first_run(api):
        world = setup_non_food_catalog(api)
        world["g_pc"] = get_success_data(
            api.create_resin_grade(pcr_grade_payload(), ADMIN))
        world = setup_approved_non_food_recipe(api=api, world=world,
                                               recipe_code="R-NF-0")
        world["r0"] = world["recipe"]
        world = setup_approved_non_food_recipe(
            api=api, world=world, recipe_code="R-NF-6",
            components=((1, "VIRGIN", 50.0, "g_ll"), (1, "VIRGIN", 50.0, "g_pc")))
        world["r6"] = world["recipe"]
        world["run1"] = get_success_data(api.create_extrusion_run(
            _run_payload(world, world["r0"], "RUN-NF-1",
                         "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z"),
            EXTRUDER))
        return world

    def test_same_recipe_abutment_needs_no_purge_gap(self, api):
        """A run starting exactly at 14:00 on the same blend is admitted.

        PRD: "Because the windows are half-open, a run beginning exactly at an
        existing run's `scheduled_end` with a zero gap does not conflict."

        Design: Difficulty/resource_temporal_overlap/line_exclusive_occupancy_with_conditional_purge_buffer
        """
        world = self._two_recipes_and_first_run(api)
        run2 = validate_success(api.create_extrusion_run(
            _run_payload(world, world["r0"], "RUN-NF-2",
                         "2026-08-05T14:00:00Z", "2026-08-05T20:00:00Z"),
            EXTRUDER), 201)

        assert run2["status"] == "SCHEDULED"
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["purge_buffer_minutes"] == 45
        assert line["posture"] == "OPEN"

    def test_different_recipe_abutment_is_covered_by_the_purge_gap(self, api):
        """A blend change at 20:00 falls inside the 45-minute purge window.

        PRD: "In every other case the required gap is the line's
        `purge_buffer_minutes`." The neighbouring run pins a different
        `blend_recipe_id`, so the gap applies and the abutment conflicts.

        Design: Difficulty/resource_temporal_overlap/line_exclusive_occupancy_with_conditional_purge_buffer
        """
        world = self._two_recipes_and_first_run(api)
        get_success_data(api.create_extrusion_run(
            _run_payload(world, world["r0"], "RUN-NF-2",
                         "2026-08-05T14:00:00Z", "2026-08-05T20:00:00Z"),
            EXTRUDER))

        validate_error(api.create_extrusion_run(
            _run_payload(world, world["r6"], "RUN-NF-3",
                         "2026-08-05T20:00:00Z", "2026-08-05T23:00:00Z",
                         target_output_kg=300.0),
            EXTRUDER), ApiErrorId.ERR_LINE_WINDOW_CONFLICT, 409)

    def test_clearing_the_purge_gap_admits_the_blend_change(self, api):
        """Starting at 20:45 clears the gap and the run is scheduled.

        PRD: "A conflict exists when the new run's `scheduled_start` falls
        earlier than the occupying run's `scheduled_end` extended forward by the
        gap".

        Design: Difficulty/resource_temporal_overlap/line_exclusive_occupancy_with_conditional_purge_buffer
        """
        world = self._two_recipes_and_first_run(api)
        get_success_data(api.create_extrusion_run(
            _run_payload(world, world["r0"], "RUN-NF-2",
                         "2026-08-05T14:00:00Z", "2026-08-05T20:00:00Z"),
            EXTRUDER))
        validate_error(api.create_extrusion_run(
            _run_payload(world, world["r6"], "RUN-NF-3",
                         "2026-08-05T20:00:00Z", "2026-08-05T23:00:00Z",
                         target_output_kg=300.0),
            EXTRUDER), ApiErrorId.ERR_LINE_WINDOW_CONFLICT, 409)

        run4 = validate_success(api.create_extrusion_run(
            _run_payload(world, world["r6"], "RUN-NF-4",
                         "2026-08-05T20:45:00Z", "2026-08-05T23:45:00Z",
                         target_output_kg=300.0),
            EXTRUDER), 201)
        assert run4["scheduled_start"].startswith("2026-08-05T20:45:00")

        rows, meta = validate_paginated(api.list_extrusion_runs(
            EXTRUDER, params={"line_id": world["line"]["id"],
                              "status": "SCHEDULED"}))
        assert meta["total_count"] == 3
        assert len(rows) == 3

        r0 = get_success_data(api.get_blend_recipe(world["r0"]["id"], ENGINEER))
        r6 = get_success_data(api.get_blend_recipe(world["r6"]["id"], ENGINEER))
        assert r0["pinned_run_count"] == 2
        assert r6["pinned_run_count"] == 1


class TestRunHoldResumeCycle:
    """A run may be held and resumed repeatedly until the hold limit is passed."""

    @staticmethod
    def _running_run(api):
        world = setup_approved_non_food_recipe(api)
        run = get_success_data(api.create_extrusion_run(
            _run_payload(world, world["recipe"], "RUN-NF-1",
                         "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z"),
            EXTRUDER))
        get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
        world["run"] = run
        return world

    def test_first_hold_and_resume_move_the_line_hold_counter(self, api):
        """The hold counter on the line rises and falls with the run.

        PRD: "A hold moves `RUNNING → HELD`, requires a `hold_reason` in the
        payload, increments the run's `hold_count`, increments the line's
        `active_hold_count` and re-derives `posture`".

        Design: Difficulty/non_linear_state_machine/run_hold_resume_cycle_bounded_by_max_run_holds
        """
        world = self._running_run(api)
        held = validate_success(
            api.hold_extrusion_run(world["run"]["id"], "die lip cleaning", EXTRUDER),
            200)
        assert held["status"] == "HELD"
        assert held["hold_count"] == 1
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["active_hold_count"] == 1

        resumed = validate_success(
            api.resume_extrusion_run(world["run"]["id"], EXTRUDER), 200)
        assert resumed["status"] == "RUNNING"
        assert resumed["hold_reason"] is None
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["active_hold_count"] == 0

    @pytest.mark.parametrize("reasons,expected_count", [
        (("die lip cleaning",), 1),
        (("die lip cleaning", "bubble instability"), 2),
        (("die lip cleaning", "bubble instability", "gauge band drift"), 3),
    ])
    def test_repeated_hold_resume_passes_accumulate_the_count(self, api, reasons,
                                                              expected_count):
        """Three complete cycles leave the run RUNNING with a rising counter.

        PRD: "A run may be held and resumed repeatedly, but resume is refused
        with `ERR_RUN_HOLD_LIMIT_EXCEEDED` once `hold_count` has passed three".

        Design: Difficulty/non_linear_state_machine/run_hold_resume_cycle_bounded_by_max_run_holds
        """
        world = self._running_run(api)
        for reason in reasons:
            get_success_data(api.hold_extrusion_run(world["run"]["id"], reason,
                                                    EXTRUDER))
            get_success_data(api.resume_extrusion_run(world["run"]["id"], EXTRUDER))

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["hold_count"] == expected_count
        assert run["status"] == "RUNNING"

    def test_fourth_resume_is_refused_and_the_run_stays_held(self, api):
        """The fourth hold is accepted but its resume is not.

        PRD: "resume is refused with `ERR_RUN_HOLD_LIMIT_EXCEEDED` once
        `hold_count` has passed three; beyond that point the run can only be
        completed or blocked."

        Design: Difficulty/non_linear_state_machine/run_hold_resume_cycle_bounded_by_max_run_holds
        """
        world = self._running_run(api)
        for reason in ("die lip cleaning", "bubble instability", "gauge band drift"):
            get_success_data(api.hold_extrusion_run(world["run"]["id"], reason,
                                                    EXTRUDER))
            get_success_data(api.resume_extrusion_run(world["run"]["id"], EXTRUDER))

        fourth = validate_success(
            api.hold_extrusion_run(world["run"]["id"], "air ring fault", EXTRUDER),
            200)
        assert fourth["hold_count"] == 4
        assert fourth["status"] == "HELD"

        validate_error(api.resume_extrusion_run(world["run"]["id"], EXTRUDER),
                       ApiErrorId.ERR_RUN_HOLD_LIMIT_EXCEEDED, 409)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["status"] == "HELD"
        assert run["hold_reason"] == "air ring fault"
        assert run["hold_count"] == 4
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["posture"] == "OPEN"


class TestSchedulingAgainstASupersededRecipe:
    """The gate sits on the referenced recipe, not on the line."""

    @staticmethod
    def _superseded_predecessor(api):
        world = setup_approved_non_food_recipe(api, recipe_code="R-NF-0")
        world["r0"] = world["recipe"]
        successor = get_success_data(api.create_blend_recipe(
            create_blend_recipe_payload(world["product"]["id"],
                                        recipe_code="R-NF-0B",
                                        layer_count=1,
                                        supersedes_recipe_id=world["r0"]["id"]),
            ENGINEER))
        get_success_data(api.add_recipe_component(
            successor["id"],
            create_component_payload(layer_index=1, component_kind="VIRGIN",
                                     weight_pct=100.0,
                                     resin_grade_id=world["g_ll"]["id"]),
            ENGINEER))
        get_success_data(api.submit_blend_recipe(
            successor["id"], make_blend_engineer_headers("u-be-2")))
        get_success_data(api.approve_blend_recipe(
            successor["id"], make_quality_manager_headers("u-qm-2")))
        world["r0b"] = get_success_data(
            api.get_blend_recipe(successor["id"], ENGINEER))
        return world

    def test_unpinned_predecessor_supersedes_immediately(self, api):
        """With no pinning runs the predecessor leaves APPROVED at once.

        PRD: "When a successor is approved and the predecessor's
        `pinned_run_count` is zero, the predecessor moves `APPROVED →
        SUPERSEDED` immediately."

        Design: Difficulty/cross_entity_state_dependency/run_scheduling_requires_recipe_approved_not_superseded
        """
        world = self._superseded_predecessor(api)
        r0 = get_success_data(api.get_blend_recipe(world["r0"]["id"], ENGINEER))

        assert r0["status"] == "SUPERSEDED"
        assert r0["supersede_pending"] is False
        assert r0["pinned_run_count"] == 0
        assert world["r0b"]["status"] == "APPROVED"
        assert world["r0b"]["supersedes_recipe_id"] == world["r0"]["id"]

    def test_scheduling_against_the_superseded_recipe_is_refused(self, api):
        """No run may pin a recipe that has left APPROVED.

        PRD: "`SUPERSEDED` is terminal, and any later attempt to schedule a run
        against a superseded recipe is refused with `ERR_RECIPE_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/run_scheduling_requires_recipe_approved_not_superseded
        """
        world = self._superseded_predecessor(api)
        validate_error(api.create_extrusion_run(
            _run_payload(world, world["r0"], "RUN-NF-X",
                         "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z"),
            EXTRUDER), ApiErrorId.ERR_RECIPE_NOT_APPROVED, 409)

        _rows, meta = validate_paginated(api.list_extrusion_runs(
            EXTRUDER, params={"line_id": world["line"]["id"]}))
        assert meta["total_count"] == 0
        line = get_success_data(api.get_extrusion_line(world["line"]["id"], ADMIN))
        assert line["posture"] == "OPEN"

    def test_the_successor_recipe_is_the_legal_thing_to_schedule(self, api):
        """The refusal is about the recipe: its successor schedules cleanly.

        PRD: "An `ExtrusionOperator` or `PlantAdmin` schedules a **run** by
        supplying a `run_code`, the `line_id` to occupy, the `blend_recipe_id` to
        pin".

        Design: Difficulty/cross_entity_state_dependency/run_scheduling_requires_recipe_approved_not_superseded
        """
        world = self._superseded_predecessor(api)
        validate_error(api.create_extrusion_run(
            _run_payload(world, world["r0"], "RUN-NF-X",
                         "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z"),
            EXTRUDER), ApiErrorId.ERR_RECIPE_NOT_APPROVED, 409)

        accepted = validate_success(api.create_extrusion_run(
            _run_payload(world, world["r0b"], "RUN-NF-X",
                         "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z"),
            EXTRUDER), 201)
        assert accepted["status"] == "SCHEDULED"
