"""Three quantities that must survive a forward move and its compensating reversal:
silo stucco across schedule then cancel, raw gypsum across feed then abort, and
saleable board volume across staging then load cancellation.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    BatchStatus,
    LoadOrderStatus,
    LotStatus,
    ProductionPosture,
    RunStatus,
    assert_calciner_batch,
    assert_gypsum_lot,
    assert_lot_mass_conservation,
    assert_run_msf_conservation,
    assert_silo_identity,
    fixtures,
    test_users,
    validate_paginated,
)


class TestStuccoCommitmentConservation:
    """Scheduling moves 202.500 tons from available into committed and cancelling has
    to move exactly that back, leaving only the version counter advanced."""

    @staticmethod
    def _drafted_three_hundred_msf(api: ApiClient):
        """B1 crediting 204.530 tons with R1 drafted for 300.000 MSF and nothing committed."""
        world = fixtures.baseline_with_stucco(api)
        world.run = fixtures.draft_run(api, world, requested_planned_msf=300.0)
        return world

    def test_scheduling_debits_available_by_exactly_the_reservation(
        self, api: ApiClient
    ) -> None:
        """The 202.500-ton reservation leaves available and appears in committed intact.

        PRD: "`stucco_committed_tons` is the sum of `stucco_reserved_tons` across every production run of that plant whose `status` is `SCHEDULED` or `RUNNING`."

        Design: Difficulty/compensating_invariant/stucco_commitment_conservation_across_schedule_cancel
        """
        world = self._drafted_three_hundred_msf(api)

        before = world.read_plant()
        assert before["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005)
        assert before["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005), (
            "a draft reserves nothing"
        )
        assert before["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005)
        assert_silo_identity(before)

        scheduled = fixtures.schedule(api, world.run_id, world.plant_id)
        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["effective_planned_msf"] == pytest.approx(300.000, abs=0.0005)
        assert scheduled["stucco_reserved_tons"] == pytest.approx(202.500, abs=0.0005), (
            "300.000 MSF at 1350 pounds a MSF is 202.500 tons"
        )

        after = world.read_plant()
        assert after["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005), (
            "a reservation moves nothing physical"
        )
        assert after["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)
        assert after["stucco_available_tons"] == pytest.approx(2.030, abs=0.0005)
        assert after["production_posture"] == ProductionPosture.RESTRICTED.value
        assert_silo_identity(after)

    def test_cancelling_returns_the_reservation_to_the_penny(self, api: ApiClient) -> None:
        """The ledger comes back to its pre-schedule values while the version advances.

        PRD: "Every path that removes a run from the committed set puts its reservation back: an operator cancelling a `SCHEDULED` run, a cascade cancelling a `SCHEDULED` run because an outage was approved, and a run completing all subtract that run's `stucco_reserved_tons` from `stucco_committed_tons`."

        Design: Difficulty/compensating_invariant/stucco_commitment_conservation_across_schedule_cancel
        """
        world = self._drafted_three_hundred_msf(api)
        fixtures.schedule(api, world.run_id, world.plant_id)
        after_schedule = world.read_plant()
        assert after_schedule["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)

        cancelled = fixtures.cancel_run(api, world.run_id)

        assert cancelled["status"] == RunStatus.CANCELLED.value
        assert cancelled["stucco_reserved_tons"] == pytest.approx(0.000, abs=0.0005), (
            "cancelling zeroes the run's own reservation"
        )
        assert cancelled["cancel_reason"] == "customer order pulled"

        restored = world.read_plant()
        assert restored["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005)
        assert restored["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert restored["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005), (
            "the silo balance is bit-for-bit what it was before the schedule"
        )
        assert restored["production_posture"] == ProductionPosture.OPEN.value
        assert_silo_identity(restored)
        assert restored["version"] > after_schedule["version"], (
            "releasing the reservation is a second plant mutation"
        )


class TestGypsumMassConservationAcrossAbort:
    """Aborting a CALCINING batch hands every fed tonne back to its lot, which drags a
    fully drawn lot back out of DEPLETED."""

    @staticmethod
    def _calcining_batch_over_a_depleted_lot(api: ApiClient):
        """B3 fed all 40.000 tons of lot C plus 20.000 tons of lot B, then closed."""
        world = fixtures.baseline_with_stucco(api)
        lot_c = fixtures.natural_lot(api, world.plant_id, received_tons=40.0)
        batch_3 = fixtures.create_batch(
            api,
            world.plant_id,
            target_stucco_tons=50.0,
            feed_rate_tph=20.0,
            feed_window_start="2026-08-02T15:00:00Z",
            feed_window_end="2026-08-02T19:00:00Z",
        )
        fixtures.feed(api, batch_3["id"], lot_c["id"], 40.0, 2.6)
        fixtures.feed(api, batch_3["id"], world.lot_b_id, 20.0, 3.1)
        world.batch_2 = fixtures.close_feed(api, batch_3["id"])
        return world, lot_c["id"], batch_3["id"]

    def test_the_abort_restores_every_tonne_and_revives_the_depleted_lot(
        self, api: ApiClient
    ) -> None:
        """Lot C returns DEPLETED -> APPROVED with its full 40.000 tons back on the books.

        PRD: "An abort from `FEEDING` or `CALCINING` additionally unwinds every feed: for each feed row the source lot's `consumed_tons` decreases by that feed's `tons_fed`, its `remaining_tons` is recomputed, its `version` increments by 1, and a lot that had been `DEPLETED` returns to `APPROVED` whenever the restoration leaves `remaining_tons` strictly above `0.000`."

        Design: Difficulty/compensating_invariant/gypsum_mass_conservation_across_feed_abort
        """
        world, lot_c_id, batch_3_id = self._calcining_batch_over_a_depleted_lot(api)

        before_c = fixtures.read_lot(api, lot_c_id)
        assert before_c["status"] == LotStatus.DEPLETED.value, (
            "the draw took remaining_tons to exactly 0.000"
        )
        assert before_c["consumed_tons"] == pytest.approx(40.000, abs=0.0005)
        assert before_c["remaining_tons"] == pytest.approx(0.000, abs=0.0005)

        before_b = fixtures.read_lot(api, world.lot_b_id)
        assert before_b["consumed_tons"] == pytest.approx(100.000, abs=0.0005), (
            "80.000 tons in the first batch and 20.000 in this one"
        )
        assert before_b["remaining_tons"] == pytest.approx(100.000, abs=0.0005)
        assert fixtures.read_batch(api, batch_3_id)["feed_tons_total"] == pytest.approx(
            60.000, abs=0.0005
        )

        aborted = fixtures.abort_batch(api, batch_3_id)
        assert aborted["status"] == BatchStatus.ABORTED.value
        assert aborted["abort_reason"] == "calciner ring gear failure"

        after_c = fixtures.read_lot(api, lot_c_id)
        assert_gypsum_lot(after_c)
        assert after_c["status"] == LotStatus.APPROVED.value, (
            "DEPLETED is escapable by exactly this compensating route"
        )
        assert after_c["consumed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert after_c["remaining_tons"] == pytest.approx(40.000, abs=0.0005)

        after_b = fixtures.read_lot(api, world.lot_b_id)
        assert after_b["consumed_tons"] == pytest.approx(80.000, abs=0.0005), (
            "only this batch's 20.000 tons came back; the completed batch's draw stands"
        )
        assert after_b["remaining_tons"] == pytest.approx(120.000, abs=0.0005)

        after_a = fixtures.read_lot(api, world.lot_a_id)
        assert after_a["consumed_tons"] == pytest.approx(180.000, abs=0.0005), (
            "lot A never fed the aborted batch and is untouched"
        )
        assert after_a["remaining_tons"] == pytest.approx(120.000, abs=0.0005)

        for lot in (after_a, after_b, after_c):
            assert_lot_mass_conservation(lot)

    def test_the_aborted_batch_zeroes_its_own_figures_and_keeps_its_feed_rows(
        self, api: ApiClient
    ) -> None:
        """Blend and yield collapse to 0.000, the silo is untouched, the history stays.

        PRD: "The feed rows themselves are retained — they are append-only history — but because the batch is now `ABORTED` they no longer count toward any lot's consumption or any blend metric."

        Design: Difficulty/compensating_invariant/gypsum_mass_conservation_across_feed_abort
        """
        world, _, batch_3_id = self._calcining_batch_over_a_depleted_lot(api)
        before_plant = world.read_plant()
        assert before_plant["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005)

        fixtures.abort_batch(api, batch_3_id)

        batch = fixtures.read_batch(api, batch_3_id)
        assert_calciner_batch(batch)
        assert batch["feed_tons_total"] == pytest.approx(0.000, abs=0.0005)
        assert batch["stucco_yield_plan_tons"] == pytest.approx(0.000, abs=0.0005), (
            "the planned yield stamped when the feed side closed is wound back"
        )
        assert batch["stucco_yield_actual_tons"] == pytest.approx(0.000, abs=0.0005)

        plant = world.read_plant()
        assert plant["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005), (
            "the aborted batch never reached COMPLETED, so it never credited the silo"
        )
        assert_silo_identity(plant)

        _, meta = validate_paginated(
            api.list_batch_feeds_of_batch(batch_3_id, test_users.MATERIALS_CONTROLLER)
        )
        assert meta["total_count"] == 2, "both feed rows of the aborted batch survive"


class TestBoardMsfConservationAcrossLoadCancel:
    """Two loads debit the run twice; cancelling one credits back exactly its own
    volume and leaves the survivor's committed."""

    @staticmethod
    def _run_with_two_staged_loads(api: ApiClient):
        """290.000 net good MSF with a 12-bundle and a 5-bundle order against it."""
        world = fixtures.completed_run(api)
        world.load = fixtures.stage_load(api, world, bundles_count=12)
        world.load_2 = fixtures.stage_load(api, world, bundles_count=5)
        return world

    def test_two_staged_loads_debit_the_run_by_their_combined_volume(
        self, api: ApiClient
    ) -> None:
        """27.648 plus 11.520 MSF comes off the run's 290.000 available.

        PRD: "Finished board volume follows the same discipline: a run's `available_msf` is its `net_good_msf` less the `total_msf` of every load order against it whose `status` is `STAGED`, `HELD`, `LOADED` or `SHIPPED`, so cancelling a load returns its volume to the run."

        Design: Difficulty/compensating_invariant/board_msf_conservation_across_load_stage_cancel
        """
        world = fixtures.completed_run(api)

        completed = world.read_run()
        assert completed["net_good_msf"] == pytest.approx(290.000, abs=0.0005)
        assert completed["available_msf"] == pytest.approx(290.000, abs=0.0005)
        assert_run_msf_conservation(completed, 0.0)

        first = fixtures.stage_load(api, world, bundles_count=12)
        second = fixtures.stage_load(api, world, bundles_count=5)

        assert first["total_msf"] == pytest.approx(27.648, abs=0.0005)
        assert second["total_msf"] == pytest.approx(11.520, abs=0.0005)
        assert second["quoted_freight_usd"] == pytest.approx(425.00, abs=0.005), (
            "the five-bundle charge falls under the market's minimum charge"
        )

        run = world.read_run()
        assert run["available_msf"] == pytest.approx(250.832, abs=0.0005), (
            "290.000 less 27.648 and 11.520"
        )
        assert_run_msf_conservation(run, 27.648 + 11.520)

    def test_cancelling_one_load_returns_only_its_own_volume(self, api: ApiClient) -> None:
        """The 27.648 MSF comes back and the surviving order keeps its 11.520 committed.

        PRD: "Cancelling a load order is permitted from `STAGED`, `HELD` or `LOADED`, and from all three it behaves identically: a free-text `cancel_reason` is recorded, the order moves to the terminal `CANCELLED` state, its `total_msf` is released so that the source run's `available_msf` increases by that amount, and the order's `version` increments by 1."

        Design: Difficulty/compensating_invariant/board_msf_conservation_across_load_stage_cancel
        """
        world = self._run_with_two_staged_loads(api)
        assert world.read_run()["available_msf"] == pytest.approx(250.832, abs=0.0005)

        cancelled = fixtures.cancel_load(api, world.load_id)

        assert cancelled["status"] == LoadOrderStatus.CANCELLED.value
        assert cancelled["cancel_reason"] == "distributor rescheduled the delivery"
        assert cancelled["total_msf"] == pytest.approx(27.648, abs=0.0005), (
            "the cancelled order still reports the volume it once held"
        )

        survivor = fixtures.read_load(api, world.load_2["id"])
        assert survivor["status"] == LoadOrderStatus.STAGED.value
        assert survivor["total_msf"] == pytest.approx(11.520, abs=0.0005)

        run = world.read_run()
        assert run["net_good_msf"] == pytest.approx(290.000, abs=0.0005)
        assert run["available_msf"] == pytest.approx(278.480, abs=0.0005), (
            "250.832 plus the 27.648 released by the cancellation"
        )
        assert_run_msf_conservation(run, 11.520)
