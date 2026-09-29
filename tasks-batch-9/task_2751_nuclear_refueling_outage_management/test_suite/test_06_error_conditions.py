"""Error conditions: not-found codes, own-state refusals and the guards that
sit above them in the rejection order."""

import pytest

from test_helpers import (
    AlaraPosture,
    ApiErrorId,
    BackgroundOutcome,
    CLOCK_EPOCH,
    ConstraintStatus,
    CoreLoadPatternStatus,
    Craft,
    Disposition,
    DoseDirection,
    DoseReason,
    EmergentItemStatus,
    ExecutionStatus,
    HoldPointType,
    NON_EXISTENT_UUID,
    OutageStatus,
    ReservationPurpose,
    ReservationStatus,
    RwpStatus,
    StartupTestStatus,
    StationUnit,
    WorkOrderStatus,
    WorkOrderType,
    WorkerStatus,
    api_client,
    assert_same_instant,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_badged_worker,
    given_disposed_emergent_item,
    given_draft_rwp,
    given_emergent_item,
    given_executing_outage,
    given_outage,
    given_pool_cell_reservation,
    given_rad_area,
    given_schedule_activity,
    given_scope_locked_outage,
    given_spent_fuel_pool,
    given_startup_test,
    given_supplemental_worker,
    given_work_order,
    make_access_authority_headers,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    make_station_admin_headers,
    read_activity,
    read_dose_rows,
    read_emergent_item,
    read_outage,
    read_pattern,
    read_pool,
    read_reservation,
    read_rwp,
    read_startup_test,
    read_work_order,
    read_worker,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSingleRowReadsAnswerWithTheirOwnNotFoundCode:
    def test_eleven_unknown_identifiers_yield_eleven_distinct_codes(self):
        """Against an empty database the same well-formed but unknown UUID is
        read through eleven single-row endpoints, and each family answers with
        its own 404 rather than a shared generic code.

        PRD 2.6: "The not-found codes are `ERR_OUTAGE_NOT_FOUND`,
        `ERR_SPENT_FUEL_POOL_NOT_FOUND`, `ERR_RAD_AREA_NOT_FOUND`,
        `ERR_SAFETY_FUNCTION_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
        `ERR_SCHEDULE_ACTIVITY_NOT_FOUND`, `ERR_CORE_LOAD_PATTERN_NOT_FOUND`,
        `ERR_POOL_RESERVATION_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`,
        `ERR_RWP_NOT_FOUND`, `ERR_EMERGENT_ITEM_NOT_FOUND` and
        `ERR_STARTUP_TEST_NOT_FOUND`, each carrying HTTP 404."

        Design: Corner/errors/every_path_id_error_is_reachable_with_an_unknown_uuid
        """
        set_clock(CLOCK_EPOCH)
        missing = NON_EXISTENT_UUID
        reads = [
            (
                api_client.get_spent_fuel_pool(missing, make_station_admin_headers()),
                ApiErrorId.SPENT_FUEL_POOL_NOT_FOUND.value,
            ),
            (
                api_client.get_rad_area(missing, make_station_admin_headers()),
                ApiErrorId.RAD_AREA_NOT_FOUND.value,
            ),
            (
                api_client.get_safety_function(missing, make_station_admin_headers()),
                ApiErrorId.SAFETY_FUNCTION_NOT_FOUND.value,
            ),
            (
                api_client.get_work_order(missing, make_outage_planner_headers()),
                ApiErrorId.WORK_ORDER_NOT_FOUND.value,
            ),
            (
                api_client.get_schedule_activity(missing, make_outage_planner_headers()),
                ApiErrorId.SCHEDULE_ACTIVITY_NOT_FOUND.value,
            ),
            (
                api_client.get_core_load_pattern(missing, make_reactor_engineer_headers()),
                ApiErrorId.CORE_LOAD_PATTERN_NOT_FOUND.value,
            ),
            (
                api_client.get_pool_cell_reservation(
                    missing, make_reactor_engineer_headers()
                ),
                ApiErrorId.POOL_RESERVATION_NOT_FOUND.value,
            ),
            (
                api_client.get_supplemental_worker(missing, make_access_authority_headers()),
                ApiErrorId.WORKER_NOT_FOUND.value,
            ),
            (
                api_client.get_rwp(missing, make_rad_protection_planner_headers()),
                ApiErrorId.RWP_NOT_FOUND.value,
            ),
            (
                api_client.get_emergent_item(missing, make_outage_planner_headers()),
                ApiErrorId.EMERGENT_ITEM_NOT_FOUND.value,
            ),
            (
                api_client.get_startup_test(missing, make_regulatory_affairs_headers()),
                ApiErrorId.STARTUP_TEST_NOT_FOUND.value,
            ),
            (
                api_client.get_outage(missing, make_outage_director_headers()),
                ApiErrorId.OUTAGE_NOT_FOUND.value,
            ),
        ]
        for response, expected_error_id in reads:
            validate_error(response, expected_error_id, 404)

        seen = [expected for _response, expected in reads]
        assert len(set(seen)) == len(seen), (
            "each entity family must answer for itself, never with a shared code"
        )


class TestBodyForeignKeysNameTheMissingEntity:
    def _outage_with_one_approved_work_order(self):
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            station_unit=StationUnit.UNIT_1,
            cells_total=1200,
            cells_baseline_occupied=900,
            full_core_offload_reserve_cells=193,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Containment survey",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        return pool, outage, work_order

    def test_five_resolvable_paths_still_answer_for_their_unknown_body_keys(self):
        """Every path segment resolves in all five requests, so the 404 that
        comes back has to describe the body reference — a safety function, a rad
        area, a work order, a predecessor activity or an outage.

        PRD 2.6: "A `safety_function_id`, `rad_area_id`, `spent_fuel_pool_id`,
        `outage_id`, `work_order_id` or `predecessor_activity_id` that names no
        stored row also yields the corresponding 404 code —
        `ERR_SAFETY_FUNCTION_NOT_FOUND`, `ERR_RAD_AREA_NOT_FOUND`,
        `ERR_SPENT_FUEL_POOL_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`,
        `ERR_WORK_ORDER_NOT_FOUND` or `ERR_SCHEDULE_ACTIVITY_NOT_FOUND`
        respectively."

        Design: Corner/errors/body_foreign_key_errors_name_the_missing_entity
        """
        pool, outage, work_order = self._outage_with_one_approved_work_order()
        pool_version_before = read_pool(pool["id"])["version"]

        validate_error(
            api_client.create_work_order(
                outage["id"],
                {
                    "wo_type": WorkOrderType.MAINTENANCE,
                    "title": "Unknown safety function",
                    "estimated_hours": 10,
                    "estimated_cost_usd": 1000,
                    "estimated_dose_mrem": 0,
                    "safety_function_id": NON_EXISTENT_UUID,
                },
                make_outage_planner_headers(),
            ),
            ApiErrorId.SAFETY_FUNCTION_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.draft_rwp(
                work_order["id"],
                {
                    "rad_area_id": NON_EXISTENT_UUID,
                    "worker_count": 2,
                    "shielding_factor": 0.5,
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 6,
                },
                make_rad_protection_planner_headers(),
            ),
            ApiErrorId.RAD_AREA_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_schedule_activity(
                outage["id"],
                {
                    "label": "Unknown work order",
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 10,
                    "work_order_id": NON_EXISTENT_UUID,
                },
                make_outage_planner_headers(),
            ),
            ApiErrorId.WORK_ORDER_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_schedule_activity(
                outage["id"],
                {
                    "label": "Unknown predecessor",
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 10,
                    "predecessor_activity_id": NON_EXISTENT_UUID,
                },
                make_outage_planner_headers(),
            ),
            ApiErrorId.SCHEDULE_ACTIVITY_NOT_FOUND.value,
            404,
        )
        validate_error(
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": NON_EXISTENT_UUID,
                    "spent_fuel_pool_id": pool["id"],
                    "cells_requested": 10,
                    "purpose": ReservationPurpose.CONTINGENCY,
                    "expected_spent_fuel_pool_version": pool_version_before,
                },
                make_reactor_engineer_headers(),
            ),
            ApiErrorId.OUTAGE_NOT_FOUND.value,
            404,
        )

        work_orders, wo_meta = validate_paginated(
            api_client.list_work_orders(make_outage_planner_headers(), outage_id=outage["id"])
        )
        assert len(work_orders) == 1
        assert wo_meta["total_count"] == 1
        activities, activity_meta = validate_paginated(
            api_client.list_schedule_activities(
                make_outage_planner_headers(), outage_id=outage["id"]
            )
        )
        assert activities == []
        assert activity_meta["total_count"] == 0

        after = read_pool(pool["id"])
        assert after["cells_reserved"] == 0
        assert after["version"] == pool_version_before, (
            "the refused reservation neither reserved cells nor bumped the pool"
        )


