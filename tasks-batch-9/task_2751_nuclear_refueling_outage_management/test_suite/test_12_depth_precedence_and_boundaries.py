"""Depth coverage: rejection precedence, inclusive boundaries and cross-entity
state dependencies."""

import pytest

from test_helpers import (
    AlaraPosture,
    ApiErrorId,
    AvailabilityVariant,
    CLOCK_EPOCH,
    OutageStatus,
    ReservationPurpose,
    RwpStatus,
    SafetyFunctionCode,
    StationUnit,
    WorkOrderStatus,
    WorkOrderType,
    api_client,
    assert_dose_budget_consistent,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_core_load_pattern,
    given_draft_rwp,
    given_outage,
    given_planned_work_order,
    given_rad_area,
    given_safety_function,
    given_schedule_activity,
    given_spent_fuel_pool,
    given_startup_test,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_reactor_engineer_headers,
    read_outage,
    read_pool,
    read_rwp,
    set_clock,
    validate_error,
    validate_success,
)


class TestCrossEntityStateBeatsDoseBudget:
    def _planning_outage_with_oversized_permit(self):
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            area_code="RA-5", dose_rate_mrem_per_hr=25, survey_buffer_hours=2
        )
        outage = given_outage(designation="2R26", dose_budget_total_mrem=100)
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Reactor cavity inspection campaign",
            estimated_hours=200,
            estimated_cost_usd=500000,
            estimated_dose_mrem=400,
            regulatory_commitment=True,
            requires_rad_work=True,
        )
        permit = given_draft_rwp(
            work_order["id"],
            rad_area["id"],
            worker_count=5,
            shielding_factor=0,
            planned_start_offset_hours=0,
            planned_duration_hours=5,
        )
        assert permit["committed_dose_mrem"] == pytest.approx(750.00, abs=0.01)
        return outage, permit

    def test_planning_outage_masks_the_dose_budget_overrun(self):
        """A 750.00-mrem permit against a 100-mrem budget also violates the dose
        budget, but the outage is still in PLANNING, and that earlier check
        decides the response.

        PRD 3.7: "These seven checks are evaluated in the order just given, which
        is the order §2.8 fixes: a suspended posture surfaces as
        `ERR_ALARA_POSTURE_SUSPENDED` rather than being masked by the later window
        or dose-budget checks."

        Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_dose_budget_on_rwp_approve
        """
        outage, permit = self._planning_outage_with_oversized_permit()
        assert read_outage(outage["id"])["status"] == OutageStatus.PLANNING

        response = api_client.approve_rwp(
            permit["id"],
            make_rad_protection_manager_headers(),
            alara_review_reference="ALARA-2R26-011",
        )
        validate_error(response, ApiErrorId.OUTAGE_STATE_INVALID.value)

    def test_the_refused_approval_leaves_permit_and_ledger_untouched(self):
        """The rejected request commits nothing: the permit is still DRAFT, no
        ledger row exists and the dose posture is still NORMAL.

        PRD 3.7: "Hop two replays the ledger to refresh the outage's
        `dose_committed_mrem` and `dose_budget_remaining_mrem`."

        Design: Difficulty/priority_pair_validation_conflict/cross_entity_state_beats_dose_budget_on_rwp_approve
        """
        outage, permit = self._planning_outage_with_oversized_permit()
        api_client.approve_rwp(
            permit["id"],
            make_rad_protection_manager_headers(),
            alara_review_reference="ALARA-2R26-011",
        )
        assert read_rwp(permit["id"])["status"] == RwpStatus.DRAFT
        rows = validate_success(
            api_client.list_dose_transactions(
                permit["id"], make_rad_protection_manager_headers()
            )
        )
        assert rows == []
        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(0.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(100.00, abs=0.01)
        assert after["alara_posture"] == AlaraPosture.NORMAL


class TestSafetyFunctionCapacityBeatsGraphOwnership:
    def _two_outages_sharing_one_safety_function(self):
        set_clock(CLOCK_EPOCH)
        safety_function = given_safety_function(
            station_unit=StationUnit.UNIT_1,
            function_code=SafetyFunctionCode.DECAY_HEAT_REMOVAL,
            trains_total=3,
            min_trains_required=2,
        )
        first = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        second = given_outage(station_unit=StationUnit.UNIT_2, designation="2R26")
        given_schedule_activity(
            first["id"],
            label="A1 decay heat train A out of service",
            planned_start_offset_hours=100,
            planned_duration_hours=50,
            oos_safety_function_id=safety_function["id"],
            oos_train_label="A",
        )
        foreign = given_schedule_activity(
            second["id"],
            label="Foreign unit manoeuvre",
            planned_start_offset_hours=0,
            planned_duration_hours=10,
        )
        return first, second, safety_function, foreign

    def test_capacity_breach_outranks_the_foreign_predecessor(self):
        """The incoming window touches the existing one at hour 150 and names a
        second train, so capacity is breached; the predecessor also belongs to
        another outage, but that check sits one rank later.

        PRD 2.8: "A request that both breaches shutdown-safety-function capacity
        and overruns the spent fuel pool reports the safety breach, never the
        capacity breach."

        Design: Difficulty/priority_pair_validation_conflict/safety_function_capacity_beats_predecessor_outage_mismatch
        """
        first, _second, safety_function, foreign = (
            self._two_outages_sharing_one_safety_function()
        )
        assert safety_function["max_concurrent_oos_trains"] == 1

        response = api_client.create_schedule_activity(
            first["id"],
            {
                "label": "A2 decay heat train B out of service",
                "planned_start_offset_hours": 150,
                "planned_duration_hours": 20,
                "oos_safety_function_id": safety_function["id"],
                "oos_train_label": "B",
                "predecessor_activity_id": foreign["id"],
            },
            make_outage_planner_headers(),
        )
        validate_error(response, ApiErrorId.SAFETY_FUNCTION_CAPACITY_EXCEEDED.value)

        rows = validate_success(
            api_client.list_schedule_activities(
                make_outage_planner_headers(), outage_id=first["id"]
            )
        )
        assert len(rows) == 1, "the refused creation persisted nothing"

    def test_ownership_mismatch_surfaces_once_capacity_is_satisfied(self):
        """Naming the train already out of service consumes one unit of capacity
        rather than two, so the request clears rank 13 and the foreign
        predecessor is what finally rejects it.

        PRD 2.8: "14. Schedule graph ownership: a supplied predecessor or work
        order belongs to the same outage — otherwise
        `ERR_PREDECESSOR_OUTAGE_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_function_capacity_beats_predecessor_outage_mismatch
        """
        first, _second, safety_function, foreign = (
            self._two_outages_sharing_one_safety_function()
        )
        response = api_client.create_schedule_activity(
            first["id"],
            {
                "label": "A2 decay heat train A continuation",
                "planned_start_offset_hours": 150,
                "planned_duration_hours": 20,
                "oos_safety_function_id": safety_function["id"],
                "oos_train_label": "A",
                "predecessor_activity_id": foreign["id"],
            },
            make_outage_planner_headers(),
        )
        validate_error(response, ApiErrorId.PREDECESSOR_OUTAGE_MISMATCH.value)


def _locked_outage_with_two_permits(dose_budget_total_mrem, station_unit, area_code, designation):
    """One approved work order carrying a 750.00-mrem permit and a 432.00-mrem
    draft, against the supplied dose budget."""
    set_clock(CLOCK_EPOCH)
    rad_area = given_rad_area(
        station_unit=station_unit,
        area_code=area_code,
        dose_rate_mrem_per_hr=25,
        survey_buffer_hours=2,
    )
    outage = given_outage(
        station_unit=station_unit,
        designation=designation,
        dose_budget_total_mrem=dose_budget_total_mrem,
    )
    given_approved_core_load_pattern(outage["id"])
    work_order = given_approved_work_order(
        outage["id"],
        wo_type=WorkOrderType.INSPECTION,
        title="Reactor cavity inspection campaign",
        estimated_hours=200,
        estimated_cost_usd=500000,
        estimated_dose_mrem=400,
        requires_rad_work=True,
    )
    permit_a = given_draft_rwp(
        work_order["id"],
        rad_area["id"],
        worker_count=5,
        shielding_factor=0,
        planned_start_offset_hours=0,
        planned_duration_hours=5,
    )
    permit_b = given_draft_rwp(
        work_order["id"],
        rad_area["id"],
        worker_count=3,
        shielding_factor=0.2,
        planned_start_offset_hours=20,
        planned_duration_hours=6,
    )
    validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
    return outage, permit_a, permit_b


class TestAlaraRatioBoundary:
    def test_remaining_exactly_one_quarter_of_total_is_restricted(self):
        """250 remaining against a 1000-mrem total is exactly one quarter, and the
        inclusive comparison makes that RESTRICTED, which parks the other draft.

        PRD 3.7: "The unrounded comparison matters at the boundary: a
        remaining-to-total position of 250 against 1000 is exactly one quarter and
        is `RESTRICTED`, while 251 against 1001 is very slightly above one quarter
        and is `NORMAL`."

        Design: Difficulty/boundary_precision_check/alara_ratio_exactly_one_quarter_is_restricted
        """
        outage, permit_a, permit_b = _locked_outage_with_two_permits(
            1000, StationUnit.UNIT_1, "RA-6", "1R24"
        )
        validate_success(
            api_client.approve_rwp(
                permit_a["id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-1R24-001",
            )
        )
        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(750.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(250.00, abs=0.01)
        assert after["alara_posture"] == AlaraPosture.RESTRICTED
        assert read_rwp(permit_b["id"])["status"] == RwpStatus.HELD_FOR_ALARA
        assert_dose_budget_consistent(after)

    def test_remaining_just_above_one_quarter_stays_normal(self):
        """251 remaining against a 1001-mrem total is fractionally above one
        quarter, so the posture stays NORMAL and no hold cascade runs.

        PRD 3.7: "`alara_posture` is `SUSPENDED` when the remaining budget is less
        than or equal to zero; otherwise it is `RESTRICTED` when the ratio is less
        than or equal to 0.25; otherwise it is `NORMAL`."

        Design: Difficulty/boundary_precision_check/alara_ratio_exactly_one_quarter_is_restricted
        """
        outage, permit_a, permit_b = _locked_outage_with_two_permits(
            1001, StationUnit.UNIT_2, "RA-7", "2R26"
        )
        validate_success(
            api_client.approve_rwp(
                permit_a["id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-2R26-001",
            )
        )
        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(750.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(251.00, abs=0.01)
        assert after["alara_posture"] == AlaraPosture.NORMAL
        assert read_rwp(permit_b["id"])["status"] == RwpStatus.DRAFT


class TestAuthorizeStartupWithEmptySequence:
    def _executing_outage_with_completed_scope(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            title="Feedwater pump overhaul",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        activity = given_schedule_activity(
            outage["id"],
            label="Pump overhaul",
            planned_start_offset_hours=0,
            planned_duration_hours=10,
            work_order_id=work_order["id"],
        )
        validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )
        validate_success(
            api_client.start_activity(activity["id"], make_outage_planner_headers())
        )
        validate_success(
            api_client.complete_activity(activity["id"], make_outage_planner_headers())
        )
        return outage, work_order

    def test_startup_authorization_is_refused_while_the_sequence_is_empty(self):
        """Every other startup gate is satisfied --- the only work order is
        COMPLETE and no activity holds a safety function --- yet the outage owns no
        startup test at all.

        PRD 3.6: "The outage must own at least one startup test, otherwise
        `ERR_STARTUP_SEQUENCE_EMPTY` — an outage with an empty startup sequence
        cannot be authorized into startup."

        Design: Difficulty/boundary_precision_check/authorize_startup_with_empty_startup_sequence_rejected
        """
        outage, work_order = self._executing_outage_with_completed_scope()
        response = api_client.authorize_startup(
            outage["id"], make_outage_director_headers()
        )
        validate_error(response, ApiErrorId.STARTUP_SEQUENCE_EMPTY.value)
        assert read_outage(outage["id"])["status"] == OutageStatus.EXECUTION

    def test_one_pending_test_is_enough_to_open_the_gate(self):
        """Adding a single PENDING test --- not a satisfied one --- turns the same
        rejected request into a successful transition to STARTUP.

        PRD 3.6: "The outage's `version` increments by 1, and the startup tests
        become satisfiable in `sequence_index` order."

        Design: Difficulty/boundary_precision_check/authorize_startup_with_empty_startup_sequence_rejected
        """
        outage, _work_order = self._executing_outage_with_completed_scope()
        validate_error(
            api_client.authorize_startup(outage["id"], make_outage_director_headers()),
            ApiErrorId.STARTUP_SEQUENCE_EMPTY.value,
        )
        test_row = given_startup_test(
            outage["id"],
            test_code="CRD-DROP",
            sequence_index=1,
            predicted_reactivity_pcm=500,
        )
        assert test_row["status"] == "PENDING"

        authorized = validate_success(
            api_client.authorize_startup(outage["id"], make_outage_director_headers())
        )
        assert authorized["status"] == OutageStatus.STARTUP


class TestRwpApprovalNeedsAnApprovedWorkOrder:
    def _locked_outage_with_permit_on_planned_work_order(self):
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            area_code="RA-8", dose_rate_mrem_per_hr=25, survey_buffer_hours=2
        )
        outage = given_outage(designation="2R26", dose_budget_total_mrem=5000)
        given_approved_core_load_pattern(outage["id"])
        given_approved_work_order(
            outage["id"],
            title="WO1 baseline scope",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        covering = given_planned_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="WO2 containment inspection",
            estimated_hours=40,
            estimated_cost_usd=250000,
            estimated_dose_mrem=0,
            requires_rad_work=True,
        )
        permit = given_draft_rwp(
            covering["id"],
            rad_area["id"],
            worker_count=2,
            shielding_factor=0.5,
            planned_start_offset_hours=0,
            planned_duration_hours=6,
        )
        validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        return outage, covering, permit

    def test_permit_approval_is_refused_while_its_work_order_is_only_planned(self):
        """Everything else about the permit is admissible --- 180.00 mrem needs no
        ALARA reference and the outage is SCOPE_LOCKED --- but the covering work
        order has not been approved.

        PRD 3.7: "The covering work order must itself be in `APPROVED`, otherwise
        `ERR_WORK_ORDER_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/rwp_approve_requires_owning_work_order_approved
        """
        outage, _covering, permit = self._locked_outage_with_permit_on_planned_work_order()
        assert permit["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)
        assert permit["alara_review_required"] is False

        response = api_client.approve_rwp(
            permit["id"], make_rad_protection_manager_headers()
        )
        validate_error(response, ApiErrorId.WORK_ORDER_NOT_APPROVED.value)

        assert read_rwp(permit["id"])["status"] == RwpStatus.DRAFT
        rows = validate_success(
            api_client.list_dose_transactions(
                permit["id"], make_rad_protection_manager_headers()
            )
        )
        assert rows == []
        assert read_outage(outage["id"])["status"] == OutageStatus.SCOPE_LOCKED

    def test_approving_the_work_order_admits_the_identical_permit_request(self):
        """Holding every other input constant, moving the covering work order to
        APPROVED turns the rejection into a successful dose commitment.

        PRD 3.7: "Hop two replays the ledger to refresh the outage's
        `dose_committed_mrem` and `dose_budget_remaining_mrem`."

        Design: Difficulty/cross_entity_state_dependency/rwp_approve_requires_owning_work_order_approved
        """
        outage, covering, permit = self._locked_outage_with_permit_on_planned_work_order()
        validate_error(
            api_client.approve_rwp(permit["id"], make_rad_protection_manager_headers()),
            ApiErrorId.WORK_ORDER_NOT_APPROVED.value,
        )
        approved_wo = validate_success(
            api_client.approve_work_order_scope(
                covering["id"], make_outage_director_headers()
            )
        )
        assert approved_wo["status"] == WorkOrderStatus.APPROVED

        approved = validate_success(
            api_client.approve_rwp(permit["id"], make_rad_protection_manager_headers())
        )
        assert approved["status"] == RwpStatus.APPROVED
        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(180.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(4820.00, abs=0.01)


class TestDischargeReservationNeedsAnApprovedPattern:
    def _pool_outage_and_draft_pattern(self):
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            cells_total=1200, cells_baseline_occupied=900, full_core_offload_reserve_cells=193
        )
        outage = given_outage(designation="2R26")
        pattern = given_core_load_pattern(outage["id"])
        return pool, outage, pattern

    def _book(self, outage_id, pool_id, purpose, cells, pool_version_value):
        return api_client.create_pool_cell_reservation(
            {
                "outage_id": outage_id,
                "spent_fuel_pool_id": pool_id,
                "cells_requested": cells,
                "purpose": purpose,
                "expected_spent_fuel_pool_version": pool_version_value,
            },
            make_reactor_engineer_headers(),
        )

    def test_discharge_is_refused_while_the_pattern_is_only_drafted(self):
        """A five-cell DISCHARGE booking fits the protected headroom comfortably,
        but the outage owns no approved reload design; an identical CONTINGENCY
        booking is admitted because it carries no such guard.

        PRD 3.3: "A `DISCHARGE` reservation carries one additional guard: the
        consuming outage must already own a core loading pattern in `APPROVED`,
        otherwise the request is rejected with
        `ERR_CORE_LOAD_PATTERN_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/discharge_reservation_requires_approved_core_load_pattern
        """
        pool, outage, _pattern = self._pool_outage_and_draft_pattern()
        first_version = read_pool(pool["id"])["version"]

        refused = self._book(
            outage["id"], pool["id"], ReservationPurpose.DISCHARGE, 5, first_version
        )
        validate_error(refused, ApiErrorId.CORE_LOAD_PATTERN_NOT_APPROVED.value)
        untouched = read_pool(pool["id"])
        assert untouched["cells_reserved"] == 0
        assert untouched["version"] == first_version

        admitted = validate_success(
            self._book(
                outage["id"], pool["id"], ReservationPurpose.CONTINGENCY, 5, first_version
            ),
            201,
        )
        assert admitted["availability_variant"] == AvailabilityVariant.NOMINAL

    def test_approving_the_pattern_admits_the_discharge_booking(self):
        """Once the design is APPROVED the same DISCHARGE request succeeds under
        the FULL_CORE_PROTECTED variant, and the pool ledger carries both
        bookings.

        PRD 3.3: "a `DISCHARGE` or `FRESH_STAGING` reservation is a planned,
        long-dwell occupancy and takes the `FULL_CORE_PROTECTED` variant, while a
        `CONTINGENCY` reservation — precisely the unplanned condition the reserve
        block exists to absorb — takes the `NOMINAL` variant."

        Design: Difficulty/cross_entity_state_dependency/discharge_reservation_requires_approved_core_load_pattern
        """
        pool, outage, pattern = self._pool_outage_and_draft_pattern()
        version_one = read_pool(pool["id"])["version"]
        validate_success(
            self._book(
                outage["id"], pool["id"], ReservationPurpose.CONTINGENCY, 5, version_one
            ),
            201,
        )
        approved_pattern = validate_success(
            api_client.approve_core_load_pattern(
                pattern["id"], make_reactor_engineer_headers("re-beta")
            )
        )
        assert approved_pattern["reactivity_margin_pcm"] == pytest.approx(1586.00, abs=0.01)

        version_two = read_pool(pool["id"])["version"]
        discharge = validate_success(
            self._book(
                outage["id"], pool["id"], ReservationPurpose.DISCHARGE, 5, version_two
            ),
            201,
        )
        assert discharge["availability_variant"] == AvailabilityVariant.FULL_CORE_PROTECTED

        after = read_pool(pool["id"])
        assert after["cells_reserved"] == 10
        assert after["cells_occupied"] == 900
        assert after["cells_available"] == 290
        assert after["protected_cells_available"] == 97
