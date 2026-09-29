"""Declared transitions and the states from which they are not declared: batch
creation, the outage walk, the two closed doors on a CALCINING batch, the window
gate on a start, two terminal states and the two system-driven transitions.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    BoardLineStatus,
    LoadOrderStatus,
    LotStatus,
    OutageStatus,
    ProductionPosture,
    QualityState,
    RunStatus,
    SaleableGrade,
    StuccoQualityFlag,
    assert_calciner_batch,
    assert_maintenance_outage,
    assert_production_run,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


def _line_status(api: ApiClient, line_id: str) -> str:
    return validate_success(api.get_board_line(line_id, test_users.PLANT_ADMIN))["status"]


class TestCalcinerBatchEntryAndClosedDoors:
    """A batch is born PLANNED, and once the feed side has closed both the feed and the
    close transition are gone."""

    def test_a_new_batch_starts_planned_with_a_pending_flag(self, api: ApiClient) -> None:
        """Every accumulator is zeroed and no other status is reachable at creation.

        PRD: "A batch that survives the test is created in `status` `PLANNED` with `stucco_quality_flag` at `PENDING`, `feed_tons_total` at `0.000`, and `abort_reason` null."

        Design: Corner/state_machines/new_calciner_batch_starts_planned_with_pending_flag
        """
        plant = fixtures.create_plant(api)

        batch = validate_success(
            api.create_calciner_batch(
                factories.calciner_batch_payload(
                    plant["id"],
                    target_stucco_tons=80.0,
                    feed_rate_tph=25.0,
                    feed_window_start="2026-08-02T08:00:00Z",
                    feed_window_end="2026-08-02T12:00:00Z",
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            201,
        )

        assert_calciner_batch(batch)
        assert batch["status"] == BatchStatus.PLANNED.value
        assert batch["stucco_quality_flag"] == StuccoQualityFlag.PENDING.value
        assert batch["feed_tons_total"] == pytest.approx(0.000, abs=0.0005)
        assert batch["stucco_yield_plan_tons"] == pytest.approx(0.000, abs=0.0005)
        assert batch["stucco_yield_actual_tons"] == pytest.approx(0.000, abs=0.0005)
        assert batch["abort_reason"] is None
        assert batch["version"] == 1
        assert fixtures.read_plant(api, plant["id"])["stucco_on_hand_tons"] == pytest.approx(
            0.000, abs=0.0005
        ), "a planned batch credits nothing to the silo"

    def test_a_feed_on_a_calcining_batch_is_refused_without_touching_the_lot(
        self, api: ApiClient
    ) -> None:
        """Every other precondition passes; only the batch state closes the door.

        PRD: "Closing stamps `feed_purity_plan_pct` and the planned yield, and thereafter no further feed is accepted; a feed attempted on a `CALCINING` batch is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/feed_after_close_feed_returns_invalid_state
        """
        world = fixtures.compact_batch_world(api)
        spare = fixtures.natural_lot(api, world.plant_id, received_tons=50.0)
        assert spare["status"] == LotStatus.APPROVED.value, "tonnage is never the constraint here"

        validate_error(
            api.create_batch_feed(
                world.batch_id,
                factories.batch_feed_payload(spare["id"], 20.0, 2.6, spare["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.INVALID_STATE.value,
            409,
        )

        batch = world.read_batch()
        assert batch["status"] == BatchStatus.CALCINING.value
        assert batch["feed_tons_total"] == pytest.approx(100.000, abs=0.0005)
        assert batch["stucco_yield_plan_tons"] == pytest.approx(77.340, abs=0.0005)

        lot = fixtures.read_lot(api, spare["id"])
        assert lot["consumed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert lot["remaining_tons"] == pytest.approx(50.000, abs=0.0005)
        assert lot["status"] == LotStatus.APPROVED.value

        _, meta = validate_paginated(
            api.list_batch_feeds_of_batch(world.batch_id, test_users.MATERIALS_CONTROLLER)
        )
        assert meta["total_count"] == 1, "only the original feed exists"

    def test_a_second_close_feed_is_refused_without_re_stamping_the_yield(
        self, api: ApiClient
    ) -> None:
        """Replaying the close is a state error, not a silent recomputation.

        PRD: "It requires the batch to be in `FEEDING` — otherwise `ERR_INVALID_STATE` — and requires `feed_tons_total` to be greater than zero, so an empty batch cannot be closed."

        Design: Corner/state_machines/second_close_feed_returns_invalid_state_without_recomputing
        """
        world = fixtures.compact_batch_world(api)
        before = world.read_batch()
        assert before["status"] == BatchStatus.CALCINING.value

        validate_error(
            api.close_feed(world.batch_id, {}, test_users.MATERIALS_CONTROLLER),
            ApiErrorId.INVALID_STATE.value,
            409,
        )

        after = world.read_batch()
        assert after["status"] == BatchStatus.CALCINING.value
        assert after["stucco_yield_plan_tons"] == pytest.approx(77.340, abs=0.0005)
        assert after["feed_moisture_plan_pct"] == pytest.approx(10.00, abs=0.005)
        assert after["feed_purity_plan_pct"] == pytest.approx(90.00, abs=0.005)
        assert after["version"] == before["version"], (
            "a rejected call is not a mutation of the batch"
        )


class TestOutageLifecycleWalk:
    """Propose, approve, start and close, with the line stepping through its three
    maintenance states."""

    def test_the_outage_walk_moves_the_line_through_all_three_transitions(
        self, api: ApiClient
    ) -> None:
        """An October window walks PROPOSED to CLOSED and returns the line to AVAILABLE.

        PRD: "A new line's `status` is `AVAILABLE`, and it moves only under maintenance control: `AVAILABLE → MAINTENANCE_SCHEDULED` when an outage on it is approved, `MAINTENANCE_SCHEDULED → UNDER_MAINTENANCE` when that outage starts, and `UNDER_MAINTENANCE → AVAILABLE` when it closes."

        Design: Corner/state_machines/outage_lifecycle_propose_approve_start_close_walks_all_transitions
        """
        world = fixtures.baseline(api)

        proposed = fixtures.propose_outage(api, world.line_id)
        assert_maintenance_outage(proposed)
        assert proposed["status"] == OutageStatus.PROPOSED.value
        assert proposed["seasonality_index"] == pytest.approx(0.90, abs=0.005)
        assert proposed["planned_downtime_hours"] == pytest.approx(48.00, abs=0.005)
        assert proposed["at_risk_msf"] == pytest.approx(0.000, abs=0.0005), (
            "this plant has no runs at all"
        )
        assert proposed["opportunity_cost_usd"] == pytest.approx(0.00, abs=0.005)
        assert proposed["deferral_count"] == 0
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value

        approved = fixtures.approve_outage(api, proposed["id"])
        assert approved["status"] == OutageStatus.APPROVED.value
        assert approved["approved_by_user_id"] == test_users.USER_MANAGER
        assert _line_status(api, world.line_id) == BoardLineStatus.MAINTENANCE_SCHEDULED.value

        fixtures.set_clock(api, "2026-10-05T06:00:00Z")
        started = fixtures.start_outage(api, proposed["id"])
        assert started["status"] == OutageStatus.IN_PROGRESS.value
        assert _line_status(api, world.line_id) == BoardLineStatus.UNDER_MAINTENANCE.value

        fixtures.set_clock(api, "2026-10-07T06:00:00Z")
        closed = fixtures.close_outage(api, proposed["id"])
        assert closed["status"] == OutageStatus.CLOSED.value
        assert closed["close_note"] == "burner and drive replaced"
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value
        assert closed["version"] == 4, "propose, approve, start and close are four writes"

        plant = fixtures.read_plant(api, world.plant_id)
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value, (
            "the empty silo decides the re-derived posture once the outage is closed"
        )


class TestRunWindowGateAndTerminalStatus:
    """The clock gate on a start, and the two calls a CANCELLED run refuses."""

    def test_a_start_one_step_before_the_window_is_refused_then_allowed(
        self, api: ApiClient
    ) -> None:
        """The clock decides: reaching `window_start` exactly is sufficient.

        PRD: "The logical clock must have reached the run's `window_start`, or the request fails with `ERR_RUN_WINDOW_NOT_STARTED` — reaching the instant exactly is sufficient."

        Design: Corner/state_machines/start_run_before_window_returns_run_window_not_started
        """
        world = fixtures.scheduled_run(api)

        validate_error(
            api.start_run(world.run_id, {}, test_users.PRODUCTION_SCHEDULER),
            ApiErrorId.RUN_WINDOW_NOT_STARTED.value,
            409,
        )

        refused = world.read_run()
        assert refused["status"] == RunStatus.SCHEDULED.value
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)

        fixtures.set_clock(api, "2026-08-03T06:00:00Z")
        started = fixtures.start(api, world.run_id)

        assert_production_run(started)
        assert started["status"] == RunStatus.RUNNING.value
        assert world.read_plant()["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005), (
            "the reservation stays committed across the start"
        )
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value, (
            "a running run does not change the line's maintenance status"
        )

    def test_a_cancelled_run_refuses_both_start_and_complete(self, api: ApiClient) -> None:
        """The window is open and the tonnage is back, but the status dimension is closed.

        PRD: "`COMPLETED` and `CANCELLED` are the lifecycle dimension's terminal states."

        Design: Corner/state_machines/cancelled_run_cannot_be_started_or_completed
        """
        world = fixtures.scheduled_run(api)
        fixtures.cancel_run(api, world.run_id)
        fixtures.set_clock(api, "2026-08-03T06:00:00Z")

        validate_error(
            api.start_run(world.run_id, {}, test_users.PRODUCTION_SCHEDULER),
            ApiErrorId.INVALID_STATE.value,
            409,
        )
        validate_error(
            api.complete_run(
                world.run_id, factories.complete_run_payload(), test_users.PRODUCTION_SCHEDULER
            ),
            ApiErrorId.INVALID_STATE.value,
            409,
        )

        run = world.read_run()
        assert run["status"] == RunStatus.CANCELLED.value
        assert run["cancel_reason"] == "customer order pulled"
        assert run["actual_msf"] == pytest.approx(0.000, abs=0.0005)

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.OPEN.value
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value


class TestTerminalLoadAndSystemDrivenTransitions:
    """A shipped trailer, a lot that depletes itself mid-request, and the completion that
    moves two plant counters at once."""

    def test_a_shipped_load_order_refuses_cancellation(self, api: ApiClient) -> None:
        """The 11.520 MSF stays committed because the cancel transition is not declared.

        PRD: "From `SHIPPED` or `CANCELLED` the request is refused with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/shipped_load_order_cannot_be_cancelled
        """
        world = fixtures.released_run_with_load(api, bundles_count=5)
        fixtures.record_load(api, world.load_id, 5)
        shipped = fixtures.ship_load(api, world.load_id, backhaul=False)
        assert shipped["status"] == LoadOrderStatus.SHIPPED.value

        validate_error(
            api.cancel_load_order(
                world.load_id,
                factories.cancel_load_payload(cancel_reason="customer refused delivery"),
                test_users.PRODUCTION_SCHEDULER,
            ),
            ApiErrorId.INVALID_STATE.value,
            409,
        )

        load = world.read_load()
        assert load["status"] == LoadOrderStatus.SHIPPED.value
        assert load["cancel_reason"] is None
        assert load["total_msf"] == pytest.approx(11.520, abs=0.0005)
        assert load["trailer_weight_lb"] == pytest.approx(18432.00, abs=0.005)
        assert load["quoted_freight_usd"] == pytest.approx(425.00, abs=0.005)
        assert load["settled_freight_usd"] == pytest.approx(425.00, abs=0.005)
        assert load["freight_variance_usd"] == pytest.approx(0.00, abs=0.005)

        assert world.read_run()["available_msf"] == pytest.approx(278.480, abs=0.0005), (
            "the rejected cancel handed nothing back"
        )

    def test_a_lot_depletes_inside_the_feed_and_then_refuses_the_next_one(
        self, api: ApiClient
    ) -> None:
        """Depletion has no endpoint of its own; the next feed fails on status, not tonnage.

        PRD: "A lot moves `APPROVED → DEPLETED` at the moment a feed draws it down so that `received_tons` minus `consumed_tons`, rounded half-up to 3 decimals, equals exactly `0.000`; from `DEPLETED` no further feed is accepted, and one attempted anyway is refused with `ERR_LOT_NOT_APPROVED`."

        Design: Corner/state_machines/lot_auto_depletes_when_fully_drawn_and_refuses_further_feeds
        """
        world = fixtures.compact_batch_world(api, tons_fed=100.0, received_tons=100.0, close=False)

        drawn = world.read_lot_a()
        assert drawn["status"] == LotStatus.DEPLETED.value
        assert drawn["consumed_tons"] == pytest.approx(100.000, abs=0.0005)
        assert drawn["remaining_tons"] == pytest.approx(0.000, abs=0.0005)
        assert drawn["version"] == 3, "receipt, assay, then the feed that depleted it"

        second_batch = fixtures.create_batch(
            api,
            world.plant_id,
            target_stucco_tons=40.0,
            feed_rate_tph=20.0,
            feed_window_start="2026-08-02T12:00:00Z",
            feed_window_end="2026-08-02T16:00:00Z",
        )

        validate_error(
            api.create_batch_feed(
                second_batch["id"],
                factories.batch_feed_payload(world.lot_a_id, 10.0, 10.0, drawn["version"]),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.LOT_NOT_APPROVED.value,
            409,
        )

        after = fixtures.read_batch(api, second_batch["id"])
        assert after["status"] == BatchStatus.PLANNED.value
        assert after["feed_tons_total"] == pytest.approx(0.000, abs=0.0005)

        _, meta = validate_paginated(
            api.list_batch_feeds(
                test_users.MATERIALS_CONTROLLER, params={"lot_id": world.lot_a_id}
            )
        )
        assert meta["total_count"] == 1, "the lot was drawn from exactly once"

    def test_completion_releases_the_reservation_and_charges_the_silo_at_once(
        self, api: ApiClient
    ) -> None:
        """Two plant counters move in opposite directions in the same write.

        PRD: "On the plant side, the run's `stucco_reserved_tons` is subtracted from `stucco_committed_tons`, `stucco_consumed_tons` is subtracted from `stucco_on_hand_tons`, `stucco_available_tons` and `production_posture` are re-derived, and the plant's `version` increments by 1."

        Design: Corner/state_machines/complete_run_debits_silo_and_releases_commitment_in_one_write
        """
        world = fixtures.running_run(api)

        completed = validate_success(
            api.complete_run(
                world.run_id, factories.complete_run_payload(), test_users.PRODUCTION_SCHEDULER
            ),
            200,
        )

        assert completed["status"] == RunStatus.COMPLETED.value
        assert completed["actual_msf"] == pytest.approx(295.000, abs=0.0005)
        assert completed["scrap_msf"] == pytest.approx(5.000, abs=0.0005)
        assert completed["stucco_consumed_tons"] == pytest.approx(199.125, abs=0.0005), (
            "295.000 MSF at 1350 pounds each is 199.125 tons, and scrap is not charged"
        )
        assert completed["net_good_msf"] == pytest.approx(290.000, abs=0.0005)
        assert completed["available_msf"] == pytest.approx(290.000, abs=0.0005)
        assert completed["quality_state"] == QualityState.UNTESTED.value, (
            "the quality dimension is untouched by completion"
        )
        assert completed["saleable_grade"] == SaleableGrade.UNGRADED.value

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["stucco_on_hand_tons"] == pytest.approx(5.405, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(5.405, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value
        assert _line_status(api, world.line_id) == BoardLineStatus.AVAILABLE.value