class TestOwnStateRefusalsOnScopeAndSchedule:
    def _outage_with_a_scoped_order_a_fresh_activity_and_an_approved_pattern(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        work_order = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Still scoped",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        activity = given_schedule_activity(
            outage["id"],
            label="Not started yet",
            planned_start_offset_hours=0,
            planned_duration_hours=10,
        )
        pattern = given_approved_core_load_pattern(
            outage["id"],
            cycle_length_mwd_mtu=18000,
            fresh_assembly_count=88,
            discharge_assembly_count=80,
        )
        assert work_order["status"] == WorkOrderStatus.SCOPED
        assert activity["execution_status"] == ExecutionStatus.NOT_STARTED
        assert pattern["status"] == CoreLoadPatternStatus.APPROVED
        return outage, work_order, activity, pattern

    def test_three_triggers_legal_from_another_state_are_refused_on_own_state(self):
        """Deferral is declared from PLANNED and APPROVED but not from SCOPED,
        completion from IN_PROGRESS but not from NOT_STARTED, and approval from
        DRAFT but not from APPROVED, so each refusal names its own entity's
        state code and leaves all three rows unmoved.

        PRD 2.8: "Own-state precondition: the resource named in the path is in a
        state from which the requested transition is declared — otherwise that
        resource type's state code (`ERR_OUTAGE_STATE_INVALID`,
        `ERR_WORK_ORDER_STATE_INVALID`, `ERR_ACTIVITY_STATE_INVALID`,
        `ERR_CORE_LOAD_PATTERN_STATE_INVALID`,
        `ERR_POOL_RESERVATION_STATE_INVALID`, `ERR_WORKER_STATE_INVALID`,
        `ERR_RWP_STATE_INVALID`, `ERR_EMERGENT_ITEM_STATE_INVALID` or
        `ERR_STARTUP_TEST_STATE_INVALID`, each HTTP 409)."

        Design: Corner/errors/state_invalid_errors_for_the_scope_and_schedule_entities
        """
        _outage, work_order, activity, pattern = (
            self._outage_with_a_scoped_order_a_fresh_activity_and_an_approved_pattern()
        )

        validate_error(
            api_client.defer_work_order(
                work_order["id"],
                "Removed from outage scope",
                make_outage_director_headers(),
            ),
            ApiErrorId.WORK_ORDER_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.complete_activity(activity["id"], make_outage_planner_headers()),
            ApiErrorId.ACTIVITY_STATE_INVALID.value,
            409,
        )
        validate_error(
            api_client.approve_core_load_pattern(
                pattern["id"], make_reactor_engineer_headers("re-gamma")
            ),
            ApiErrorId.CORE_LOAD_PATTERN_STATE_INVALID.value,
            409,
        )

        assert read_work_order(work_order["id"])["status"] == WorkOrderStatus.SCOPED
        after_activity = read_activity(activity["id"])
        assert after_activity["execution_status"] == ExecutionStatus.NOT_STARTED
        assert after_activity["completed_at"] is None
        after_pattern = read_pattern(pattern["id"])
        assert after_pattern["status"] == CoreLoadPatternStatus.APPROVED
        assert after_pattern["approved_by_user_id"] == "re-beta", (
            "the second approval was refused on own state, not on the two-person rule"
        )


