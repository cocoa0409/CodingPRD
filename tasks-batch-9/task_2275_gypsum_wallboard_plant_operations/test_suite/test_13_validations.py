"""Each guard exercised at its own edge and immediately below it: the double speed
ceiling, the closed tension band, the dwell-versus-moisture tradeoff, the window that
cannot absorb a cold start, the two bundle rules behind one endpoint, the well-formed
outage window, the re-test gate on one disposition branch, and the run's MSF budget.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoardLineStatus,
    DispositionAction,
    HeldReason,
    LoadOrderStatus,
    ProductionPosture,
    QualityState,
    RunStatus,
    SaleableGrade,
    assert_no_run_side_effects,
    assert_production_run,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProcessEnvelopeGuards:
    """Three draft-time checks, each with the accepted neighbour of the rejected value."""

    @staticmethod
    def _plant_with_one_planned_batch(api: ApiClient):
        world = fixtures.baseline(api)
        world.batch = fixtures.create_batch(api, world.plant_id)
        return world

    def _draft(self, api: ApiClient, world, **overrides):
        return api.create_production_run(
            factories.run_draft_payload(
                world.plant_id,
                world.line_id,
                world.spec_reg_id,
                world.batch_id,
                requested_planned_msf=100.0,
                **overrides,
            ),
            test_users.PRODUCTION_SCHEDULER,
        )

    def test_the_speed_ceiling_is_the_lower_of_the_line_and_the_sku(
        self, api: ApiClient
    ) -> None:
        """500 fpm is refused on a 500 fpm line because the SKU caps at 480.

        PRD: "The speed check is a double ceiling: `line_speed_fpm` may not exceed the lower of the line's mechanical `max_speed_fpm` and the SKU's `line_speed_max_fpm`, and a breach of either is `ERR_LINE_SPEED_EXCEEDS_SPEC`."

        Design: Corner/validations/line_speed_above_the_sku_ceiling_is_rejected_at_draft
        """
        world = self._plant_with_one_planned_batch(api)

        validate_error(
            self._draft(api, world, line_speed_fpm=500, paper_tension_lb=45.0),
            ApiErrorId.LINE_SPEED_EXCEEDS_SPEC.value,
            422,
        )

        accepted = validate_success(
            self._draft(
                api,
                world,
                window_start="2026-08-04T06:00:00Z",
                window_end="2026-08-04T10:00:00Z",
                line_speed_fpm=480,
                paper_tension_lb=45.0,
            ),
            201,
        )
        assert_production_run(accepted)
        assert accepted["status"] == RunStatus.DRAFT.value
        assert accepted["required_paper_tension_lb"] == pytest.approx(41.80, abs=0.005), (
            "28.0 plus 230 feet a minute above the pivot"
        )

        _, meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER, params={"plant_id": world.plant_id}
            )
        )
        assert meta["total_count"] == 1, "the refused draft created no run"

    def test_both_ends_of_the_tension_band_are_inclusive(self, api: ApiClient) -> None:
        """36.99 lb is refused while 37.00 and 46.00 are both accepted.

        PRD: "The chosen `paper_tension_lb` is then valid if and only if it is greater than or equal to `required_paper_tension_lb` and less than or equal to the SKU's `paper_tension_max_lb`; both comparisons are inclusive, so landing exactly on either bound is acceptable."

        Design: Corner/validations/paper_tension_exactly_at_the_requirement_passes_one_hundredth_below_fails
        """
        world = self._plant_with_one_planned_batch(api)

        validate_error(
            self._draft(api, world, paper_tension_lb=36.99),
            ApiErrorId.PAPER_TENSION_OUT_OF_RANGE.value,
            422,
        )

        at_min = validate_success(
            self._draft(
                api,
                world,
                window_start="2026-08-04T06:00:00Z",
                window_end="2026-08-04T10:00:00Z",
                paper_tension_lb=37.0,
            ),
            201,
        )
        at_max = validate_success(
            self._draft(
                api,
                world,
                window_start="2026-08-05T06:00:00Z",
                window_end="2026-08-05T10:00:00Z",
                paper_tension_lb=46.0,
            ),
            201,
        )

        assert at_min["required_paper_tension_lb"] == pytest.approx(37.00, abs=0.005)
        assert at_min["paper_tension_lb"] == pytest.approx(37.00, abs=0.005)
        assert at_max["paper_tension_lb"] == pytest.approx(46.00, abs=0.005)

        _, meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER, params={"plant_id": world.plant_id}
            )
        )
        assert meta["total_count"] == 2

    def test_a_dwell_too_short_for_the_moisture_target_is_infeasible(
        self, api: ApiClient
    ) -> None:
        """32 minutes cannot evaporate the slurry water that 40 minutes can.

        PRD: "The profile is feasible if and only if `projected_exit_moisture_pct` is less than or equal to `kiln_exit_moisture_target_pct` plus a tolerance of 0.10 percentage points; an infeasible profile is `ERR_KILN_PROFILE_INFEASIBLE`."

        Design: Corner/validations/kiln_dwell_too_short_for_the_moisture_target_is_infeasible
        """
        world = self._plant_with_one_planned_batch(api)

        validate_error(
            self._draft(api, world, kiln_dwell_minutes=32),
            ApiErrorId.KILN_PROFILE_INFEASIBLE.value,
            422,
        )

        accepted = validate_success(
            self._draft(
                api,
                world,
                window_start="2026-08-04T06:00:00Z",
                window_end="2026-08-04T10:00:00Z",
                kiln_dwell_minutes=40,
            ),
            201,
        )
        assert accepted["projected_exit_moisture_pct"] == pytest.approx(0.00, abs=0.005), (
            "a 40-minute dwell evaporates the whole 1200.00-pound slurry water load"
        )
        assert accepted["projected_exit_moisture_pct"] <= 0.60

        _, meta = validate_paginated(
            api.list_production_runs(
                test_users.PRODUCTION_SCHEDULER, params={"plant_id": world.plant_id}
            )
        )
        assert meta["total_count"] == 1


class TestScheduleTimeCapacityGuard:
    """A 30-minute window drafts cleanly and only fails when the cold-start changeover
    is absorbed inside it."""

    def test_a_thirty_minute_window_cannot_absorb_the_cold_start_changeover(
        self, api: ApiClient
    ) -> None:
        """Capacity goes non-positive, so the schedule is refused and nothing is reserved.

        PRD: "If `capacity_msf` is `0.000` or less, the window is too short to be useful once changeover is absorbed and the schedule is refused with `ERR_WINDOW_TOO_SHORT_FOR_CHANGEOVER`."

        Design: Corner/validations/window_shorter_than_the_cold_start_changeover_leaves_no_capacity
        """
        world = fixtures.baseline_with_stucco(api)
        tiny = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-03T06:00:00Z",
            window_end="2026-08-03T06:30:00Z",
            requested_planned_msf=100.0,
        )
        assert tiny["status"] == RunStatus.DRAFT.value, "the draft itself is well formed"

        validate_error(
            api.schedule_run(
                tiny["id"],
                factories.schedule_payload(world.plant_version()),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.WINDOW_TOO_SHORT_FOR_CHANGEOVER.value,
            422,
        )

        assert_no_run_side_effects(world.read_run(tiny["id"]), RunStatus.DRAFT.value)

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.OPEN.value


class TestBundleConfigurationRules:
    """`boards_per_bundle` is screened twice: evenness at the request-shape band and the
    SKU ceiling at the process-envelope band."""

    def test_an_odd_count_is_malformed_while_an_over_ceiling_count_is_a_bundle_error(
        self, api: ApiClient
    ) -> None:
        """49 boards is caught as a bad request, 50 boards as an invalid configuration.

        PRD: "An odd value is caught as a malformed request; a value outside the numeric bounds is `ERR_BUNDLE_CONFIG_INVALID`."

        Design: Corner/validations/bundle_configuration_must_be_even_and_within_the_sku_ceiling
        """
        world = fixtures.released_run(api)
        assert world.read_run()["available_msf"] == pytest.approx(290.000, abs=0.0005)

        validate_error(
            api.create_load_order(
                factories.load_order_payload(world.run_id, world.market_id, 5, 49),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_load_order(
                factories.load_order_payload(world.run_id, world.market_id, 5, 50),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.BUNDLE_CONFIG_INVALID.value,
            422,
        )

        _, meta = validate_paginated(
            api.list_load_orders(test_users.PRODUCTION_SCHEDULER, params={"run_id": world.run_id})
        )
        assert meta["total_count"] == 0, "neither refused configuration created an order"
        assert world.read_run()["available_msf"] == pytest.approx(290.000, abs=0.0005), (
            "the run's volume is untouched by a refused staging"
        )


class TestOutageWindowWellFormedness:
    """A reversed window and a zero-length window are both rejected before any derived
    figure is computed."""

    def test_a_reversed_and_a_zero_length_window_are_both_refused(
        self, api: ApiClient
    ) -> None:
        """No outage row appears on the line and the line stays AVAILABLE.

        PRD: "On every entity that has one, `window_end` must be strictly later than `window_start`; a window that is empty or inverted is rejected with `ERR_INVALID_WINDOW` (HTTP 400)."

        Design: Corner/validations/outage_window_must_end_strictly_after_it_starts
        """
        world = fixtures.baseline(api)

        validate_error(
            api.create_outage(
                factories.outage_payload(
                    world.line_id,
                    window_start="2026-10-07T06:00:00Z",
                    window_end="2026-10-05T06:00:00Z",
                    scope_note="reversed window",
                ),
                test_users.MAINTENANCE_PLANNER,
            ),
            ApiErrorId.INVALID_WINDOW.value,
            400,
        )
        validate_error(
            api.create_outage(
                factories.outage_payload(
                    world.line_id,
                    window_start="2026-10-05T06:00:00Z",
                    window_end="2026-10-05T06:00:00Z",
                    scope_note="zero length window",
                ),
                test_users.MAINTENANCE_PLANNER,
            ),
            ApiErrorId.INVALID_WINDOW.value,
            400,
        )

        _, meta = validate_paginated(
            api.list_outages(test_users.MAINTENANCE_PLANNER, params={"line_id": world.line_id})
        )
        assert meta["total_count"] == 0
        line = validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))
        assert line["status"] == BoardLineStatus.AVAILABLE.value


class TestDispositionPreconditions:
    """The re-test requirement attaches to one branch of one endpoint, so the same held
    run refuses a release and accepts a downgrade."""

    def test_release_needs_a_retest_while_downgrade_does_not(self, api: ApiClient) -> None:
        """Same run, same state, two actions, two outcomes.

        PRD: "A `RELEASE` disposition moves the run `HELD → RELEASED`, and it is the *only* branch that requires evidence of a re-test: `retest_count` must be 1 or more, else the request is refused with `ERR_RETEST_REQUIRED`."

        Design: Corner/validations/retest_requirement_gates_only_the_release_disposition
        """
        world = fixtures.held_run(api)

        held = world.read_run()
        assert held["quality_state"] == QualityState.HELD.value
        assert held["fail_rate"] == pytest.approx(0.3333, abs=0.00005)
        assert held["retest_count"] == 0
        assert held["saleable_grade"] == SaleableGrade.UNGRADED.value
        assert held["held_reason"] == HeldReason.BOARD_TEST_FAIL.value
        before_plant = world.read_plant()
        assert before_plant["held_run_count"] == 1

        validate_error(
            api.disposition_quality(
                world.run_id,
                factories.disposition_payload(
                    action=DispositionAction.RELEASE.value,
                    disposition_note="visual re-inspection looks fine",
                ),
                test_users.QUALITY_MANAGER,
            ),
            ApiErrorId.RETEST_REQUIRED.value,
            409,
        )
        assert world.read_run()["quality_state"] == QualityState.HELD.value

        downgraded = validate_success(
            api.disposition_quality(
                world.run_id,
                factories.disposition_payload(
                    action=DispositionAction.DOWNGRADE.value,
                    disposition_note="sell as seconds",
                ),
                test_users.QUALITY_MANAGER,
            ),
            200,
        )
        assert downgraded["quality_state"] == QualityState.DOWNGRADED.value
        assert downgraded["saleable_grade"] == SaleableGrade.SECONDS.value
        assert downgraded["held_reason"] is None
        assert downgraded["net_good_msf"] == pytest.approx(290.000, abs=0.0005)
        assert downgraded["available_msf"] == pytest.approx(290.000, abs=0.0005)

        after_plant = world.read_plant()
        assert after_plant["held_run_count"] == 0
        assert after_plant["version"] > before_plant["version"]


class TestRunMsfBudget:
    """The volume budget lives on the run, so a thin run refuses the bigger trailer and
    accepts the smaller one."""

    def test_a_ten_msf_run_refuses_eleven_and_a_half_msf_of_board(
        self, api: ApiClient
    ) -> None:
        """5 bundles is 11.520 MSF and too much; 4 bundles is 9.216 MSF and fits.

        PRD: "And `total_msf` may not exceed the source run's `available_msf`, which nets out the volume already committed to sibling loads in `STAGED`, `HELD`, `LOADED` or `SHIPPED`; a breach is `ERR_RUN_MSF_INSUFFICIENT`."

        Design: Corner/validations/load_order_cannot_draw_more_msf_than_the_run_has_available
        """
        world = fixtures.completed_run(api, actual_msf=10.0, scrap_msf=0.0)

        run = world.read_run()
        assert run["net_good_msf"] == pytest.approx(10.000, abs=0.0005)
        assert run["available_msf"] == pytest.approx(10.000, abs=0.0005)

        validate_error(
            api.create_load_order(
                factories.load_order_payload(world.run_id, world.market_id, 5, 48),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.RUN_MSF_INSUFFICIENT.value,
            409,
        )

        accepted = validate_success(
            api.create_load_order(
                factories.load_order_payload(world.run_id, world.market_id, 4, 48),
                test_users.PRODUCTION_SCHEDULER,
            ),
            201,
        )
        assert accepted["status"] == LoadOrderStatus.STAGED.value
        assert accepted["total_msf"] == pytest.approx(9.216, abs=0.0005)

        assert world.read_run()["available_msf"] == pytest.approx(0.784, abs=0.0005)

        _, meta = validate_paginated(
            api.list_load_orders(test_users.PRODUCTION_SCHEDULER, params={"run_id": world.run_id})
        )
        assert meta["total_count"] == 1
