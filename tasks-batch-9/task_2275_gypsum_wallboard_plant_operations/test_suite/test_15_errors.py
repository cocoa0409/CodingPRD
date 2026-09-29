"""Each refusal identified by its own code rather than by a generic one: the two
authentication shapes, the aged assay, the frozen posture, the third deferral, the line
committed to maintenance, the silo ceiling at the crediting moment, the lot balance, the
empty specimen set and the fire-rated changeover buffer.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    BoardLineStatus,
    LotStatus,
    OutageStatus,
    OutageType,
    ProductionPosture,
    QualityState,
    RunStatus,
    SaleableGrade,
    StuccoQualityFlag,
    assert_no_run_side_effects,
    assert_production_run,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthenticationShapes:
    """Both failures are the same code at the same status, and neither reaches the
    authorization band that would have answered 403."""

    def test_a_missing_role_and_an_undeclared_role_are_both_unauthenticated(
        self, api: ApiClient
    ) -> None:
        """No plant is created by either attempt.

        PRD: "A request that omits either header, or that presents an `X-User-Role` value outside those seven strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_or_unknown_role_header_returns_unauthenticated
        """
        missing = validate_error(
            api.create_plant(
                factories.plant_payload(code="GYP-9", name="No Header Plant"),
                test_users.NO_ROLE_HEADERS,
            ),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        unknown = validate_error(
            api.create_plant(
                factories.plant_payload(code="GYP-9", name="Bogus Role Plant"),
                test_users.UNKNOWN_ROLE_HEADERS,
            ),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        for error in (missing, unknown):
            assert error["error_id"] != ApiErrorId.UNAUTHORIZED.value, (
                "authentication is decided before any endpoint role list is consulted"
            )

        _, meta = validate_paginated(api.list_plants(test_users.PLANT_ADMIN))
        assert meta["total_count"] == 0


class TestAssayValidityWindow:
    """Thirty days is measured from `assayed_at` against the logical clock and the
    boundary day is still inside the window."""

    def test_a_feed_on_day_thirty_is_accepted_and_one_past_day_thirty_one_is_not(
        self, api: ApiClient
    ) -> None:
        """The lot keeps 90.000 tons and stays APPROVED, so only the age refuses the feed.

        PRD: "A feed is subject to five preconditions, and they hold identically for the first feed and for every subsequent one: the lot's `status` must be `APPROVED` or the request fails with `ERR_LOT_NOT_APPROVED`; the lot must belong to the same plant as the batch or the request fails with `ERR_PLANT_SCOPE_MISMATCH`; the lot's assay must still be current, meaning the logical clock must be no more than 30 days past the lot's `assayed_at`, or the request fails with `ERR_ASSAY_EXPIRED`; the `expected_lot_version` must equal the lot's current `version` or the request fails with `ERR_STALE_LOT_VERSION`; and `tons_fed` must not exceed the lot's `remaining_tons` or the request fails with `ERR_LOT_TONS_INSUFFICIENT`."

        Design: Corner/errors/feed_from_a_lot_whose_assay_aged_past_thirty_days
        """
        world = fixtures.baseline(api)
        world.lot_a = fixtures.synthetic_lot(
            api,
            world.plant_id,
            free_moisture_pct=10.0,
            purity_pct=90.0,
            chloride_ppm=100,
            supplier_name="Pawnee FGD",
            received_tons=100.0,
        )
        assert world.lot_a["assayed_at"].startswith("2026-08-01T00:00:00")
        world.batch = fixtures.create_batch(api, world.plant_id)

        fixtures.set_clock(api, "2026-08-31T00:00:00Z")
        on_the_boundary = validate_success(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(
                    world.lot_a_id, 10.0, 10.0, world.lot_a["version"]
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            201,
        )
        assert on_the_boundary["tons_fed"] == pytest.approx(10.000, abs=0.0005)
        assert world.read_batch()["status"] == BatchStatus.FEEDING.value

        drawn = world.read_lot_a()
        fixtures.set_clock(api, "2026-09-01T00:00:01Z")
        validate_error(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(world.lot_a_id, 10.0, 10.0, drawn["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.ASSAY_EXPIRED.value,
            409,
        )

        lot = world.read_lot_a()
        assert lot["status"] == LotStatus.APPROVED.value
        assert lot["remaining_tons"] == pytest.approx(90.000, abs=0.0005)
        assert world.read_batch()["feed_tons_total"] == pytest.approx(10.000, abs=0.0005)


class TestFrozenPostureStopsScheduling:
    """An emergency in progress is a plant-wide stop, whatever the run's own window
    says."""

    def test_an_emergency_in_progress_blocks_a_run_days_away_from_its_window(
        self, api: ApiClient
    ) -> None:
        """The posture code answers, not a line, window or balance code.

        PRD: "Scheduling a run and starting a run are both refused while the posture is `FROZEN`, with `ERR_PLANT_POSTURE_FROZEN` (HTTP 409)."

        Design: Corner/errors/scheduling_while_an_emergency_outage_freezes_the_plant
        """
        world = fixtures.baseline_with_stucco(api)
        world.run = fixtures.draft_run(
            api,
            world,
            window_start="2026-08-05T06:00:00Z",
            window_end="2026-08-05T10:00:00Z",
            requested_planned_msf=100.0,
        )

        emergency = fixtures.propose_outage(
            api,
            world.line_id,
            outage_type=OutageType.EMERGENCY.value,
            window_start="2026-08-03T06:00:00Z",
            window_end="2026-08-03T18:00:00Z",
            scope_note="mixer gearbox seized",
        )
        fixtures.approve_outage(api, emergency["id"])
        fixtures.set_clock(api, "2026-08-03T06:00:00Z")
        world.outage = fixtures.start_outage(api, emergency["id"])
        assert world.outage["status"] == OutageStatus.IN_PROGRESS.value

        before = world.read_plant()
        assert before["production_posture"] == ProductionPosture.FROZEN.value
        assert (
            validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))["status"]
            == BoardLineStatus.UNDER_MAINTENANCE.value
        )

        validate_error(
            api.schedule_run(
                world.run_id,
                factories.schedule_payload(before["version"]),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.PLANT_POSTURE_FROZEN.value,
            409,
        )

        assert_no_run_side_effects(world.read_run(), RunStatus.DRAFT.value)
        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005)


class TestDeferralCeiling:
    """The counter is per outage and survives every re-proposal, so the third push is
    refused on a freshly re-proposed window."""

    def test_a_third_deferral_is_refused_with_the_counter_pinned_at_two(
        self, api: ApiClient
    ) -> None:
        """Two rounds of push-and-re-propose exhaust the allowance.

        PRD: "An outage may be deferred at most twice: a third attempt, made when `deferral_count` has already reached 2, is refused with `ERR_MAX_DEFERRALS_REACHED`."

        Design: Corner/errors/third_deferral_of_one_outage_is_refused
        """
        world = fixtures.baseline(api)
        outage = fixtures.propose_outage(api, world.line_id)

        first = fixtures.defer_outage(api, outage["id"])
        assert first["status"] == OutageStatus.DEFERRED.value
        assert first["deferral_count"] == 1
        fixtures.repropose_outage(
            api, outage["id"], "2026-10-12T06:00:00Z", "2026-10-14T06:00:00Z"
        )
        second = fixtures.defer_outage(api, outage["id"], deferred_reason="spare parts on backorder")
        assert second["deferral_count"] == 2
        reproposed = fixtures.repropose_outage(
            api, outage["id"], "2026-10-19T06:00:00Z", "2026-10-21T06:00:00Z"
        )
        assert reproposed["status"] == OutageStatus.PROPOSED.value
        assert reproposed["deferral_count"] == 2, "a re-proposal never resets the counter"

        validate_error(
            api.defer_outage(
                outage["id"],
                factories.defer_payload(deferred_reason="third slip"),
                test_users.MAINTENANCE_PLANNER,
            ),
            ApiErrorId.MAX_DEFERRALS_REACHED.value,
            409,
        )

        after = fixtures.read_outage(api, outage["id"])
        assert after["status"] == OutageStatus.PROPOSED.value
        assert after["deferral_count"] == 2
        assert after["window_start"].startswith("2026-10-19T06:00:00")
        assert after["seasonality_index"] == pytest.approx(0.90, abs=0.005)
        assert after["deferred_reason"] == reproposed["deferred_reason"], (
            "the refused call recorded no new reason"
        )
        assert after["version"] == reproposed["version"]
        assert (
            validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))["status"]
            == BoardLineStatus.AVAILABLE.value
        )


class TestLineCommittedToMaintenance:
    """Approval schedules maintenance months ahead, and a start demands an `AVAILABLE`
    line whatever the outage's own window is."""

    def test_an_august_run_cannot_start_on_a_line_scheduled_for_october_work(
        self, api: ApiClient
    ) -> None:
        """The windows never intersect, so nothing was cancelled and nothing was at risk.

        PRD: "The line's `status` must be `AVAILABLE`, so a line whose outage has been approved and is therefore `MAINTENANCE_SCHEDULED`, or that is already `UNDER_MAINTENANCE`, blocks the start with `ERR_LINE_NOT_AVAILABLE`."

        Design: Corner/errors/starting_a_run_on_a_line_already_committed_to_maintenance
        """
        world = fixtures.scheduled_run(api, requested_planned_msf=100.0)
        assert world.read_run()["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005)

        outage = fixtures.approved_outage(api, world)
        assert outage["status"] == OutageStatus.APPROVED.value
        assert outage["at_risk_msf"] == pytest.approx(0.000, abs=0.0005), (
            "the August run does not intersect the October window"
        )
        assert (
            validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))["status"]
            == BoardLineStatus.MAINTENANCE_SCHEDULED.value
        )

        fixtures.set_clock(api, "2026-08-03T06:00:00Z")
        validate_error(
            api.start_run(world.run_id, {}, test_users.PRODUCTION_SCHEDULER),
            ApiErrorId.LINE_NOT_AVAILABLE.value,
            409,
        )

        run = world.read_run()
        assert run["status"] == RunStatus.SCHEDULED.value
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(67.500, abs=0.0005)