class TestOwnStateRefusalsOnWorkforceAndPermits:
    def _outage_with_a_requested_worker_a_draft_permit_and_a_reservation(self):
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            station_unit=StationUnit.UNIT_1,
            cells_total=1200,
            cells_baseline_occupied=900,
            full_core_offload_reserve_cells=193,
        )
        rad_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="CTMT-EL471",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Containment survey",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        permit = given_draft_rwp(
            work_order["id"],
            rad_area["id"],
            worker_count=2,
            shielding_factor=0.5,
            planned_start_offset_hours=0,
            planned_duration_hours=6,
        )
        worker = given_supplemental_worker(
            outage["id"],
            full_name="R. Kowalski",
            craft=Craft.PIPEFITTER,
            sponsoring_contractor="Northline Mechanical",
        )
        reservation = given_pool_cell_reservation(
            outage["id"],
            pool["id"],
            cells_requested=10,
            purpose=ReservationPurpose.CONTINGENCY,
        )
        assert worker["status"] == WorkerStatus.REQUESTED
        assert permit["status"] == RwpStatus.DRAFT
        assert reservation["status"] == ReservationStatus.RESERVED
        return pool, outage, permit, worker, reservation

    def test_badging_before_the_join_and_voiding_twice_are_both_refused(self):
        """Neither qualification branch has been recorded, so the worker is
        still REQUESTED and cannot be badged; the permit voids once from DRAFT
        without touching the dose ledger and then refuses the repeat, because
        VOIDED accepts no second void.

        PRD 3.5: "The worker must be in `BADGE_READY`, otherwise
        `ERR_WORKER_STATE_INVALID` — badging a worker still in `SCREENING` is
        exactly this rejection."

        Design: Corner/errors/state_invalid_errors_for_the_workforce_and_permit_entities
        """
        _pool, outage, permit, worker, _reservation = (
            self._outage_with_a_requested_worker_a_draft_permit_and_a_reservation()
        )

        validate_error(
            api_client.badge_worker(worker["id"], "B-1000", make_access_authority_headers()),
            ApiErrorId.WORKER_STATE_INVALID.value,
            409,
        )
        assert read_worker(worker["id"])["status"] == WorkerStatus.REQUESTED
        assert read_outage(outage["id"])["badged_worker_count"] == 0

        voided = validate_success(
            api_client.void_rwp(
                permit["id"], "Work scope withdrawn", make_rad_protection_manager_headers()
            )
        )
        assert voided["status"] == RwpStatus.VOIDED
        assert read_dose_rows(permit["id"]) == [], (
            "an unapproved permit held no committed dose to release"
        )

        validate_error(
            api_client.void_rwp(
                permit["id"], "Duplicate withdrawal", make_rad_protection_manager_headers()
            ),
            ApiErrorId.RWP_STATE_INVALID.value,
            409,
        )
        assert read_rwp(permit["id"])["void_reason"] == "Work scope withdrawn"

    def test_a_released_reservation_refuses_consumption_before_the_outage_check(self):
        """The reservation is RELEASED and the owning outage is still in
        PLANNING, so two rules are broken at once — and the own-state rung
        answers first, leaving the pool ledger exactly where the release left it.

        PRD 3.3: "Consuming a reservation moves it `RESERVED → CONSUMED` and
        requires the owning outage to be in `SCOPE_LOCKED` or `EXECUTION`,
        otherwise `ERR_OUTAGE_STATE_INVALID`; a reservation that is not in
        `RESERVED` yields `ERR_POOL_RESERVATION_STATE_INVALID`."

        Design: Corner/errors/state_invalid_errors_for_the_workforce_and_permit_entities
        """
        pool, _outage, _permit, _worker, reservation = (
            self._outage_with_a_requested_worker_a_draft_permit_and_a_reservation()
        )

        released = validate_success(
            api_client.release_pool_cell_reservation(
                reservation["id"],
                "Contingency capacity no longer required",
                make_reactor_engineer_headers(),
            )
        )
        assert released["status"] == ReservationStatus.RELEASED

        validate_error(
            api_client.consume_pool_cell_reservation(
                reservation["id"], make_reactor_engineer_headers()
            ),
            ApiErrorId.POOL_RESERVATION_STATE_INVALID.value,
            409,
        )
        assert read_reservation(reservation["id"])["status"] == ReservationStatus.RELEASED

        after = read_pool(pool["id"])
        assert after["cells_occupied"] == 900
        assert after["cells_reserved"] == 0


