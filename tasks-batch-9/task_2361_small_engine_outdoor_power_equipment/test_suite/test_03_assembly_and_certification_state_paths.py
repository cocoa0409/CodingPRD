"""State paths that are not a single line: engines, families and lots.

An engine carries two axes that move independently, a certification family can
travel a full loop back to where it started, and an incoming lot forks into two
branches whose side effects differ before one of them re-joins the other.
"""

import pytest

from test_helpers import (
    build_allocatable_plant,
    build_released_order_plant,
    build_supplier,
    certify_family,
    complete_durability_run,
    deviation_accept_lot,
    hot_test_unit,
    inspect_component_lot,
    read_build_order,
    read_durability_run,
    read_engine_unit,
    read_family,
    read_lot,
    read_model,
    read_platform,
    read_supplier_scorecard,
    receive_component_lot,
    record_line_audit,
    record_torque,
    release_engine_unit,
    rework_engine_unit,
    run_allocations,
    schedule_durability_run,
    schedule_line_audit,
    stage_engine_unit,
    submit_family,
    torque_readings_at,
)

ONE_FASTENER_OVER_BAND = torque_readings_at(22.0, 22.1, 21.9, 23.2)
REMEDIATION_START = "2026-09-01T09:00:00Z"
REMEDIATION_END = "2026-09-22T09:00:00Z"


def _held_plant_after_a_failed_audit():
    """Two released and allocated units, then an audit that fails on rate."""
    scenario = build_allocatable_plant(released_units=2)
    run_allocations(scenario.build_order_id)
    audit = schedule_line_audit(scenario.build_order_id, audit_week="2026-09-14")
    assert audit["required_sample_size"] == 2
    recorded = record_line_audit(
        audit["id"],
        units_tested=2,
        units_failed=2,
        max_measured_emission_g_per_kwh=5.60,
    )
    assert recorded["status"] == "FAILED"
    assert recorded["failure_reason"] == "FAILURE_RATE_EXCEEDED"
    return scenario


def _remediate_and_recertify(scenario):
    """The AUDIT_HOLD family goes back through testing and is certified again."""
    run = schedule_durability_run(
        scenario.family_id,
        scenario.platform_id,
        scheduled_start_at=REMEDIATION_START,
        scheduled_end_at=REMEDIATION_END,
    )
    complete_durability_run(
        run["id"], accumulated_hours=500, final_emission_g_per_kwh=6.40
    )
    submit_family(scenario.family_id)
    certify_family(scenario.family_id)
    return run


