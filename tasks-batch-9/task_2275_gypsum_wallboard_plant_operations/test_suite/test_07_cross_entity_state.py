"""Transitions blocked by the state of a *different* entity, and unblocked by moving
that other entity: a run start waiting on its calciner batch, a shipment waiting on
the run's quality dimension, and an outage start waiting on a running run.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    BoardLineStatus,
    LoadOrderStatus,
    OutageStatus,
    ProductionPosture,
    QualityState,
    RunStatus,
    SaleableGrade,
    assert_maintenance_outage,
    fixtures,
    test_users,
    validate_error,
    validate_success,
)


class TestRunStartWaitsOnTheCalcinerBatch:
    """Scheduling accepted a CALCINING batch; starting insists on COMPLETED, and only
    a passing stucco sample on the batch can supply that."""

    @staticmethod
    def _scheduled_run_on_a_calcining_batch(api: ApiClient):
        """R2 scheduled against B2, which is closed but not yet sampled."""
        world = fixtures.baseline_with_stucco(api)
        batch_2 = fixtures.create_batch(
            api,
            world.plant_id,
            target_stucco_tons=100.0,
            feed_rate_tph=20.0,
            feed_window_start="2026-08-02T15:00:00Z",
            feed_window_end="2026-08-02T19:00:00Z",
        )
        fixtures.feed(api, batch_2["id"], world.lot_a_id, 120.0, 9.4)
        world.batch_2 = fixtures.close_feed(api, batch_2["id"])
        world.run = fixtures.draft_run(
            api, world, batch_id=batch_2["id"], requested_planned_msf=100.0
        )
        world.run = fixtures.schedule(api, world.run_id, world.plant_id)
        fixtures.set_clock(api, "2026-08-03T06:00:00Z")
        return world

    def test_the_start_is_refused_while_the_batch_is_still_calcining(
        self, api: ApiClient
    ) -> None:
        """The clock and the line are both ready; only the batch state blocks the start.

        PRD: "And the stucco must actually exist and be conforming: the calciner batch must have reached `COMPLETED` and its `stucco_quality_flag` must not be `FAIL`, each failure reported as `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/run_start_blocked_until_calciner_batch_completed
        """
        world = self._scheduled_run_on_a_calcining_batch(api)

        assert world.read_batch(world.batch_2["id"])["status"] == BatchStatus.CALCINING.value
        scheduled = world.read_run()
        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005), (
            "100.000 MSF at 1350 pounds each is 67.500 tons"
        )

        validate_error(
            api.start_run(world.run_id, {}, test_users.PRODUCTION_SCHEDULER),
            ApiErrorId.INVALID_STATE.value,
            409,
        )

        after = world.read_run()
        assert after["status"] == RunStatus.SCHEDULED.value, "the run did not move"
        assert after["quality_state"] == QualityState.UNTESTED.value
        assert world.read_batch(world.batch_2["id"])["status"] == BatchStatus.CALCINING.value

    def test_completing_the_batch_lets_the_identical_start_succeed(
        self, api: ApiClient
    ) -> None:
        """A passing sample on the other entity is what unblocks this one.

        PRD: "Note that starting is stricter than scheduling about the batch — scheduling accepts a batch still `CALCINING`, starting does not."

        Design: Difficulty/cross_entity_state_dependency/run_start_blocked_until_calciner_batch_completed
        """
        world = self._scheduled_run_on_a_calcining_batch(api)
        validate_error(
            api.start_run(world.run_id, {}, test_users.PRODUCTION_SCHEDULER),
            ApiErrorId.INVALID_STATE.value,
            409,
        )

        fixtures.record_stucco_test(
            api,
            world.batch_2["id"],
            sample_seq=1,
            combined_water_pct=5.4,
            free_water_pct=0.2,
            set_time_minutes=8.0,
        )

        batch = world.read_batch(world.batch_2["id"])
        assert batch["status"] == BatchStatus.COMPLETED.value
        assert batch["stucco_yield_actual_tons"] == pytest.approx(92.747, abs=0.0005)

        plant = world.read_plant()
        assert plant["stucco_on_hand_tons"] == pytest.approx(297.277, abs=0.0005), (
            "204.530 from the first batch plus 92.747 from the second"
        )
        assert plant["stucco_committed_tons"] == pytest.approx(67.500, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(229.777, abs=0.0005)

        started = fixtures.start(api, world.run_id)
        assert started["status"] == RunStatus.RUNNING.value
        assert started["effective_planned_msf"] == pytest.approx(100.000, abs=0.0005)
        assert started["stucco_reserved_tons"] == pytest.approx(67.500, abs=0.0005), (
            "the reservation stays committed across the start"
        )


class TestShipmentWaitsOnTheRunQualityDimension:
    """A loaded trailer off a COMPLETED run cannot ship while the run's quality
    dimension is UNTESTED, however complete the lifecycle dimension is."""

    @staticmethod
    def _loaded_trailer_on_an_untested_run(api: ApiClient):
        world = fixtures.completed_run(api)
        world.load = fixtures.stage_load(api, world)
        world.load = fixtures.record_load(api, world.load_id, 12)
        return world

    def test_shipping_is_refused_while_the_run_is_untested(self, api: ApiClient) -> None:
        """The quote is stamped but nothing settles while the quality dimension is unmoved.

        PRD: "Beyond requiring the order to be in `LOADED`, shipping enforces the quality chain end to end: the source run's `quality_state` must be `RELEASED` or `DOWNGRADED`, and anything else — `UNTESTED`, `IN_TEST`, `HELD` or `SCRAPPED` — blocks the shipment with `ERR_RUN_QUALITY_NOT_RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/load_ship_blocked_until_run_quality_released
        """
        world = self._loaded_trailer_on_an_untested_run(api)

        run = world.read_run()
        assert run["status"] == RunStatus.COMPLETED.value
        assert run["quality_state"] == QualityState.UNTESTED.value

        validate_error(
            api.ship_load_order(world.load_id, {"backhaul": False}, test_users.PLANT_MANAGER),
            ApiErrorId.RUN_QUALITY_NOT_RELEASED.value,
            409,
        )

        load = world.read_load()
        assert load["status"] == LoadOrderStatus.LOADED.value
        assert load["settled_freight_usd"] is None
        assert load["freight_variance_usd"] is None
        assert load["quoted_freight_usd"] == pytest.approx(756.79, abs=0.005)
        assert load["trailer_weight_lb"] == pytest.approx(44236.80, abs=0.005)
        assert load["total_msf"] == pytest.approx(27.648, abs=0.0005)

    def test_releasing_the_run_lets_the_identical_shipment_settle(
        self, api: ApiClient
    ) -> None:
        """Three specimens and an evaluation on the run are what let the trailer ship.

        PRD: "Shipment stamps `settled_freight_usd`, `overweight_fee_usd` and `freight_variance_usd`, and increments the order's `version`."

        Design: Difficulty/cross_entity_state_dependency/load_ship_blocked_until_run_quality_released
        """
        world = self._loaded_trailer_on_an_untested_run(api)
        validate_error(
            api.ship_load_order(world.load_id, {"backhaul": False}, test_users.PLANT_MANAGER),
            ApiErrorId.RUN_QUALITY_NOT_RELEASED.value,
            409,
        )

        fixtures.record_passing_specimens(api, world.run_id, 3)
        evaluated = fixtures.evaluate(api, world.run_id)
        assert evaluated["quality_state"] == QualityState.RELEASED.value
        assert evaluated["saleable_grade"] == SaleableGrade.FIRST_QUALITY.value

        shipped = fixtures.ship_load(api, world.load_id)

        assert shipped["status"] == LoadOrderStatus.SHIPPED.value
        assert shipped["settled_freight_usd"] == pytest.approx(761.53, abs=0.005)
        assert shipped["overweight_fee_usd"] == pytest.approx(4.74, abs=0.005), (
            "236.80 pounds over the 44000-pound target at two cents a pound"
        )
        assert shipped["freight_variance_usd"] == pytest.approx(4.74, abs=0.005)


class TestOutageStartWaitsOnTheRunningRun:
    """The approval cascade only sweeps DRAFT and SCHEDULED runs, so a RUNNING run
    survives on a MAINTENANCE_SCHEDULED line and blocks the outage from starting."""

    @staticmethod
    def _approved_october_outage_over_a_running_run(api: ApiClient):
        world = fixtures.running_run(api)
        fixtures.approved_outage(api, world)
        fixtures.set_clock(api, "2026-10-05T06:00:00Z")
        return world

    def test_the_outage_start_is_refused_while_a_run_is_running_on_the_line(
        self, api: ApiClient
    ) -> None:
        """The clock is inside the window, but the line still has board on it.

        PRD: "Starting an approved outage moves it `APPROVED → IN_PROGRESS` and requires three things: the outage must be in `APPROVED`; the logical clock must have reached its `window_start`, else `ERR_OUTAGE_WINDOW_NOT_STARTED`; and no production run on the line may be `RUNNING`, else `ERR_RUN_ACTIVE_ON_LINE`."

        Design: Difficulty/cross_entity_state_dependency/outage_start_blocked_while_run_active_on_line
        """
        world = self._approved_october_outage_over_a_running_run(api)

        outage = world.read_outage()
        assert_maintenance_outage(outage)
        assert outage["seasonality_index"] == pytest.approx(0.90, abs=0.005), (
            "October sits exactly on the inclusive seasonality ceiling"
        )
        assert outage["planned_downtime_hours"] == pytest.approx(48.00, abs=0.005)
        assert outage["at_risk_msf"] == pytest.approx(0.000, abs=0.0005), (
            "the August run's window lies outside the October outage window"
        )
        assert outage["opportunity_cost_usd"] == pytest.approx(0.00, abs=0.005)
        assert world.read_run()["status"] == RunStatus.RUNNING.value, (
            "the approval cascade left the running run alone"
        )

        validate_error(
            api.start_outage(world.outage_id, {}, test_users.MAINTENANCE_PLANNER),
            ApiErrorId.RUN_ACTIVE_ON_LINE.value,
            409,
        )

        assert world.read_outage()["status"] == OutageStatus.APPROVED.value
        line = validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))
        assert line["status"] == BoardLineStatus.MAINTENANCE_SCHEDULED.value

    def test_completing_the_run_lets_the_outage_start_and_take_the_line(
        self, api: ApiClient
    ) -> None:
        """Once the run is COMPLETED the same start succeeds and the line goes down.

        PRD: "When the outage's `outage_type` is `EMERGENCY`, starting it also re-derives the plant's `production_posture`, which the emergency condition of §2.9 forces to `FROZEN`, and increments the plant's `version` by 1; a `PLANNED` outage does not freeze the plant."

        Design: Difficulty/cross_entity_state_dependency/outage_start_blocked_while_run_active_on_line
        """
        world = self._approved_october_outage_over_a_running_run(api)
        validate_error(
            api.start_outage(world.outage_id, {}, test_users.MAINTENANCE_PLANNER),
            ApiErrorId.RUN_ACTIVE_ON_LINE.value,
            409,
        )

        completed = fixtures.complete(api, world.run_id)
        assert completed["status"] == RunStatus.COMPLETED.value
        assert completed["net_good_msf"] == pytest.approx(290.000, abs=0.0005)

        started = fixtures.start_outage(api, world.outage_id)
        assert started["status"] == OutageStatus.IN_PROGRESS.value

        line = validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))
        assert line["status"] == BoardLineStatus.UNDER_MAINTENANCE.value

        plant = world.read_plant()
        assert plant["stucco_available_tons"] == pytest.approx(5.405, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value, (
            "the posture reflects the thin silo, not a freeze, because the outage is PLANNED"
        )
