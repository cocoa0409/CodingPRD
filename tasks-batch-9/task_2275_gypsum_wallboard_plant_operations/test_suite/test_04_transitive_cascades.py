"""Two four-hop cascades that each settle inside a single request: a retained
stucco sample failing days after the fact, and an emergency outage approval
sweeping a line clear.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    OUTAGE_CANCEL_REASON_PREFIX,
    ApiClient,
    BatchStatus,
    BoardLineStatus,
    HeldReason,
    HoldSource,
    LoadOrderStatus,
    OutageStatus,
    OutageType,
    ProductionPosture,
    QualityState,
    RunStatus,
    SaleableGrade,
    StuccoQualityFlag,
    assert_load_order,
    assert_maintenance_outage,
    fixtures,
    test_users,
    validate_success,
)


def _released_run_with_two_batches(api: ApiClient):
    """R1 released against B1, with B2 also credited, and one 12-bundle load staged."""
    world = fixtures.baseline_with_stucco(api)
    fixtures.second_batch_completed(api, world)
    return fixtures.released_run_with_load(api, world)


def _failing_retained_sample(api: ApiClient, batch_id: str) -> dict:
    """A second sample on an already-completed batch whose combined water is too low."""
    return fixtures.record_stucco_test(
        api,
        batch_id,
        sample_seq=2,
        headers=test_users.QUALITY_INSPECTOR_2,
        combined_water_pct=3.90,
        free_water_pct=0.22,
        set_time_minutes=7.00,
        normal_consistency_cc=79.0,
    )


class TestRetainedStuccoFailCascade:
    """Batch flag, run quality, plant posture and the staged load all move on one
    laboratory result."""

    def test_the_retained_sample_overwrites_the_flag_of_a_completed_batch(
        self, api: ApiClient
    ) -> None:
        """A FAIL sample on a COMPLETED batch leaves it completed but flags it FAIL.

        PRD: "Whatever the outcome, the batch's `stucco_quality_flag` is overwritten with the new result, so the flag always reflects the most recent sample rather than the best or the worst one."

        Design: Difficulty/transitive_cascade/retained_stucco_fail_cascades_batch_run_plant_load
        """
        world = _released_run_with_two_batches(api)

        sample = _failing_retained_sample(api, world.batch_id)
        assert sample["result"] == "FAIL", "3.90 percent combined water is below the 4.20 floor"
        assert sample["recorded_by_user_id"] == test_users.USER_INSPECTOR_2

        batch = world.read_batch()
        assert batch["status"] == BatchStatus.COMPLETED.value, (
            "a retained sample keeps the batch where it was"
        )
        assert batch["stucco_quality_flag"] == StuccoQualityFlag.FAIL.value
        assert batch["stucco_yield_actual_tons"] == pytest.approx(204.530, abs=0.0005), (
            "the tonnage already credited is not unwound by the retained result"
        )

    def test_the_released_run_is_pulled_back_to_held_and_the_plant_re_derives(
        self, api: ApiClient
    ) -> None:
        """The run drops RELEASED -> HELD and the plant counts its first held run.

        PRD: "Hop one to two: every production run naming this batch as its stucco provenance whose `status` is `RUNNING` or `COMPLETED`, and whose `quality_state` is `UNTESTED`, `IN_TEST`, `RELEASED` or `DOWNGRADED`, has its `quality_state` moved to `HELD` with `held_reason` set to `STUCCO_NONCONFORMING` and `saleable_grade` reset to `UNGRADED`."

        Design: Difficulty/transitive_cascade/retained_stucco_fail_cascades_batch_run_plant_load
        """
        world = _released_run_with_two_batches(api)

        before = world.read_plant()
        assert before["held_run_count"] == 0
        assert before["production_posture"] == ProductionPosture.OPEN.value, (
            "98.152 available tons with no held run is OPEN"
        )

        _failing_retained_sample(api, world.batch_id)

        run = world.read_run()
        assert run["status"] == RunStatus.COMPLETED.value
        assert run["quality_state"] == QualityState.HELD.value
        assert run["held_reason"] == HeldReason.STUCCO_NONCONFORMING.value
        assert run["saleable_grade"] == SaleableGrade.UNGRADED.value

        plant = world.read_plant()
        assert plant["held_run_count"] == 1
        assert plant["stucco_on_hand_tons"] == pytest.approx(98.152, abs=0.0005), (
            "297.277 credited by the two batches less the 199.125 the run consumed"
        )
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value, (
            "one held run is enough to restrict the plant"
        )

    def test_the_staged_load_is_held_with_its_quote_untouched(self, api: ApiClient) -> None:
        """The freight already staged against the run is held, not cancelled or re-priced.

        PRD: "Hop three to four: because each of those runs is now `HELD`, every load order sourced from it whose `status` is `STAGED` moves to `HELD` with `hold_source` set to `RUN_QUALITY_HELD`."

        Design: Difficulty/transitive_cascade/retained_stucco_fail_cascades_batch_run_plant_load
        """
        world = _released_run_with_two_batches(api)
        assert world.read_load()["status"] == LoadOrderStatus.STAGED.value

        _failing_retained_sample(api, world.batch_id)

        load = world.read_load()
        assert_load_order(load)
        assert load["status"] == LoadOrderStatus.HELD.value
        assert load["hold_source"] == HoldSource.RUN_QUALITY_HELD.value
        assert load["quoted_freight_usd"] == pytest.approx(756.79, abs=0.005), (
            "the quote stamped at staging survives the hold"
        )
        assert load["settled_freight_usd"] is None, "a held load has not shipped"


class TestEmergencyOutageApprovalCascade:
    """Approving an emergency outage schedules the line, cancels the overlapping run,
    releases its reservation and re-derives the posture."""

    def _scheduled_run_with_emergency_outage(self, api: ApiClient):
        world = fixtures.scheduled_run(api)
        world.outage = fixtures.propose_outage(
            api,
            world.line_id,
            outage_type=OutageType.EMERGENCY.value,
            window_start="2026-08-03T05:00:00Z",
            window_end="2026-08-03T12:00:00Z",
            scope_note="mixer gearbox failure",
        )
        return world

    def test_an_emergency_window_is_approved_in_august_and_priced_at_risk(
        self, api: ApiClient
    ) -> None:
        """August's 1.16 index would block campaign work, but an emergency is exempt.

        PRD: "An `EMERGENCY` outage is always allowed, whatever the month."

        Design: Difficulty/transitive_cascade/emergency_outage_approval_cascades_line_run_plant
        """
        world = self._scheduled_run_with_emergency_outage(api)

        approved = fixtures.approve_outage(api, world.outage_id)

        assert_maintenance_outage(approved)
        assert approved["status"] == OutageStatus.APPROVED.value
        assert approved["seasonality_index"] == pytest.approx(1.16, abs=0.005)
        assert approved["planned_downtime_hours"] == pytest.approx(7.00, abs=0.005), (
            "05:00 to 12:00 is seven hours of downtime"
        )
        assert approved["at_risk_msf"] == pytest.approx(300.000, abs=0.0005), (
            "the scheduled run's whole effective volume intersects the window"
        )
        assert approved["opportunity_cost_usd"] == pytest.approx(11550.00, abs=0.005), (
            "300.000 MSF at a contribution margin of 38.50 is 11550.00"
        )

    def test_approval_schedules_the_line_and_cancels_the_overlapping_run(
        self, api: ApiClient
    ) -> None:
        """The line goes to MAINTENANCE_SCHEDULED and the run is cancelled by the server.

        PRD: "Hop two to three: because the line is now `MAINTENANCE_SCHEDULED`, every production run on that line whose `status` is `DRAFT` or `SCHEDULED` and whose window intersects the outage window moves to `CANCELLED`, with the `OUTAGE_APPROVED:` reason described in §3.6."

        Design: Difficulty/transitive_cascade/emergency_outage_approval_cascades_line_run_plant
        """
        world = self._scheduled_run_with_emergency_outage(api)
        fixtures.approve_outage(api, world.outage_id)

        line = validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))
        assert line["status"] == BoardLineStatus.MAINTENANCE_SCHEDULED.value

        run = world.read_run()
        assert run["status"] == RunStatus.CANCELLED.value
        assert run["cancel_reason"] == f"{OUTAGE_CANCEL_REASON_PREFIX}{world.outage_id}", (
            "the server writes the literal prefix followed by the approving outage's id"
        )
        assert run["effective_planned_msf"] == pytest.approx(300.000, abs=0.0005), (
            "the cancellation does not erase what the run had planned"
        )
        assert run["stucco_reserved_tons"] == pytest.approx(0.000, abs=0.0005), (
            "cancelling zeroes the run's own reservation"
        )

    def test_the_released_reservation_re_derives_the_plant_posture(
        self, api: ApiClient
    ) -> None:
        """Handing 202.500 tons back moves the plant from RESTRICTED to OPEN.

        PRD: "Hop three to four: each cancelled run that had been `SCHEDULED` releases its `stucco_reserved_tons` back out of the plant's `stucco_committed_tons`, which re-derives `production_posture` and increments the plant's `version`, and every load order of that run in `STAGED`, `HELD` or `LOADED` is cancelled."

        Design: Difficulty/transitive_cascade/emergency_outage_approval_cascades_line_run_plant
        """
        world = self._scheduled_run_with_emergency_outage(api)

        before = world.read_plant()
        assert before["stucco_committed_tons"] == pytest.approx(202.500, abs=0.0005)
        assert before["stucco_available_tons"] == pytest.approx(2.030, abs=0.0005)
        assert before["production_posture"] == ProductionPosture.RESTRICTED.value

        fixtures.approve_outage(api, world.outage_id)

        after = world.read_plant()
        assert after["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert after["stucco_on_hand_tons"] == pytest.approx(204.530, abs=0.0005), (
            "physical inventory is untouched by a cancellation"
        )
        assert after["stucco_available_tons"] == pytest.approx(204.530, abs=0.0005)
        assert after["production_posture"] == ProductionPosture.OPEN.value
        assert after["version"] > before["version"], "the re-derivation is itself a mutation"