class TestEngineUnitTwoStateAxes:
    """Physical progress and quality standing move on separate axes."""

    def test_a_failing_torque_record_advances_the_build_axis_anyway(
        self, canonical_clock
    ):
        """PRD §3.7: "A platform specified at 22.0 Nm with a tolerance of 0.05 therefore accepts everything from 20.90 through 23.10 inclusive."
        PRD §3.7: "`out_of_spec_fastener_count` is the number of readings whose `torque_nm` is strictly below the lower bound or strictly above the upper bound."
        PRD §3.7: "The unit's `build_state` advances `STAGED → ASSEMBLED` regardless of the count, and its `conformance_state` becomes `NONCONFORMING` when `out_of_spec_fastener_count` is greater than zero, or is left at `PENDING` when every fastener was in band."

        Design: Difficulty/non_linear_state_machine/engine_unit_parallel_build_and_conformance_dimensions
        """
        scenario = build_released_order_plant()
        staged = stage_engine_unit(scenario, "SN-0001")
        assert staged["build_state"] == "STAGED"
        assert staged["conformance_state"] == "PENDING"
        assert staged["rework_count"] == 0

        recorded = record_torque(staged["id"], ONE_FASTENER_OVER_BAND)

        # Only the 23.2 Nm reading sits outside the inclusive band.
        assert recorded["out_of_spec_fastener_count"] == 1
        assert recorded["build_state"] == "ASSEMBLED"
        assert recorded["conformance_state"] == "NONCONFORMING"

    def test_rework_walks_the_build_axis_backwards_and_resets_conformance(
        self, canonical_clock
    ):
        """PRD §3.7: "A unit whose `build_state` is `ASSEMBLED` or `HOT_TESTED` and whose `conformance_state` is `NONCONFORMING` may be sent back to staging, provided its `rework_count` is still below 2; a third attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED`."
        PRD §3.7: "Rework adds 1 to `rework_count`, steps `build_state` back to `STAGED`, resets `conformance_state` to `PENDING`, and clears `torque_readings`, `out_of_spec_fastener_count`, `measured_rpm`, `measured_emission_g_per_kwh` and `hot_test_emission_threshold` back to empty."

        Design: Difficulty/non_linear_state_machine/engine_unit_parallel_build_and_conformance_dimensions
        """
        scenario = build_released_order_plant()
        staged = stage_engine_unit(scenario, "SN-0001")
        record_torque(staged["id"], ONE_FASTENER_OVER_BAND)

        reworked = rework_engine_unit(staged["id"])

        assert reworked["build_state"] == "STAGED"
        assert reworked["conformance_state"] == "PENDING"
        assert reworked["rework_count"] == 1
        assert reworked["torque_readings"] is None
        assert reworked["out_of_spec_fastener_count"] is None
        assert reworked["measured_rpm"] is None
        assert reworked["measured_emission_g_per_kwh"] is None
        assert reworked["hot_test_emission_threshold"] is None

    def test_one_engine_visits_nonconforming_pending_and_conforming_in_turn(
        self, canonical_clock
    ):
        """PRD §3.7: "A quarantine cascade moves only the conformance axis and leaves the build axis untouched; a rework moves the build axis backwards and resets the conformance axis; a cancellation moves the build axis to its terminal value and leaves the conformance axis exactly as it was."
        PRD §3.7: "The `build_state` advances `ASSEMBLED → HOT_TESTED` either way, and `conformance_state` becomes `CONFORMING` when both comparisons hold and `NONCONFORMING` when either fails."
        PRD §3.7: "The unit reaches the terminal `RELEASED` build state with `released_at` stamped from the clock, the order's `built_quantity` rises by 1 while `staged_quantity` falls by 1, and the unit joins the order's allocation pool."

        Design: Difficulty/non_linear_state_machine/engine_unit_parallel_build_and_conformance_dimensions
        """
        scenario = build_released_order_plant()
        staged = stage_engine_unit(scenario, "SN-0001")

        first_pass = record_torque(staged["id"], ONE_FASTENER_OVER_BAND)
        assert (first_pass["build_state"], first_pass["conformance_state"]) == (
            "ASSEMBLED",
            "NONCONFORMING",
        )

        after_rework = rework_engine_unit(staged["id"])
        assert (after_rework["build_state"], after_rework["conformance_state"]) == (
            "STAGED",
            "PENDING",
        )

        record_torque(staged["id"])
        hot_tested = hot_test_unit(staged["id"])
        assert hot_tested["build_state"] == "HOT_TESTED"
        assert hot_tested["conformance_state"] == "CONFORMING"
        assert hot_tested["hot_test_emission_threshold"] == pytest.approx(
            5.63, abs=0.005
        )

        released = release_engine_unit(staged["id"])
        assert (released["build_state"], released["conformance_state"]) == (
            "RELEASED",
            "CONFORMING",
        )
        assert released["rework_count"] == 1
        assert released["out_of_spec_fastener_count"] == 0

        order = read_build_order(scenario.build_order_id)
        assert order["built_quantity"] == 1
        assert order["staged_quantity"] == 0