class TestOwnStateRefusalsOnEmergentAndStartupRows:
    def _online_outage_with_a_rejected_item_and_a_satisfied_test(self):
        ctx = given_executing_outage(
            outage={
                "station_unit": StationUnit.UNIT_1,
                "designation": "1R24",
                "duration_target_hours": 720,
                "dose_budget_total_mrem": 5000,
                "cost_budget_usd": 40000000,
            },
            work_order={
                "wo_type": WorkOrderType.INSPECTION,
                "title": "Steam generator eddy current",
                "estimated_hours": 40,
                "estimated_cost_usd": 200000,
                "estimated_dose_mrem": 50,
            },
        )
        item = given_emergent_item(
            ctx["work_order_id"],
            description="Corroded support hanger",
            estimated_hours=8,
            estimated_cost_usd=12000,
            estimated_dose_mrem=10,
            discovered_during_inspection=True,
        )
        disposed = given_disposed_emergent_item(
            item["id"],
            disposition=Disposition.REJECTED,
            disposition_note="Deferred to the next cycle",
        )
        assert disposed["status"] == EmergentItemStatus.REJECTED
        assert disposed["created_work_order_id"] is None

        test_row = given_startup_test(
            ctx["outage_id"],
            test_code="RCS-HEATUP",
            sequence_index=1,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=500,
        )
        validate_success(
            api_client.defer_work_order(
                ctx["work_order_id"],
                "Removed from outage scope",
                make_outage_director_headers(),
            )
        )
        validate_success(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
        )
        satisfied = validate_success(
            api_client.satisfy_startup_test(
                test_row["id"], 560, make_regulatory_affairs_headers()
            )
        )
        assert satisfied["status"] == StartupTestStatus.SATISFIED
        assert satisfied["reactivity_deviation_pcm"] == pytest.approx(60.00, abs=0.01)
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.ONLINE
        return ctx, item, test_row

    def test_a_disposed_item_and_a_satisfied_test_both_refuse_a_repeat(self):
        """Re-dispositioning to the very same value is still refused, and the
        satisfied test answers on its own state rather than on the ONLINE outage
        it now belongs to, so neither row is overwritten.

        PRD 3.9: "The test must be in `PENDING` or `FAILED`, otherwise
        `ERR_STARTUP_TEST_STATE_INVALID` — a test already `SATISFIED` cannot be
        re-measured."

        Design: Corner/errors/state_invalid_errors_for_the_emergent_and_startup_entities
        """
        _ctx, item, test_row = self._online_outage_with_a_rejected_item_and_a_satisfied_test()

        validate_error(
            api_client.dispose_emergent_item(
                item["id"],
                Disposition.REJECTED,
                make_outage_director_headers(),
                disposition_note="Second look",
            ),
            ApiErrorId.EMERGENT_ITEM_STATE_INVALID.value,
            409,
        )
        after_item = read_emergent_item(item["id"])
        assert after_item["disposition_note"] == "Deferred to the next cycle"
        assert after_item["created_work_order_id"] is None, (
            "a REJECTED disposition mints nothing, twice over"
        )

        validate_error(
            api_client.satisfy_startup_test(
                test_row["id"], 500, make_regulatory_affairs_headers()
            ),
            ApiErrorId.STARTUP_TEST_STATE_INVALID.value,
            409,
        )
        after_test = read_startup_test(test_row["id"])
        assert after_test["measured_reactivity_pcm"] == pytest.approx(560, abs=0.01)
        assert after_test["reactivity_deviation_pcm"] == pytest.approx(60.00, abs=0.01)