class TestSiloCeilingAtCrediting:
    """The silo constraint bites when the yield is credited, not when the batch is
    planned or fed."""

    def test_a_fifty_ton_silo_calcines_a_seventy_seven_ton_batch_and_refuses_the_sample(
        self, api: ApiClient
    ) -> None:
        """The batch stays CALCINING, the flag stays PENDING and the silo stays empty.

        PRD: "Completion is gated on the silo having room: if the plant's `stucco_on_hand_tons` plus this batch's `stucco_yield_actual_tons`, rounded half-up to three decimals, would exceed `stucco_silo_capacity_tons`, the request is refused with `ERR_SILO_CAPACITY_EXCEEDED`; a total exactly equal to capacity is accepted."

        Design: Corner/errors/batch_yield_larger_than_the_silo_is_refused_at_the_stucco_test
        """
        plant = fixtures.create_plant(
            api, code="GYP-3", name="Cheyenne Wallboard", stucco_silo_capacity_tons=50
        )
        lot = fixtures.synthetic_lot(
            api,
            plant["id"],
            free_moisture_pct=10.0,
            purity_pct=90.0,
            chloride_ppm=100,
            supplier_name="Pawnee FGD",
            received_tons=100.0,
        )
        batch = fixtures.create_batch(api, plant["id"])
        fixtures.feed(api, batch["id"], lot["id"], 100.0, 10.0)
        closed = fixtures.close_feed(api, batch["id"])
        assert closed["stucco_yield_plan_tons"] == pytest.approx(77.340, abs=0.0005), (
            "feeding a batch whose yield cannot fit is entirely legal"
        )

        validate_error(
            api.create_stucco_test(
                batch["id"], factories.stucco_test_payload(), test_users.QUALITY_INSPECTOR
            ),
            ApiErrorId.SILO_CAPACITY_EXCEEDED.value,
            409,
        )

        after = fixtures.read_batch(api, batch["id"])
        assert after["status"] == BatchStatus.CALCINING.value
        assert after["stucco_quality_flag"] == StuccoQualityFlag.PENDING.value
        assert after["stucco_yield_actual_tons"] == pytest.approx(0.000, abs=0.0005)

        _, meta = validate_paginated(
            api.list_stucco_tests(test_users.QUALITY_INSPECTOR, params={"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 0, "the refused sample was not recorded"

        refreshed = fixtures.read_plant(api, plant["id"])
        assert refreshed["stucco_on_hand_tons"] == pytest.approx(0.000, abs=0.0005)
        assert refreshed["production_posture"] == ProductionPosture.RESTRICTED.value


class TestLotBalanceNotOriginalSize:
    """The tonnage check reads `remaining_tons`, so a draw well under the lot's original
    size can still be refused."""

    def test_fifty_tons_is_refused_on_a_forty_ton_balance_and_forty_tons_succeeds(
        self, api: ApiClient
    ) -> None:
        """The refused feed leaves the lot's version alone, so the same guard value is reused.

        PRD: "A feed is subject to five preconditions, and they hold identically for the first feed and for every subsequent one: the lot's `status` must be `APPROVED` or the request fails with `ERR_LOT_NOT_APPROVED`; the lot must belong to the same plant as the batch or the request fails with `ERR_PLANT_SCOPE_MISMATCH`; the lot's assay must still be current, meaning the logical clock must be no more than 30 days past the lot's `assayed_at`, or the request fails with `ERR_ASSAY_EXPIRED`; the `expected_lot_version` must equal the lot's current `version` or the request fails with `ERR_STALE_LOT_VERSION`; and `tons_fed` must not exceed the lot's `remaining_tons` or the request fails with `ERR_LOT_TONS_INSUFFICIENT`."

        Design: Corner/errors/feeding_more_tons_than_the_lot_still_holds
        """
        world = fixtures.compact_batch_world(api, tons_fed=60.0, received_tons=100.0, close=False)
        drawn = world.read_lot_a()
        assert drawn["remaining_tons"] == pytest.approx(40.000, abs=0.0005)
        assert drawn["received_tons"] == pytest.approx(100.000, abs=0.0005)

        validate_error(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(world.lot_a_id, 50.0, 10.0, drawn["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.LOT_TONS_INSUFFICIENT.value,
            409,
        )

        accepted = validate_success(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(world.lot_a_id, 40.0, 10.0, drawn["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            201,
        )
        assert accepted["tons_fed"] == pytest.approx(40.000, abs=0.0005), (
            "the rejected call was not a mutation, so the guard value still matched"
        )

        lot = world.read_lot_a()
        assert lot["remaining_tons"] == pytest.approx(0.000, abs=0.0005)
        assert lot["status"] == LotStatus.DEPLETED.value

        batch = world.read_batch()
        assert batch["feed_tons_total"] == pytest.approx(100.000, abs=0.0005)
        assert batch["status"] == BatchStatus.FEEDING.value


class TestEmptySpecimenSet:
    """Zero specimens has its own code, distinct both from the generic state error and
    from the too-few-specimens error."""

    def test_an_evaluation_with_no_specimens_is_its_own_documented_exception(
        self, api: ApiClient
    ) -> None:
        """The run keeps its completed volume and its untested quality dimension.

        PRD: "First, the run must have at least one specimen: a run whose `quality_state` is still `UNTESTED`, which is exactly the condition `specimen_count` equal to 0, is refused with `ERR_NO_BOARD_TEST_SPECIMENS` rather than with the generic invalid-state error."

        Design: Corner/errors/quality_evaluation_with_no_specimens_returns_its_own_code
        """
        world = fixtures.completed_run(api)
        assert world.read_run()["specimen_count"] == 0

        error = validate_error(
            api.evaluate_quality(world.run_id, {}, test_users.QUALITY_INSPECTOR),
            ApiErrorId.NO_BOARD_TEST_SPECIMENS.value,
            422,
        )
        assert error["error_id"] != ApiErrorId.INVALID_STATE.value
        assert error["error_id"] != ApiErrorId.INSUFFICIENT_SPECIMENS.value, (
            "the too-few code belongs to one or two specimens, not to none"
        )

        run = world.read_run()
        assert run["quality_state"] == QualityState.UNTESTED.value
        assert run["specimen_count"] == 0
        assert run["saleable_grade"] == SaleableGrade.UNGRADED.value
        assert run["status"] == RunStatus.COMPLETED.value
        assert run["available_msf"] == pytest.approx(290.000, abs=0.0005)


class TestFireRatedChangeoverBuffer:
    """The buffer is the matrix figure for this specific SKU pair, and the comparison is
    inclusive at the exact figure."""

    def test_a_sixty_minute_gap_is_short_of_the_purge_but_a_hundred_and_thirty_five_is_not(
        self, api: ApiClient
    ) -> None:
        """A gap that would have been ample for another REGULAR run breaks a fire-rated switch.

        PRD: "If there is a predecessor and `gap_minutes` is strictly less than `changeover_minutes`, the schedule is refused with `ERR_CHANGEOVER_BUFFER_VIOLATION`; a gap exactly equal to the required changeover is acceptable."

        Design: Corner/errors/fire_rated_run_too_soon_after_a_standard_run_breaks_the_changeover_buffer
        """
        world = fixtures.scheduled_run(api, requested_planned_msf=100.0)
        before = world.read_plant()
        assert before["stucco_available_tons"] == pytest.approx(137.030, abs=0.0005)
        assert before["production_posture"] == ProductionPosture.OPEN.value, (
            "an OPEN plant may schedule a fire-rated SKU, so the posture gate is silent here"
        )

        too_soon = fixtures.draft_run(
            api,
            world,
            spec_id=world.spec_tx_id,
            window_start="2026-08-03T11:00:00Z",
            window_end="2026-08-03T15:00:00Z",
            requested_planned_msf=100.0,
            line_speed_fpm=380,
            paper_tension_lb=40.0,
            kiln_dwell_minutes=50,
        )
        error = validate_error(
            api.schedule_run(
                too_soon["id"],
                factories.schedule_payload(before["version"]),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.CHANGEOVER_BUFFER_VIOLATION.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.LINE_WINDOW_CONFLICT.value, (
            "the two windows do not overlap at all"
        )
        assert error["error_id"] != ApiErrorId.POSTURE_RESTRICTED_FIRE_RATED.value

        assert_no_run_side_effects(world.read_run(too_soon["id"]), RunStatus.DRAFT.value)
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(67.500, abs=0.0005)

        far_enough = fixtures.draft_run(
            api,
            world,
            spec_id=world.spec_tx_id,
            window_start="2026-08-03T12:15:00Z",
            window_end="2026-08-03T16:15:00Z",
            requested_planned_msf=100.0,
            line_speed_fpm=380,
            paper_tension_lb=40.0,
            kiln_dwell_minutes=50,
        )
        scheduled = fixtures.schedule(api, far_enough["id"], world.plant_id)

        assert_production_run(scheduled)
        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["prior_run_id"] == world.run_id
        assert scheduled["gap_minutes"] == 135
        assert scheduled["changeover_minutes"] == 135, (
            "110 minutes for the family and thickness switch plus a 25-minute fire-rated purge"
        )
        assert scheduled["in_window_changeover_minutes"] == 0, "a warm start absorbs nothing"
        assert scheduled["stucco_reserved_tons"] == pytest.approx(91.000, abs=0.0005)
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(158.500, abs=0.0005)
