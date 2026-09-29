"""State machines that are neither linear nor single-dimensioned: a run whose
status and quality dimensions advance independently, a lot that loops through
quarantine a bounded number of times, and an outage whose deferral cycle changes
the guard that governs its own approval.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BoardLineStatus,
    LotStatus,
    OutageStatus,
    ProductionPosture,
    QualityState,
    QuarantineReason,
    RunStatus,
    SaleableGrade,
    assert_board_test,
    assert_gypsum_lot,
    assert_maintenance_outage,
    assert_production_run,
    factories,
    find_by,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)

#: Four specimens against the REGULAR minima, the second missing nail pull.
FOUR_SPECIMENS_ONE_FAILING = (
    factories.board_test_payload(1, 17.0, 82.0, 39.0, 110.0, 0.55),
    factories.board_test_payload(2, 16.0, 70.0, 38.0, 105.0, 0.58),
    factories.board_test_payload(3, 18.0, 84.0, 40.0, 112.0, 0.49),
    factories.board_test_payload(4, 17.5, 79.0, 37.0, 108.0, 0.51),
)


class TestRunDimensionsAdvanceIndependently:
    """`status` and `quality_state` are two machines on one row; the combined
    state (COMPLETED, DOWNGRADED) is reachable and status never leaves COMPLETED."""

    def test_status_walks_to_completed_while_quality_state_stays_untested(
        self, api: ApiClient
    ) -> None:
        """Drafting, scheduling, starting and completing never touch the quality dimension.

        PRD: "A new draft has `status` `DRAFT`, `quality_state` `UNTESTED` and `saleable_grade` `UNGRADED`, with `prior_run_id`, `cancel_reason` and `held_reason` all null and every tonnage and MSF counter at its zero default."

        Design: Difficulty/non_linear_state_machine/run_status_and_quality_dimensions_advance_independently
        """
        world = fixtures.baseline_with_stucco(api)

        drafted = fixtures.draft_run(api, world)
        assert drafted["status"] == RunStatus.DRAFT.value
        assert drafted["quality_state"] == QualityState.UNTESTED.value
        assert drafted["saleable_grade"] == SaleableGrade.UNGRADED.value
        assert drafted["held_reason"] is None

        scheduled = fixtures.schedule(api, drafted["id"], world.plant_id)
        assert scheduled["status"] == RunStatus.SCHEDULED.value
        assert scheduled["quality_state"] == QualityState.UNTESTED.value

        fixtures.set_clock(api, "2026-08-03T06:00:00Z")
        started = fixtures.start(api, drafted["id"])
        assert started["status"] == RunStatus.RUNNING.value
        assert started["quality_state"] == QualityState.UNTESTED.value

        completed = fixtures.complete(api, drafted["id"])
        assert completed["status"] == RunStatus.COMPLETED.value
        assert completed["quality_state"] == QualityState.UNTESTED.value, (
            "clean defect rates leave the quality dimension untouched by completion"
        )
        assert completed["specimen_count"] == 0
        assert completed["fail_rate"] == pytest.approx(0.0000, abs=0.00005)

    def test_evaluation_moves_only_the_quality_dimension_to_downgraded(
        self, api: ApiClient
    ) -> None:
        """One failing specimen in four downgrades the run and leaves status COMPLETED.

        PRD: "The quality dimension of a production run is tracked by `quality_state`, which evolves independently of `status` and takes one of six values: `UNTESTED`, `IN_TEST`, `RELEASED`, `DOWNGRADED`, `HELD` and `SCRAPPED`."

        Design: Difficulty/non_linear_state_machine/run_status_and_quality_dimensions_advance_independently
        """
        world = fixtures.completed_run(api)
        for payload in FOUR_SPECIMENS_ONE_FAILING:
            fixtures.record_specimen(api, world.run_id, payload)

        evaluated = fixtures.evaluate(api, world.run_id)

        assert_production_run(evaluated)
        assert evaluated["status"] == RunStatus.COMPLETED.value, (
            "the lifecycle dimension is frozen at COMPLETED"
        )
        assert evaluated["quality_state"] == QualityState.DOWNGRADED.value
        assert evaluated["saleable_grade"] == SaleableGrade.SECONDS.value
        assert evaluated["specimen_count"] == 4
        assert evaluated["failing_specimen_count"] == 1
        assert evaluated["fail_rate"] == pytest.approx(0.2500, abs=0.00005), (
            "one failure in four specimens is exactly the inclusive downgrade ceiling"
        )
        assert evaluated["held_reason"] is None, "a downgrade is not a hold"
        assert evaluated["net_good_msf"] == pytest.approx(290.000, abs=0.0005)
        assert evaluated["available_msf"] == pytest.approx(290.000, abs=0.0005)

    def test_the_failing_specimen_names_the_one_attribute_it_missed(
        self, api: ApiClient
    ) -> None:
        """Specimen two reads 70.0 lbf against a 77.0 minimum and fails on NAIL_PULL alone.

        PRD: "A specimen with an empty `failing_attributes` has `result` `PASS`; otherwise `result` is `FAIL` and `failing_attributes` lists every attribute that missed, not just the first."

        Design: Difficulty/non_linear_state_machine/run_status_and_quality_dimensions_advance_independently
        """
        world = fixtures.completed_run(api)
        for payload in FOUR_SPECIMENS_ONE_FAILING:
            fixtures.record_specimen(api, world.run_id, payload)
        fixtures.evaluate(api, world.run_id)

        specimens, meta = validate_paginated(
            api.list_board_tests_of_run(world.run_id, test_users.QUALITY_INSPECTOR)
        )
        assert meta["total_count"] == 4

        failing = find_by(specimens, specimen_seq=2)
        assert failing is not None, "the second specimen must be listed"
        assert_board_test(failing)
        assert failing["result"] == "FAIL"
        assert failing["failing_attributes"] == ["NAIL_PULL"], (
            "core hardness, flexural cross and exit moisture were all inside their bands"
        )

        passing = find_by(specimens, specimen_seq=4)
        assert passing is not None
        assert passing["result"] == "PASS"
        assert passing["failing_attributes"] == []

        plant = world.read_plant()
        assert plant["held_run_count"] == 0, "a downgraded run is not a held run"
        assert plant["stucco_on_hand_tons"] == pytest.approx(5.405, abs=0.0005), (
            "204.530 credited less the 199.125 tons the run consumed"
        )
        assert plant["stucco_committed_tons"] == pytest.approx(0.000, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.RESTRICTED.value, (
            "5.405 available tons is below the 40.0-ton floor"
        )


class TestLotQuarantineCycle:
    """QUARANTINED is a self-loop bounded at three assays, and each pass through it
    recomputes the reason from the pinned check order."""

    def test_each_assay_recomputes_the_quarantine_reason(self, api: ApiClient) -> None:
        """Moisture, then chloride, then moisture again as the first failing check changes.

        PRD: "A `QUARANTINED` lot may be assayed again: if the disposition still comes back quarantined the lot loops `QUARANTINED → QUARANTINED` with its reason recomputed, and if the fresh numbers clear all three checks it moves `QUARANTINED → APPROVED` with `quarantine_reason` cleared to null."

        Design: Difficulty/non_linear_state_machine/lot_quarantine_reassay_cycle_bounded_at_three
        """
        plant = fixtures.create_plant(api)
        lot = fixtures.create_lot(api, factories.synthetic_lot_payload(plant["id"]))

        assert lot["status"] == LotStatus.RECEIVED.value
        assert lot["assay_count"] == 0
        assert lot["version"] == 1

        first = fixtures.assay_lot(api, lot["id"], 12.01, 94.0, 120)
        assert first["status"] == LotStatus.QUARANTINED.value
        assert first["quarantine_reason"] == QuarantineReason.MOISTURE_CEILING.value, (
            "12.01 percent is strictly above the 12.0 synthetic ceiling"
        )
        assert first["assay_count"] == 1
        assert first["version"] == 2

        second = fixtures.assay_lot(api, lot["id"], 11.00, 94.0, 250)
        assert second["status"] == LotStatus.QUARANTINED.value
        assert second["quarantine_reason"] == QuarantineReason.CHLORIDE_CEILING.value, (
            "the moisture check now passes, so the chloride check at exactly 250 ppm decides"
        )
        assert second["assay_count"] == 2
        assert second["version"] == 3

        third = fixtures.assay_lot(api, lot["id"], 12.60, 94.0, 250)
        assert_gypsum_lot(third)
        assert third["status"] == LotStatus.QUARANTINED.value
        assert third["quarantine_reason"] == QuarantineReason.MOISTURE_CEILING.value, (
            "both checks fail, and the first one in the pinned order names the reason"
        )
        assert third["assay_count"] == 3
        assert third["version"] == 4

    def test_the_fourth_assay_is_refused_and_the_third_result_stands(
        self, api: ApiClient
    ) -> None:
        """A clean fourth sample cannot rescue the lot once three assays are spent.

        PRD: "Any attempt to record a fourth — that is, an attempt made when `assay_count` has already reached 3 — is refused with `ERR_MAX_ASSAYS_REACHED`."

        Design: Difficulty/non_linear_state_machine/lot_quarantine_reassay_cycle_bounded_at_three
        """
        plant = fixtures.create_plant(api)
        lot = fixtures.create_lot(api, factories.synthetic_lot_payload(plant["id"]))
        fixtures.assay_lot(api, lot["id"], 12.01, 94.0, 120)
        fixtures.assay_lot(api, lot["id"], 11.00, 94.0, 250)
        fixtures.assay_lot(api, lot["id"], 12.60, 94.0, 250)

        validate_error(
            api.assay_gypsum_lot(
                lot["id"],
                factories.assay_payload(8.00, 94.0, 100),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.MAX_ASSAYS_REACHED.value,
            409,
        )

        after = fixtures.read_lot(api, lot["id"])
        assert after["status"] == LotStatus.QUARANTINED.value
        assert after["quarantine_reason"] == QuarantineReason.MOISTURE_CEILING.value
        assert after["assay_count"] == 3, "the refused attempt did not count"
        assert after["free_moisture_pct"] == pytest.approx(12.60, abs=0.005), (
            "the third assay's values are still the ones of record"
        )
        assert after["chloride_ppm"] == 250
        assert after["version"] == 4, "a refused request is not a mutation"
        assert after["remaining_tons"] == pytest.approx(300.000, abs=0.0005)
        assert after["consumed_tons"] == pytest.approx(0.000, abs=0.0005)


class TestOutageDeferralCycle:
    """The PROPOSED -> DEFERRED -> PROPOSED loop is what changes the approval guard:
    the same August month is refused at zero deferrals and allowed at two."""

    def test_an_august_window_is_refused_while_the_outage_has_never_been_deferred(
        self, api: ApiClient
    ) -> None:
        """August's index of 1.16 is above the 0.90 ceiling, so approval is blocked.

        PRD: "Otherwise the outage is allowed only when its `seasonality_index` is less than or equal to 0.90; the ceiling is inclusive, so October, whose index is exactly 0.90, is an allowed month, while April through September and any month above the ceiling are not."

        Design: Difficulty/non_linear_state_machine/outage_defer_repropose_cycle_unlocks_seasonality_gate
        """
        world = fixtures.baseline(api)
        outage = fixtures.propose_outage(
            api,
            world.line_id,
            window_start="2026-08-20T06:00:00Z",
            window_end="2026-08-22T06:00:00Z",
            scope_note="board line knife and forming table rebuild",
        )

        assert_maintenance_outage(outage)
        assert outage["seasonality_index"] == pytest.approx(1.16, abs=0.005)
        assert outage["planned_downtime_hours"] == pytest.approx(48.00, abs=0.005)
        assert outage["at_risk_msf"] == pytest.approx(0.000, abs=0.0005), (
            "no run is scheduled on the line, so nothing is at risk"
        )
        assert outage["opportunity_cost_usd"] == pytest.approx(0.00, abs=0.005)
        assert outage["deferral_count"] == 0

        validate_error(
            api.approve_outage(outage["id"], {}, test_users.PLANT_MANAGER),
            ApiErrorId.SEASONALITY_WINDOW_UNFAVORABLE.value,
            409,
        )

        after = fixtures.read_outage(api, outage["id"])
        assert after["status"] == OutageStatus.PROPOSED.value
        assert after["approved_by_user_id"] is None
        assert fixtures.read_line(api, world.line_id)["status"] == BoardLineStatus.AVAILABLE.value, (
            "a refused approval must not schedule the line for maintenance"
        )

    def test_two_deferrals_unlock_the_same_unfavourable_month(self, api: ApiClient) -> None:
        """After two pushes the gate stops applying and an August window is approved.

        PRD: "`deferral_count` is never reset by a re-proposal, which is what makes the deferral cycle self-limiting: after two rounds of push-and-re-propose the seasonality gate stops applying altogether and the work must be approved into whatever month it lands in."

        Design: Difficulty/non_linear_state_machine/outage_defer_repropose_cycle_unlocks_seasonality_gate
        """
        world = fixtures.baseline(api)
        outage = fixtures.propose_outage(
            api,
            world.line_id,
            window_start="2026-08-20T06:00:00Z",
            window_end="2026-08-22T06:00:00Z",
            scope_note="board line knife and forming table rebuild",
        )

        deferred = fixtures.defer_outage(api, outage["id"], deferred_reason="peak housing season backlog")
        assert deferred["status"] == OutageStatus.DEFERRED.value
        assert deferred["deferral_count"] == 1

        reproposed = fixtures.repropose_outage(
            api, outage["id"], "2026-08-25T06:00:00Z", "2026-08-27T06:00:00Z"
        )
        assert reproposed["status"] == OutageStatus.PROPOSED.value
        assert reproposed["deferral_count"] == 1, "re-proposing never resets the counter"

        deferred_again = fixtures.defer_outage(
            api, outage["id"], deferred_reason="still shipping to distributors"
        )
        assert deferred_again["deferral_count"] == 2

        fixtures.repropose_outage(
            api, outage["id"], "2026-08-28T06:00:00Z", "2026-08-30T06:00:00Z"
        )
        approved = fixtures.approve_outage(api, outage["id"])

        assert approved["status"] == OutageStatus.APPROVED.value
        assert approved["deferral_count"] == 2
        assert approved["seasonality_index"] == pytest.approx(1.16, abs=0.005), (
            "the month is still August; it is the deferral count that changed"
        )
        assert approved["planned_downtime_hours"] == pytest.approx(48.00, abs=0.005)
        assert approved["window_start"].startswith("2026-08-28T06:00:00")
        assert approved["approved_by_user_id"] == test_users.USER_MANAGER
        assert approved["at_risk_msf"] == pytest.approx(0.000, abs=0.0005)
        assert approved["opportunity_cost_usd"] == pytest.approx(0.00, abs=0.005)

        line = validate_success(api.get_board_line(world.line_id, test_users.PLANT_ADMIN))
        assert line["status"] == BoardLineStatus.MAINTENANCE_SCHEDULED.value, (
            "approval cascades into the line"
        )