def _scope_locked_outage_with_two_draft_permits(
    dose_budget_total_mrem, second_permit_duration_hours
):
    """Two permits on two separate rad areas, so their buffered windows can
    never collide and only the dose rules can decide the second approval."""
    set_clock(CLOCK_EPOCH)
    area_a = given_rad_area(
        station_unit=StationUnit.UNIT_1,
        area_code="CTMT-EL471",
        dose_rate_mrem_per_hr=25,
        occupancy_limit_workers=10,
        survey_buffer_hours=2,
    )
    area_b = given_rad_area(
        station_unit=StationUnit.UNIT_1,
        area_code="CTMT-EL500",
        dose_rate_mrem_per_hr=25,
        occupancy_limit_workers=10,
        survey_buffer_hours=2,
    )
    outage = given_outage(
        station_unit=StationUnit.UNIT_1,
        designation="1R24",
        duration_target_hours=720,
        dose_budget_total_mrem=dose_budget_total_mrem,
        cost_budget_usd=40000000,
    )
    given_approved_core_load_pattern(
        outage["id"],
        cycle_length_mwd_mtu=18000,
        fresh_assembly_count=88,
        discharge_assembly_count=80,
    )
    work_order_a = given_approved_work_order(
        outage["id"],
        wo_type=WorkOrderType.INSPECTION,
        title="Survey A",
        estimated_hours=60,
        estimated_cost_usd=100000,
        estimated_dose_mrem=100,
        requires_rad_work=True,
    )
    work_order_b = given_approved_work_order(
        outage["id"],
        wo_type=WorkOrderType.INSPECTION,
        title="Survey B",
        estimated_hours=60,
        estimated_cost_usd=100000,
        estimated_dose_mrem=100,
        requires_rad_work=True,
    )
    permit_a = given_draft_rwp(
        work_order_a["id"],
        area_a["id"],
        worker_count=2,
        shielding_factor=0.5,
        planned_start_offset_hours=0,
        planned_duration_hours=6,
    )
    permit_b = given_draft_rwp(
        work_order_b["id"],
        area_b["id"],
        worker_count=2,
        shielding_factor=0.5,
        planned_start_offset_hours=0,
        planned_duration_hours=second_permit_duration_hours,
    )
    assert permit_a["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)
    assert permit_a["alara_review_required"] is False
    validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
    return outage, permit_a, permit_b


class TestSuspendedPostureBlocksTheNextApproval:
    def test_the_next_approval_is_refused_on_posture_not_on_the_budget(self):
        """The first permit consumes exactly the whole 180 mrem budget and is
        admitted, which drives the remaining figure to zero and the posture to
        SUSPENDED; the second approval then breaks both the posture rule and the
        budget rule and reports the posture, which outranks it.

        PRD 3.7: "The outage's `alara_posture` must not be `SUSPENDED`,
        otherwise `ERR_ALARA_POSTURE_SUSPENDED` — a fully consumed dose budget
        blocks every further dose commitment."

        Design: Corner/errors/suspended_alara_posture_blocks_the_next_permit_approval
        """
        outage, permit_a, permit_b = _scope_locked_outage_with_two_draft_permits(180, 6)

        approved = validate_success(
            api_client.approve_rwp(permit_a["id"], make_rad_protection_manager_headers())
        )
        assert approved["status"] == RwpStatus.APPROVED, (
            "exact equality with the remaining budget is admitted, not rejected"
        )

        suspended = read_outage(outage["id"])
        assert suspended["dose_committed_mrem"] == pytest.approx(180.00, abs=0.01)
        assert suspended["dose_budget_remaining_mrem"] == pytest.approx(0.00, abs=0.01)
        assert suspended["alara_posture"] == AlaraPosture.SUSPENDED

        validate_error(
            api_client.approve_rwp(permit_b["id"], make_rad_protection_manager_headers()),
            ApiErrorId.ALARA_POSTURE_SUSPENDED.value,
            409,
        )

        assert read_rwp(permit_b["id"])["status"] == RwpStatus.DRAFT, (
            "180.00 does not exceed the 200 mrem hold threshold, so the posture "
            "flip never parked this permit in HELD_FOR_ALARA"
        )
        rows = read_dose_rows(permit_a["id"])
        assert len(rows) == 1
        assert rows[0]["direction"] == DoseDirection.COMMIT
        assert rows[0]["amount_mrem"] == pytest.approx(180.00, abs=0.01)
        assert rows[0]["reason"] == DoseReason.RWP_APPROVED
        assert read_dose_rows(permit_b["id"]) == []


class TestDoseBudgetRefusesAnOvershootingCommitment:
    def test_a_restricted_posture_lets_the_request_reach_the_budget_rule(self):
        """With a 200 mrem budget the first approval leaves 20.00 remaining at a
        ratio of one tenth, which is RESTRICTED rather than SUSPENDED, so the
        posture gate stays open and the 120.00 mrem second permit is refused by
        the dose budget itself.

        PRD 3.7: "And finally the permit's `committed_dose_mrem` must be less
        than or equal to the outage's `dose_budget_remaining_mrem`, otherwise
        `ERR_DOSE_BUDGET_EXCEEDED`; the comparison is inclusive, so a permit that
        consumes exactly the remaining budget is admitted — and drives the
        posture straight to `SUSPENDED`."

        Design: Corner/errors/dose_budget_exceeded_when_the_commitment_overshoots_the_remainder
        """
        outage, permit_a, permit_b = _scope_locked_outage_with_two_draft_permits(200, 4)
        validate_success(
            api_client.approve_rwp(permit_a["id"], make_rad_protection_manager_headers())
        )

        restricted = read_outage(outage["id"])
        assert restricted["dose_budget_remaining_mrem"] == pytest.approx(20.00, abs=0.01)
        assert restricted["alara_posture"] == AlaraPosture.RESTRICTED

        held = read_rwp(permit_b["id"])
        assert held["committed_dose_mrem"] == pytest.approx(120.00, abs=0.01)
        assert held["status"] == RwpStatus.DRAFT

        validate_error(
            api_client.approve_rwp(permit_b["id"], make_rad_protection_manager_headers()),
            ApiErrorId.DOSE_BUDGET_EXCEEDED.value,
            409,
        )

        assert read_rwp(permit_b["id"])["status"] == RwpStatus.DRAFT
        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(180.00, abs=0.01), (
            "a refused approval writes no ledger row"
        )
        assert read_dose_rows(permit_b["id"]) == []


class TestSetPredecessorRefusesToCloseALoop:
    def _outage_with_a_two_activity_chain(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        first = given_schedule_activity(
            outage["id"],
            label="A1 cavity flood-up",
            planned_start_offset_hours=0,
            planned_duration_hours=100,
        )
        second = given_schedule_activity(
            outage["id"],
            label="A2 core offload",
            planned_start_offset_hours=100,
            planned_duration_hours=150,
            predecessor_activity_id=first["id"],
        )
        return outage, first, second

    def test_both_the_two_hop_loop_and_the_self_reference_are_refused(self):
        """Chaining A1 behind A2 closes an A1 to A2 to A1 loop that only a walk
        of the chain can see, and naming A2 as its own predecessor closes the
        shortest loop of all; both answer with the same acyclicity code and
        neither edge is written.

        PRD 2.6: "Beyond mere existence, two graph-shape rules are enforced on
        the schedule and are described where they arise in §3.4: an activity may
        not be chained behind an activity belonging to a different outage, nor
        linked to a work order belonging to a different outage
        (`ERR_PREDECESSOR_OUTAGE_MISMATCH`, HTTP 422), and following the
        predecessor chain from an activity must terminate at a chain root rather
        than revisit an activity already seen (`ERR_ACTIVITY_CYCLE`, HTTP 422)."

        Design: Corner/errors/set_predecessor_refuses_to_close_a_loop
        """
        outage, first, second = self._outage_with_a_two_activity_chain()

        validate_error(
            api_client.set_activity_predecessor(
                first["id"], second["id"], make_outage_planner_headers()
            ),
            ApiErrorId.ACTIVITY_CYCLE.value,
            422,
        )
        validate_error(
            api_client.set_activity_predecessor(
                second["id"], second["id"], make_outage_planner_headers()
            ),
            ApiErrorId.ACTIVITY_CYCLE.value,
            422,
        )

        assert read_activity(first["id"])["predecessor_activity_id"] is None
        assert read_activity(second["id"])["predecessor_activity_id"] == first["id"]

        after = read_outage(outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(250.00, abs=0.01), (
            "the 100 plus 150 hour chain is unchanged by the two refusals"
        )
        assert after["risk_adjusted_duration_hours"] == pytest.approx(275.00, abs=0.01)


class TestPredecessorFromAnotherOutageIsRefused:
    def test_a_resolvable_predecessor_on_the_wrong_outage_is_a_422(self):
        """The predecessor id names a real activity, so the existence rung
        passes and the request reaches the ownership rung, which refuses it
        because a schedule may not be chained across two refuelling outages.

        PRD 2.8: "Schedule graph ownership: a supplied predecessor or work order
        belongs to the same outage — otherwise `ERR_PREDECESSOR_OUTAGE_MISMATCH`
        (HTTP 422)."

        Design: Corner/errors/predecessor_from_another_outage_is_refused
        """
        set_clock(CLOCK_EPOCH)
        first_outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        second_outage = given_outage(
            station_unit=StationUnit.UNIT_2,
            designation="2R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        foreign = given_schedule_activity(
            first_outage["id"],
            label="A1 cavity flood-up on unit 1",
            planned_start_offset_hours=0,
            planned_duration_hours=100,
        )

        validate_error(
            api_client.create_schedule_activity(
                second_outage["id"],
                {
                    "label": "Cross-unit dependency attempt",
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 50,
                    "predecessor_activity_id": foreign["id"],
                },
                make_outage_planner_headers(),
            ),
            ApiErrorId.PREDECESSOR_OUTAGE_MISMATCH.value,
            422,
        )

        rows, meta = validate_paginated(
            api_client.list_schedule_activities(
                make_outage_planner_headers(), outage_id=second_outage["id"]
            )
        )
        assert rows == []
        assert meta["total_count"] == 0
        after = read_outage(second_outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(0.00, abs=0.01)
        assert after["critical_path_activity_id"] is None


class TestStartupSequenceUniquenessAndOrdering:
    def test_a_duplicate_index_and_a_skipped_index_are_both_refused(self):
        """One rule guards the sequence at creation and another guards it at
        satisfaction: index 1 cannot be issued twice, and index 2 cannot be
        satisfied while index 1 is still PENDING — after which the sequence walks
        cleanly and the outage bubbles to ONLINE on the last test alone.

        PRD 3.9: "Every test of the same outage with a strictly lower
        `sequence_index` must already be `SATISFIED`, otherwise
        `ERR_STARTUP_SEQUENCE_OUT_OF_ORDER`; the sequence is walked in order and
        cannot be skipped."

        Design: Corner/errors/startup_sequence_duplicate_and_out_of_order_are_both_refused
        """
        ctx = given_executing_outage(
            outage={
                "station_unit": StationUnit.UNIT_1,
                "designation": "1R24",
                "duration_target_hours": 720,
                "dose_budget_total_mrem": 5000,
                "cost_budget_usd": 40000000,
            },
            work_order={
                "wo_type": WorkOrderType.MAINTENANCE,
                "title": "Reactor coolant pump seal",
                "estimated_hours": 20,
                "estimated_cost_usd": 60000,
                "estimated_dose_mrem": 0,
            },
        )
        first = given_startup_test(
            ctx["outage_id"],
            test_code="RCS-HEATUP",
            sequence_index=1,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=500,
        )
        second = given_startup_test(
            ctx["outage_id"],
            test_code="CRITICALITY",
            sequence_index=2,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=500,
        )

        validate_error(
            api_client.create_startup_test(
                ctx["outage_id"],
                {
                    "test_code": "RCS-HEATUP-RETRY",
                    "sequence_index": 1,
                    "hold_point_type": HoldPointType.STATION,
                    "predicted_reactivity_pcm": 500,
                },
                make_reactor_engineer_headers(),
            ),
            ApiErrorId.STARTUP_SEQUENCE_DUPLICATE.value,
            409,
        )
        rows, meta = validate_paginated(
            api_client.list_startup_tests(ctx["outage_id"], make_regulatory_affairs_headers())
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2

        validate_success(
            api_client.defer_work_order(
                ctx["work_order_id"],
                "Removed from outage scope",
                make_outage_director_headers(),
            )
        )
        validate_success(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
        )

        validate_error(
            api_client.satisfy_startup_test(
                second["id"], 500, make_regulatory_affairs_headers()
            ),
            ApiErrorId.STARTUP_SEQUENCE_OUT_OF_ORDER.value,
            409,
        )
        assert read_startup_test(second["id"])["measured_reactivity_pcm"] is None

        cleared = validate_success(
            api_client.satisfy_startup_test(first["id"], 540, make_regulatory_affairs_headers())
        )
        assert cleared["status"] == StartupTestStatus.SATISFIED
        assert cleared["reactivity_deviation_pcm"] == pytest.approx(40.00, abs=0.01)
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.STARTUP

        last = validate_success(
            api_client.satisfy_startup_test(second["id"], 500, make_regulatory_affairs_headers())
        )
        assert last["status"] == StartupTestStatus.SATISFIED
        assert last["reactivity_deviation_pcm"] == pytest.approx(0.00, abs=0.01)
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.ONLINE


class TestRegulatoryHoldPointDemandsItsReleaseReference:
    def test_the_same_body_fails_on_a_regulatory_test_and_passes_on_a_station_one(self):
        """Both tests are measured 20 pcm from prediction, so tolerance can be no
        part of the outcome; the regulatory hold point refuses the bare
        satisfaction and the station hold point at the next index accepts exactly
        the same payload.

        PRD 3.9: "When the test's `hold_point_type` is `REGULATORY` the payload
        must supply a non-empty `nrc_release_reference` of 1 to 64 characters,
        otherwise `ERR_REGULATORY_HOLD_POINT_NOT_RELEASED`."

        Design: Corner/errors/regulatory_hold_point_demands_its_release_reference
        """
        ctx = given_executing_outage(
            outage={
                "station_unit": StationUnit.UNIT_1,
                "designation": "1R24",
                "duration_target_hours": 720,
                "dose_budget_total_mrem": 5000,
                "cost_budget_usd": 40000000,
            },
            work_order={
                "wo_type": WorkOrderType.MAINTENANCE,
                "title": "Main steam isolation valve stroke",
                "estimated_hours": 20,
                "estimated_cost_usd": 60000,
                "estimated_dose_mrem": 0,
            },
        )
        regulatory = validate_success(
            api_client.create_startup_test(
                ctx["outage_id"],
                {
                    "test_code": "MODE-3-HOLD",
                    "sequence_index": 1,
                    "hold_point_type": HoldPointType.REGULATORY,
                    "predicted_reactivity_pcm": 500,
                },
                make_reactor_engineer_headers(),
            ),
            201,
        )
        station = validate_success(
            api_client.create_startup_test(
                ctx["outage_id"],
                {
                    "test_code": "TURBINE-ROLL",
                    "sequence_index": 2,
                    "hold_point_type": HoldPointType.STATION,
                    "predicted_reactivity_pcm": 500,
                },
                make_reactor_engineer_headers(),
            ),
            201,
        )
        validate_success(
            api_client.defer_work_order(
                ctx["work_order_id"],
                "Removed from outage scope",
                make_outage_director_headers(),
            )
        )
        validate_success(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
        )

        validate_error(
            api_client.satisfy_startup_test(
                regulatory["id"], 520, make_regulatory_affairs_headers()
            ),
            ApiErrorId.REGULATORY_HOLD_POINT_NOT_RELEASED.value,
            422,
        )
        assert read_startup_test(regulatory["id"])["status"] == StartupTestStatus.PENDING

        released = validate_success(
            api_client.satisfy_startup_test(
                regulatory["id"],
                520,
                make_regulatory_affairs_headers(),
                nrc_release_reference="NRC-REL-2026-0031",
            )
        )
        assert released["status"] == StartupTestStatus.SATISFIED
        assert released["nrc_release_reference"] == "NRC-REL-2026-0031"
        assert released["reactivity_deviation_pcm"] == pytest.approx(20.00, abs=0.01)

        bare = validate_success(
            api_client.satisfy_startup_test(
                station["id"], 520, make_regulatory_affairs_headers()
            )
        )
        assert bare["status"] == StartupTestStatus.SATISFIED
        assert bare["nrc_release_reference"] is None, (
            "no release reference is demanded of a station hold point"
        )
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.ONLINE


def _badge_ready_worker(outage_id, full_name, craft):
    """Walks both fork branches of the onboarding pipeline and stops at the
    join, leaving the worker in BADGE_READY with no badge number."""
    worker = given_supplemental_worker(
        outage_id,
        full_name=full_name,
        craft=craft,
        sponsoring_contractor="Northline Mechanical",
    )
    validate_success(
        api_client.record_background_result(
            worker["id"], BackgroundOutcome.CLEAR, make_access_authority_headers()
        )
    )
    joined = validate_success(
        api_client.record_training_completion(
            worker["id"], 4, make_access_authority_headers()
        )
    )
    assert joined["status"] == WorkerStatus.BADGE_READY
    assert joined["badge_number"] is None
    return joined


class TestBadgeNumberIsUniqueAmongBadgedWorkers:
    def test_the_second_worker_is_refused_the_number_and_then_takes_another(self):
        """The first worker keeps B-1000, the second is refused it, and a
        distinct number is then accepted, so the outage's badged headcount moves
        one, one, two across the three calls.

        PRD 3.5: "The submitted `badge_number`, 1 to 24 characters, must not
        already be held by another worker of the same outage whose status is
        `BADGED`, otherwise `ERR_BADGE_NUMBER_TAKEN`; badge numbers held by
        denied or not-yet-badged workers do not block reuse."

        Design: Corner/errors/badge_number_already_held_within_the_outage
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        assert outage["required_training_modules"] == 4
        first = _badge_ready_worker(outage["id"], "R. Kowalski", Craft.PIPEFITTER)
        second = _badge_ready_worker(outage["id"], "T. Abiodun", Craft.ELECTRICIAN)

        badged = validate_success(
            api_client.badge_worker(first["id"], "B-1000", make_access_authority_headers())
        )
        assert badged["status"] == WorkerStatus.BADGED
        after_first = read_outage(outage["id"])
        assert after_first["badged_worker_count"] == 1

        validate_error(
            api_client.badge_worker(second["id"], "B-1000", make_access_authority_headers()),
            ApiErrorId.BADGE_NUMBER_TAKEN.value,
            409,
        )
        refused = read_worker(second["id"])
        assert refused["status"] == WorkerStatus.BADGE_READY
        assert refused["badge_number"] is None
        after_refusal = read_outage(outage["id"])
        assert after_refusal["badged_worker_count"] == 1
        assert after_refusal["version"] == after_first["version"], (
            "only a badge that is actually issued reprojects the outage"
        )

        renumbered = validate_success(
            api_client.badge_worker(second["id"], "B-1001", make_access_authority_headers())
        )
        assert renumbered["status"] == WorkerStatus.BADGED
        assert renumbered["badge_number"] == "B-1001"
        assert read_outage(outage["id"])["badged_worker_count"] == 2


class TestExecutionNeedsTheFullBadgedWorkforce:
    def test_the_gate_admits_at_exact_equality_and_not_one_badge_short(self):
        """With two badges required and one issued the outage cannot leave
        SCOPE_LOCKED; badging the second worker changes nothing else, and the
        identical call then succeeds because the comparison is inclusive.

        PRD 3.6: "Breaker-open moves the outage `SCOPE_LOCKED → EXECUTION`, and
        it has exactly one substantive gate: the outage's `badged_worker_count`
        must be greater than or equal to its `required_badged_workers`, otherwise
        the request is rejected with `ERR_BADGED_WORKFORCE_INSUFFICIENT`."

        Design: Corner/errors/commence_execution_needs_the_full_badged_workforce
        """
        ctx = given_scope_locked_outage(
            outage={
                "station_unit": StationUnit.UNIT_1,
                "designation": "1R24",
                "duration_target_hours": 720,
                "dose_budget_total_mrem": 5000,
                "cost_budget_usd": 40000000,
                "required_badged_workers": 2,
            },
            work_order={
                "wo_type": WorkOrderType.MODIFICATION,
                "title": "Feedwater heater replacement",
                "estimated_hours": 300,
                "estimated_cost_usd": 900000,
                "estimated_dose_mrem": 0,
            },
        )
        given_badged_worker(
            ctx["outage_id"],
            badge_number="B-1000",
            full_name="R. Kowalski",
            craft=Craft.PIPEFITTER,
        )
        waiting = _badge_ready_worker(ctx["outage_id"], "T. Abiodun", Craft.ELECTRICIAN)
        short_handed = read_outage(ctx["outage_id"])
        assert short_handed["required_badged_workers"] == 2
        assert short_handed["badged_worker_count"] == 1

        validate_error(
            api_client.commence_execution(
                ctx["outage_id"], make_outage_director_headers()
            ),
            ApiErrorId.BADGED_WORKFORCE_INSUFFICIENT.value,
            409,
        )
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.SCOPE_LOCKED

        promoted = validate_success(
            api_client.badge_worker(waiting["id"], "B-1001", make_access_authority_headers())
        )
        assert promoted["status"] == WorkerStatus.BADGED
        assert read_outage(ctx["outage_id"])["badged_worker_count"] == 2

        opened = validate_success(
            api_client.commence_execution(ctx["outage_id"], make_outage_director_headers())
        )
        assert opened["status"] == OutageStatus.EXECUTION


class TestBlockedActivityWaitsForItsPredecessor:
    def _executing_outage_with_a_blocked_successor(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Cavity decontamination",
            estimated_hours=100,
            estimated_cost_usd=200000,
            estimated_dose_mrem=0,
        )
        first = given_schedule_activity(
            outage["id"],
            label="A1 cavity flood-up",
            planned_start_offset_hours=0,
            planned_duration_hours=100,
        )
        second = given_schedule_activity(
            outage["id"],
            label="A2 fuel movement",
            planned_start_offset_hours=100,
            planned_duration_hours=150,
            predecessor_activity_id=first["id"],
        )
        assert second["constraint_status"] == ConstraintStatus.BLOCKED
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )
        assert read_work_order(work_order["id"])["status"] == WorkOrderStatus.APPROVED
        return outage, first, second

    def test_only_a_genuinely_complete_predecessor_releases_the_successor(self):
        """The successor is refused twice — once before its predecessor starts and
        once while it is merely IN_PROGRESS — and only the predecessor's
        completion clears the constraint dimension without disturbing the
        successor's own execution dimension.

        PRD 3.4: "Its `constraint_status` must be `CLEAR`, otherwise
        `ERR_PREDECESSOR_NOT_COMPLETE`; the owning outage must be in `EXECUTION`,
        otherwise `ERR_OUTAGE_STATE_INVALID`; and either the activity has no
        `work_order_id` at all, or the named work order's status is `APPROVED` or
        `EXECUTING`, otherwise `ERR_WORK_ORDER_NOT_APPROVED`."

        PRD 3.4: "every activity whose `predecessor_activity_id` names the
        just-completed activity has its `constraint_status` recomputed to `CLEAR`,
        processed in ascending `created_at` order, and their `execution_status`
        values are left entirely alone."

        Design: Corner/errors/blocked_activity_cannot_start_until_its_predecessor_completes
        """
        _outage, first, second = self._executing_outage_with_a_blocked_successor()

        validate_error(
            api_client.start_activity(second["id"], make_outage_planner_headers()),
            ApiErrorId.PREDECESSOR_NOT_COMPLETE.value,
            409,
        )
        assert read_activity(second["id"])["execution_status"] == ExecutionStatus.NOT_STARTED

        started = validate_success(
            api_client.start_activity(first["id"], make_outage_planner_headers())
        )
        assert started["execution_status"] == ExecutionStatus.IN_PROGRESS
        assert_same_instant(started["started_at"], CLOCK_EPOCH, "started_at")

        validate_error(
            api_client.start_activity(second["id"], make_outage_planner_headers()),
            ApiErrorId.PREDECESSOR_NOT_COMPLETE.value,
            409,
        )
        assert read_activity(second["id"])["constraint_status"] == ConstraintStatus.BLOCKED, (
            "an IN_PROGRESS predecessor does not satisfy the clear predicate"
        )

        validate_success(
            api_client.complete_activity(first["id"], make_outage_planner_headers())
        )
        released = read_activity(second["id"])
        assert released["constraint_status"] == ConstraintStatus.CLEAR
        assert released["execution_status"] == ExecutionStatus.NOT_STARTED, (
            "clearing the constraint dimension never advances the execution dimension"
        )

        finally_started = validate_success(
            api_client.start_activity(second["id"], make_outage_planner_headers())
        )
        assert finally_started["execution_status"] == ExecutionStatus.IN_PROGRESS


class TestStartupAuthorizationWaitsForOpenScopeWork:
    def test_an_approved_work_order_blocks_startup_until_it_is_deferred(self):
        """An outage that owns one APPROVED work order and one startup test
        clears the sequence gate but not the open-work gate; deferring the work
        order is enough on its own, and it also empties the approved scope rollup.

        PRD 3.6: "No work order of the outage may still be in `SCOPED`,
        `PLANNED`, `APPROVED` or `EXECUTING`, otherwise
        `ERR_OPEN_WORK_ORDERS_REMAIN`; only `COMPLETE` and `DEFERRED` work orders
        are acceptable at this gate."

        Design: Corner/errors/authorize_startup_refuses_while_scope_work_remains_open
        """
        ctx = given_executing_outage(
            outage={
                "station_unit": StationUnit.UNIT_1,
                "designation": "1R24",
                "duration_target_hours": 720,
                "dose_budget_total_mrem": 5000,
                "cost_budget_usd": 40000000,
            },
            work_order={
                "wo_type": WorkOrderType.MODIFICATION,
                "title": "Feedwater heater replacement",
                "estimated_hours": 300,
                "estimated_cost_usd": 900000,
                "estimated_dose_mrem": 0,
            },
        )
        given_startup_test(
            ctx["outage_id"],
            test_code="RCS-HEATUP",
            sequence_index=1,
            hold_point_type=HoldPointType.STATION,
            predicted_reactivity_pcm=500,
        )
        assert read_work_order(ctx["work_order_id"])["status"] == WorkOrderStatus.APPROVED

        validate_error(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers()),
            ApiErrorId.OPEN_WORK_ORDERS_REMAIN.value,
            409,
        )
        assert read_outage(ctx["outage_id"])["status"] == OutageStatus.EXECUTION

        deferred = validate_success(
            api_client.defer_work_order(
                ctx["work_order_id"],
                "Deferred to the next refueling window",
                make_outage_director_headers(),
            )
        )
        assert deferred["status"] == WorkOrderStatus.DEFERRED

        authorized = validate_success(
            api_client.authorize_startup(ctx["outage_id"], make_outage_director_headers())
        )
        assert authorized["status"] == OutageStatus.STARTUP
        assert authorized["approved_scope_cost_usd"] == pytest.approx(0.00, abs=0.01), (
            "a deferred work order leaves the approved scope rollup"
        )