class TestCertificationFamilyAuditHoldLoop:
    """A held family can travel the whole loop back to CERTIFIED."""

    def test_the_hold_loop_closes_without_clearing_the_failure_counter(
        self, canonical_clock
    ):
        """PRD §3.8: "A family that had already accumulated one failure, was re-certified, and then failed again therefore goes straight from `CERTIFIED` to `SUSPENDED`; a family already sitting in `AUDIT_HOLD` that fails again does the same."
        PRD §3.2: "On success the family moves `SUBMITTED → CERTIFIED`, `certified_by_user_id` records the certifying operator, `certified_at` is stamped from the clock, and every platform of the family has its posture recomputed to `OPEN`."

        Design: Difficulty/non_linear_state_machine/certification_family_audit_hold_cycle_returns_to_certified
        """
        scenario = _held_plant_after_a_failed_audit()
        held_family = read_family(scenario.family_id)
        assert held_family["status"] == "AUDIT_HOLD"
        assert held_family["cumulative_audit_failures"] == 1
        assert held_family["audit_hold_at"].startswith("2026-08-03T08:00:00")

        _remediate_and_recertify(scenario)

        family = read_family(scenario.family_id)
        assert family["status"] == "CERTIFIED"
        assert family["cumulative_audit_failures"] == 1
        assert family["deterioration_factor"] == pytest.approx(1.2800, abs=0.00005)
        assert family["certified_emission_g_per_kwh"] == pytest.approx(5.12, abs=0.005)
        assert read_platform(scenario.platform_id)["certification_posture"] == "OPEN"

    def test_recertification_restores_the_order_but_not_the_model_or_the_split(
        self, canonical_clock
    ):
        """PRD §3.8: "When the family reaches `CERTIFIED` again, every platform's posture returns to `OPEN`; every build order of that family whose status is `HELD` is restored to whatever `status_before_hold` recorded, with both `held_reason` and `status_before_hold` cleared afterwards — so an order held from `PLANNED` returns to `PLANNED`, one held from `RELEASED` returns to `RELEASED`, and one held from `IN_PRODUCTION` returns to `IN_PRODUCTION`; and every engine unit of those restored orders whose `conformance_state` is `QUARANTINED` returns to `PENDING`, with `build_state` again untouched."
        PRD §3.8: "Allocation counters stay where the cascade left them, so the planner must run channel allocation again to re-establish a split."
        PRD §3.8: "And product models suspended by the cascade are **not** auto-released: because a model release re-checks its safety certification against the clock, a `PlantAdmin` must release each suspended model explicitly."

        Design: Difficulty/non_linear_state_machine/certification_family_audit_hold_cycle_returns_to_certified
        """
        scenario = _held_plant_after_a_failed_audit()
        held_order = read_build_order(scenario.build_order_id)
        assert held_order["status"] == "HELD"
        assert held_order["status_before_hold"] == "IN_PRODUCTION"
        assert held_order["held_reason"] == "FAMILY_AUDIT_HOLD"

        _remediate_and_recertify(scenario)

        order = read_build_order(scenario.build_order_id)
        assert order["status"] == "IN_PRODUCTION"
        assert order["status_before_hold"] is None
        assert order["held_reason"] is None

        # The channel position torn up by the cascade is not rebuilt.
        assert order["allocated_dealer_units"] == 0
        assert order["allocated_mass_retail_units"] == 0
        assert order["unallocated_units"] == 2
        assert order["allocation_status"] == "UNALLOCATED"

        assert read_model(scenario.model_id)["status"] == "SUSPENDED"

    def test_a_held_family_re_enters_durability_and_keeps_both_completed_runs(
        self, canonical_clock
    ):
        """PRD §3.2: "When the family is in `AUDIT_HOLD`, one further condition applies: the remediation run's `scheduled_start_at` must be at or after the family's `audit_hold_at`, so that a run predating the hold cannot be used to clear it."
        PRD §3.2: "Three things then happen to the surrounding graph: the family advances to `DURABILITY_TESTING` (from `DRAFT` or from `AUDIT_HOLD`; a family already in `DURABILITY_TESTING` stays there and simply carries an additional scheduled run), the family's `version` increments by 1, and every platform of the family has its `certification_posture` recomputed, landing on `RESTRICTED`."
        PRD §3.2: "Build orders that were already held by an earlier audit failure stay held through all of this; only re-certification lifts them."

        Design: Difficulty/non_linear_state_machine/certification_family_audit_hold_cycle_returns_to_certified
        """
        scenario = _held_plant_after_a_failed_audit()
        first_run_id = scenario.durability_run["id"]

        remediation = schedule_durability_run(
            scenario.family_id,
            scenario.platform_id,
            scheduled_start_at=REMEDIATION_START,
            scheduled_end_at=REMEDIATION_END,
        )
        assert remediation["status"] == "SCHEDULED"
        assert read_family(scenario.family_id)["status"] == "DURABILITY_TESTING"
        assert (
            read_platform(scenario.platform_id)["certification_posture"] == "RESTRICTED"
        )
        assert read_build_order(scenario.build_order_id)["status"] == "HELD"

        complete_durability_run(
            remediation["id"], accumulated_hours=500, final_emission_g_per_kwh=6.40
        )

        assert read_durability_run(first_run_id)["status"] == "COMPLETED"
        assert read_durability_run(remediation["id"])["status"] == "COMPLETED"
        assert read_family(scenario.family_id)["status"] == "DURABILITY_COMPLETE"
        assert read_build_order(scenario.build_order_id)["status"] == "HELD"


class TestComponentLotRejectionBranch:
    """The rejected branch carries a taint the accepted branch never does."""

    def test_a_rejected_lot_re_joins_the_line_with_a_recomputed_quantity(
        self, canonical_clock
    ):
        """PRD §3.4: "The disposition forks on the frozen acceptance number: when `defects_found` is at most `acceptance_number` the lot moves `RECEIVED → ACCEPTED`, and when it is greater the lot moves `RECEIVED → REJECTED`."
        PRD §3.4: "A lot whose status is `REJECTED` or `QUARANTINED` may be released to the line under deviation; a lot in any other status is refused with `ERR_LOT_STATE_INVALID`."
        PRD §3.4: "On success the lot moves to `DEVIATION_ACCEPTED`, `deviation_flag` becomes true, `deviation_approved_by_user_id` records the approver, and the released quantity is recomputed: `accepted_qty` becomes `lot_quantity` minus `defects_found`, with `remaining_qty` set equal to it."

        Design: Difficulty/non_linear_state_machine/component_lot_branch_reject_then_deviation_accept
        """
        supplier = build_supplier()
        clean_lot = receive_component_lot(supplier["id"], lot_code="CB-001")
        inspect_component_lot(clean_lot["id"], defects_found=0)

        dirty_lot = receive_component_lot(
            supplier["id"], lot_code="CB-002", lot_quantity=200
        )
        assert dirty_lot["sample_size"] == 10
        assert dirty_lot["acceptance_number"] == 1
        rejected = inspect_component_lot(dirty_lot["id"], defects_found=2)
        assert rejected["status"] == "REJECTED"
        assert rejected["accepted_qty"] == 0
        assert rejected["remaining_qty"] == 0

        deviated = deviation_accept_lot(dirty_lot["id"])

        assert deviated["status"] == "DEVIATION_ACCEPTED"
        assert deviated["accepted_qty"] == 198
        assert deviated["remaining_qty"] == 198
        assert deviated["consumed_qty"] == 0
        assert deviated["deviation_flag"] is True
        assert deviated["inspected_by_user_id"] == "qe-mika"
        assert deviated["deviation_approved_by_user_id"] == "co-ravi"

    def test_the_accepted_sibling_is_quarantined_and_carries_no_deviation_taint(
        self, canonical_clock
    ):
        """PRD §3.4: "An acceptance sets `accepted_qty` to `lot_quantity` minus `defects_found`, sets `remaining_qty` equal to that `accepted_qty`, writes the lot's own `defect_ppm`, records the inspecting operator as `inspected_by_user_id`, adds 1 to the supplier's `inspected_lot_count`, adds 1 to the supplier's `consecutive_accepted_lots`, and recomputes the supplier's `rolling_defect_ppm`."
        PRD §3.4: "Then **every other lot of that same supplier** whose status is `RECEIVED` or `ACCEPTED` and whose `remaining_qty` is greater than zero moves to `QUARANTINED`; a quarantined lot can no longer be inspected, and any attempt is refused with `ERR_LOT_STATE_INVALID`, while any attempt to stage a unit from it is refused with `ERR_COMPONENT_LOT_NOT_RELEASABLE`."
        PRD §3.4: "The supplier's `rolling_defect_ppm` is deliberately **not** revised."

        Design: Difficulty/non_linear_state_machine/component_lot_branch_reject_then_deviation_accept
        """
        supplier = build_supplier()
        clean_lot = receive_component_lot(supplier["id"], lot_code="CB-001")
        accepted = inspect_component_lot(clean_lot["id"], defects_found=0)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_qty"] == 800

        dirty_lot = receive_component_lot(
            supplier["id"], lot_code="CB-002", lot_quantity=200
        )
        inspect_component_lot(dirty_lot["id"], defects_found=2)
        deviation_accept_lot(dirty_lot["id"])

        dragged_down = read_lot(clean_lot["id"])
        assert dragged_down["status"] == "QUARANTINED"
        assert dragged_down["accepted_qty"] == 800
        assert dragged_down["remaining_qty"] == 800
        assert dragged_down["deviation_flag"] is False

        scorecard = read_supplier_scorecard(supplier["id"])
        assert scorecard["rolling_defect_ppm"] == 40000
        assert scorecard["approval_status"] == "PROBATION"
