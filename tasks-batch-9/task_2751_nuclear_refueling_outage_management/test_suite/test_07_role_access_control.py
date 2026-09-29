"""Role access control: the nine roles reach exactly the operations PRD
section 4 grants them, and nothing else."""

import pytest

from test_helpers import (
    ApiErrorId,
    BackgroundOutcome,
    CLOCK_EPOCH,
    CoreLoadPatternStatus,
    Craft,
    HoldPointType,
    NON_EXISTENT_UUID,
    OutageStatus,
    ReservationPurpose,
    ReservationStatus,
    RwpStatus,
    SafetyFunctionCode,
    StartupTestStatus,
    StationUnit,
    TrainingStatus,
    WorkOrderStatus,
    WorkOrderType,
    WorkerStatus,
    api_client,
    make_access_authority_headers,
    make_contractor_coordinator_headers,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    make_station_admin_headers,
    read_dose_rows,
    read_outage,
    read_pattern,
    read_rwp,
    read_worker,
    read_work_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# PRD 2.1 makes both X-User-ID and X-User-Role mandatory, so a request sent
# with no headers at all is the unauthenticated case.
NO_HEADERS = {}


class TestScopeAndSchedulePlanningRoles:
    def test_the_four_planning_roles_each_perform_their_own_operations(self):
        """One uninterrupted planning walk in which StationAdmin seeds the three
        reference entities, ReactorEngineer owns the reload design and the pool
        booking, OutagePlanner writes and sequences the scope and OutageDirector
        performs every approval — and not one call is refused.

        PRD 3.1: "Before any outage can be planned, the station's physical
        configuration must be on record, and that registration is reserved to
        `StationAdmin`."

        Design: Corner/rbac/scope_and_schedule_roles_can_perform_their_exclusive_operations
        """
        set_clock(CLOCK_EPOCH)
        pool = validate_success(
            api_client.create_spent_fuel_pool(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "cells_total": 1200,
                    "cells_baseline_occupied": 900,
                    "full_core_offload_reserve_cells": 193,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        rad_area = validate_success(
            api_client.create_rad_area(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "area_code": "CTMT-EL471",
                    "dose_rate_mrem_per_hr": 25,
                    "occupancy_limit_workers": 10,
                    "survey_buffer_hours": 2,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        safety_function = validate_success(
            api_client.create_safety_function(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "function_code": SafetyFunctionCode.DECAY_HEAT_REMOVAL,
                    "trains_total": 2,
                    "min_trains_required": 1,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "designation": "1R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_station_admin_headers(),
            ),
            201,
        )

        pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 88,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": outage["version"],
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        approved_pattern = validate_success(
            api_client.approve_core_load_pattern(
                pattern["id"], make_outage_director_headers("od-1")
            )
        )
        assert approved_pattern["status"] == CoreLoadPatternStatus.APPROVED, (
            "pattern approval is open to OutageDirector as well as ReactorEngineer"
        )

        work_order = validate_success(
            api_client.create_work_order(
                outage["id"],
                {
                    "wo_type": WorkOrderType.MAINTENANCE,
                    "title": "Residual heat removal pump overhaul",
                    "estimated_hours": 40,
                    "estimated_cost_usd": 120000,
                    "estimated_dose_mrem": 0,
                    "safety_function_id": safety_function["id"],
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        validate_success(
            api_client.plan_work_order(work_order["id"], make_outage_planner_headers())
        )
        approved_order = validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers("od-1")
            )
        )
        assert approved_order["status"] == WorkOrderStatus.APPROVED

        activity = validate_success(
            api_client.create_schedule_activity(
                outage["id"],
                {
                    "label": "RHR pump outage window",
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 40,
                    "work_order_id": work_order["id"],
                    "oos_safety_function_id": safety_function["id"],
                    "oos_train_label": "A",
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        assert activity["oos_train_label"] == "A"

        reservation = validate_success(
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": outage["id"],
                    "spent_fuel_pool_id": pool["id"],
                    "cells_requested": 100,
                    "purpose": ReservationPurpose.DISCHARGE,
                    "expected_spent_fuel_pool_version": pool["version"],
                },
                make_reactor_engineer_headers(),
            ),
            201,
        )
        assert reservation["status"] == ReservationStatus.RESERVED

        locked = validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers("od-1"))
        )
        assert locked["status"] == OutageStatus.SCOPE_LOCKED

        assert validate_success(
            api_client.get_rad_area(rad_area["id"], make_outage_planner_headers())
        )["area_code"] == "CTMT-EL471"
        assert validate_success(
            api_client.get_safety_function(
                safety_function["id"], make_outage_planner_headers()
            )
        )["function_code"] == SafetyFunctionCode.DECAY_HEAT_REMOVAL


class TestWorkforceRadAndRegulatoryRoles:
    def test_the_five_execution_roles_each_perform_their_own_operations(self):
        """The workforce, radiological and regulatory roles walk their own
        pipelines end to end — request, screen, badge; draft, approve, close;
        then satisfy the test that returns the unit to service — and every call is
        accepted.

        PRD 3.9: "Satisfying a test is `RegulatoryAffairs`'s exclusive act."

        Design: Corner/rbac/workforce_rad_and_regulatory_roles_can_perform_their_exclusive_operations
        """
        set_clock(CLOCK_EPOCH)
        rad_area = validate_success(
            api_client.create_rad_area(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "area_code": "CTMT-EL471",
                    "dose_rate_mrem_per_hr": 25,
                    "occupancy_limit_workers": 10,
                    "survey_buffer_hours": 2,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "designation": "1R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_station_admin_headers(),
            ),
            201,
        )
        pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 88,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": outage["version"],
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        validate_success(
            api_client.approve_core_load_pattern(
                pattern["id"], make_reactor_engineer_headers("re-beta")
            )
        )
        work_order = validate_success(
            api_client.create_work_order(
                outage["id"],
                {
                    "wo_type": WorkOrderType.INSPECTION,
                    "title": "Containment survey",
                    "estimated_hours": 60,
                    "estimated_cost_usd": 100000,
                    "estimated_dose_mrem": 100,
                    "requires_rad_work": True,
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        validate_success(
            api_client.plan_work_order(work_order["id"], make_outage_planner_headers())
        )
        validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers()
            )
        )

        worker = validate_success(
            api_client.create_supplemental_worker(
                outage["id"],
                {
                    "full_name": "R. Kowalski",
                    "craft": Craft.RAD_TECH,
                    "sponsoring_contractor": "Northline Mechanical",
                },
                make_contractor_coordinator_headers(),
            ),
            201,
        )
        validate_success(
            api_client.record_background_result(
                worker["id"], BackgroundOutcome.CLEAR, make_access_authority_headers()
            )
        )
        joined = validate_success(
            api_client.record_training_completion(
                worker["id"], 4, make_contractor_coordinator_headers()
            )
        )
        assert joined["status"] == WorkerStatus.BADGE_READY, (
            "training completion is shared with ContractorCoordinator and the join fired"
        )
        badged = validate_success(
            api_client.badge_worker(worker["id"], "B-1000", make_access_authority_headers())
        )
        assert badged["status"] == WorkerStatus.BADGED
        assert read_outage(outage["id"])["badged_worker_count"] == 1

        permit = validate_success(
            api_client.draft_rwp(
                work_order["id"],
                {
                    "rad_area_id": rad_area["id"],
                    "worker_count": 2,
                    "shielding_factor": 0.5,
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 6,
                },
                make_rad_protection_planner_headers(),
            ),
            201,
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        approved_permit = validate_success(
            api_client.approve_rwp(permit["id"], make_rad_protection_manager_headers())
        )
        assert approved_permit["status"] == RwpStatus.APPROVED
        assert approved_permit["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)

        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )
        closed = validate_success(
            api_client.close_rwp(permit["id"], 180, make_rad_protection_planner_headers())
        )
        assert closed["status"] == RwpStatus.CLOSED
        assert len(read_dose_rows(permit["id"])) == 1, (
            "an exact-match closeout appends no ledger row"
        )

        startup_test = validate_success(
            api_client.create_startup_test(
                outage["id"],
                {
                    "test_code": "RCS-HEATUP",
                    "sequence_index": 1,
                    "hold_point_type": HoldPointType.STATION,
                    "predicted_reactivity_pcm": 500,
                },
                make_regulatory_affairs_headers("ra-1"),
            ),
            201,
        )
        validate_success(
            api_client.defer_work_order(
                work_order["id"], "Removed from outage scope", make_outage_director_headers()
            )
        )
        validate_success(
            api_client.authorize_startup(outage["id"], make_outage_director_headers())
        )
        satisfied = validate_success(
            api_client.satisfy_startup_test(
                startup_test["id"], 500, make_regulatory_affairs_headers("ra-2")
            )
        )
        assert satisfied["status"] == StartupTestStatus.SATISFIED
        assert read_outage(outage["id"])["status"] == OutageStatus.ONLINE


class TestNoRoleReachesAnotherRolesOperation:
    def _planning_outage_with_one_row_of_every_kind(self):
        set_clock(CLOCK_EPOCH)
        pool = validate_success(
            api_client.create_spent_fuel_pool(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "cells_total": 1200,
                    "cells_baseline_occupied": 900,
                    "full_core_offload_reserve_cells": 193,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        rad_area = validate_success(
            api_client.create_rad_area(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "area_code": "CTMT-EL471",
                    "dose_rate_mrem_per_hr": 25,
                    "occupancy_limit_workers": 10,
                    "survey_buffer_hours": 2,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "designation": "1R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_station_admin_headers(),
            ),
            201,
        )
        pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 88,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": outage["version"],
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        work_order = validate_success(
            api_client.create_work_order(
                outage["id"],
                {
                    "wo_type": WorkOrderType.INSPECTION,
                    "title": "Containment survey",
                    "estimated_hours": 60,
                    "estimated_cost_usd": 100000,
                    "estimated_dose_mrem": 100,
                    "requires_rad_work": True,
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        validate_success(
            api_client.plan_work_order(work_order["id"], make_outage_planner_headers())
        )
        permit = validate_success(
            api_client.draft_rwp(
                work_order["id"],
                {
                    "rad_area_id": rad_area["id"],
                    "worker_count": 2,
                    "shielding_factor": 0.5,
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 6,
                },
                make_rad_protection_planner_headers(),
            ),
            201,
        )
        worker = validate_success(
            api_client.create_supplemental_worker(
                outage["id"],
                {
                    "full_name": "R. Kowalski",
                    "craft": Craft.PIPEFITTER,
                    "sponsoring_contractor": "Northline Mechanical",
                },
                make_contractor_coordinator_headers(),
            ),
            201,
        )
        validate_success(
            api_client.record_background_result(
                worker["id"], BackgroundOutcome.CLEAR, make_access_authority_headers()
            )
        )
        validate_success(
            api_client.record_training_completion(
                worker["id"], 4, make_access_authority_headers()
            )
        )
        return {
            "pool": pool,
            "rad_area": rad_area,
            "outage": read_outage(outage["id"]),
            "pattern": pattern,
            "work_order": work_order,
            "permit": permit,
            "worker": read_worker(worker["id"]),
        }

    def test_nine_crossed_attempts_are_all_refused_on_the_role_header_alone(self):
        """Every identifier is real and every body is well formed, so nothing but
        the role header can decide these nine rejections — and none of them leaves
        a trace on the rows they addressed.

        PRD 2.1: "If both headers are well-formed but the named role is not among
        the roles authorized for the called endpoint (see the authorization column
        of §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
        """
        rows = self._planning_outage_with_one_row_of_every_kind()
        outage = rows["outage"]
        work_order_id = rows["work_order"]["id"]
        permit_id = rows["permit"]["id"]
        worker_id = rows["worker"]["id"]
        assert rows["worker"]["status"] == WorkerStatus.BADGE_READY

        crossed = [
            api_client.approve_work_order_scope(
                work_order_id, make_outage_planner_headers()
            ),
            api_client.plan_work_order(work_order_id, make_regulatory_affairs_headers()),
            api_client.badge_worker(
                worker_id, "B-1000", make_contractor_coordinator_headers()
            ),
            api_client.approve_rwp(permit_id, make_rad_protection_planner_headers()),
            api_client.draft_rwp(
                work_order_id,
                {
                    "rad_area_id": rows["rad_area"]["id"],
                    "worker_count": 2,
                    "shielding_factor": 0.5,
                    "planned_start_offset_hours": 0,
                    "planned_duration_hours": 6,
                },
                make_rad_protection_manager_headers(),
            ),
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": outage["id"],
                    "spent_fuel_pool_id": rows["pool"]["id"],
                    "cells_requested": 10,
                    "purpose": ReservationPurpose.CONTINGENCY,
                    "expected_spent_fuel_pool_version": rows["pool"]["version"],
                },
                make_access_authority_headers(),
            ),
            api_client.lock_scope(outage["id"], make_station_admin_headers()),
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 60,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": outage["version"],
                },
                make_outage_director_headers(),
            ),
            api_client.create_spent_fuel_pool(
                {
                    "station_unit": StationUnit.UNIT_2,
                    "cells_total": 1200,
                    "cells_baseline_occupied": 900,
                    "full_core_offload_reserve_cells": 193,
                },
                make_reactor_engineer_headers(),
            ),
        ]
        for response in crossed:
            validate_error(response, ApiErrorId.UNAUTHORIZED.value, 403)

        assert read_work_order(work_order_id)["status"] == WorkOrderStatus.PLANNED
        assert read_rwp(permit_id)["status"] == RwpStatus.DRAFT
        assert read_worker(worker_id)["status"] == WorkerStatus.BADGE_READY
        after = read_outage(outage["id"])
        assert after["status"] == OutageStatus.PLANNING
        assert after["version"] == outage["version"], (
            "nine refused writes must leave the outage version alone"
        )
        reservations, meta = validate_paginated(
            api_client.list_pool_cell_reservations(make_reactor_engineer_headers())
        )
        assert reservations == []
        assert meta["total_count"] == 0
        assert read_pattern(rows["pattern"]["id"])["status"] == CoreLoadPatternStatus.DRAFT


class TestSharedOperationsAcceptEveryDeclaredRole:
    def test_four_endpoints_are_exercised_by_both_of_their_listed_roles(self):
        """Outage creation, work-order creation, training completion and pattern
        approval each name two roles, and each is driven by both — with the
        pattern approval still having to satisfy the two-person rule on
        X-User-ID.

        PRD 3.5: "The second branch is training, and it may be recorded by either
        `AccessAuthority` or `ContractorCoordinator` through a `modules_completed`
        figure."

        PRD 3.3: "Approval moves a pattern `DRAFT → APPROVED` and is open to
        `ReactorEngineer` and `OutageDirector` alike, subject to the two-person
        rule of §2.10."

        Design: Corner/rbac/shared_operations_accept_every_role_that_declares_them
        """
        set_clock(CLOCK_EPOCH)
        first_outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "designation": "1R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_station_admin_headers(),
            ),
            201,
        )
        second_outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_2,
                    "designation": "2R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_outage_director_headers(),
            ),
            201,
        )
        assert second_outage["station_unit"] == StationUnit.UNIT_2

        validate_success(
            api_client.create_work_order(
                first_outage["id"],
                {
                    "wo_type": WorkOrderType.MAINTENANCE,
                    "title": "Planner-created order",
                    "estimated_hours": 10,
                    "estimated_cost_usd": 1000,
                    "estimated_dose_mrem": 0,
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        validate_success(
            api_client.create_work_order(
                first_outage["id"],
                {
                    "wo_type": WorkOrderType.MAINTENANCE,
                    "title": "Director-created order",
                    "estimated_hours": 10,
                    "estimated_cost_usd": 1000,
                    "estimated_dose_mrem": 0,
                },
                make_outage_director_headers(),
            ),
            201,
        )
        orders, meta = validate_paginated(
            api_client.list_work_orders(
                make_outage_planner_headers(), outage_id=first_outage["id"]
            )
        )
        assert len(orders) == 2
        assert meta["total_count"] == 2

        worker = validate_success(
            api_client.create_supplemental_worker(
                first_outage["id"],
                {
                    "full_name": "R. Kowalski",
                    "craft": Craft.PIPEFITTER,
                    "sponsoring_contractor": "Northline Mechanical",
                },
                make_contractor_coordinator_headers(),
            ),
            201,
        )
        after_access_authority = validate_success(
            api_client.record_training_completion(
                worker["id"], 2, make_access_authority_headers()
            )
        )
        assert after_access_authority["training_status"] == TrainingStatus.PENDING, (
            "two modules is short of the outage's requirement of four"
        )
        assert after_access_authority["status"] == WorkerStatus.SCREENING
        # PRD 3.5's join needs both branches: background_status CLEAR and
        # training_status COMPLETE. Branch A is landed here so that the second
        # training submission is the branch that trips the join.
        validate_success(
            api_client.record_background_result(
                worker["id"], BackgroundOutcome.CLEAR, make_access_authority_headers()
            )
        )
        after_coordinator = validate_success(
            api_client.record_training_completion(
                worker["id"], 4, make_contractor_coordinator_headers()
            )
        )
        assert after_coordinator["training_status"] == TrainingStatus.COMPLETE
        assert after_coordinator["status"] == WorkerStatus.BADGE_READY, (
            "both shared-role submissions landed on the same fork branch"
        )

        pattern = validate_success(
            api_client.create_core_load_pattern(
                first_outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 88,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": read_outage(first_outage["id"])["version"],
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        approved = validate_success(
            api_client.approve_core_load_pattern(
                pattern["id"], make_outage_director_headers("od-1")
            )
        )
        assert approved["status"] == CoreLoadPatternStatus.APPROVED
        assert approved["approved_by_user_id"] == "od-1"


class TestMissingRoleHeaderIsUnauthenticated:
    def test_the_first_rung_answers_before_authorization_and_before_the_lookup(self):
        """A read, a write and a read of a non-existent identifier are all sent
        with no headers at all, and all three answer 401 — the unknown identifier
        never reaches the path-resolution rung.

        PRD 2.1: "If either header is absent, or if the value of `X-User-Role` is
        not one of the nine roles enumerated below, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD 2.8: "Checks are evaluated in the order below, and the first violated
        check decides the response; no later check is evaluated, and no earlier
        check is skipped because a later one also fails."

        Design: Corner/rbac/a_request_without_a_role_header_is_unauthenticated
        """
        set_clock(CLOCK_EPOCH)
        outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "designation": "1R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_station_admin_headers(),
            ),
            201,
        )

        validate_error(
            api_client.get_outage(outage["id"], NO_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.lock_scope(outage["id"], NO_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )
        validate_error(
            api_client.get_outage(NON_EXISTENT_UUID, NO_HEADERS),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        assert read_outage(outage["id"])["status"] == OutageStatus.PLANNING


class TestSegregationOfDutiesAtBothTwoPersonGates:
    def test_neither_self_approval_nor_self_release_is_permitted(self):
        """Both refusals are decided by X-User-ID alone: the role is correct and
        the body is complete, including the release reference the regulatory hold
        point demands. The same calls resubmitted under a second identity succeed,
        and the station hold point in the same sequence is satisfied by its own
        author.

        PRD 2.10: "Approving that pattern records the approver as
        `approved_by_user_id`, and the approving `X-User-ID` must differ from
        `created_by_user_id`; an attempt to approve one's own reload design is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        PRD 2.10: "For hold points classified `STATION` or `NONE` no two-person
        rule applies, and the author may satisfy the test."

        Design: Corner/rbac/segregation_of_duties_blocks_self_approval_and_self_release
        """
        set_clock(CLOCK_EPOCH)
        outage = validate_success(
            api_client.create_outage(
                {
                    "station_unit": StationUnit.UNIT_1,
                    "designation": "1R24",
                    "duration_target_hours": 720,
                    "dose_budget_total_mrem": 5000,
                    "cost_budget_usd": 40000000,
                    "scope_freeze_at": "2026-08-15T00:00:00.000Z",
                },
                make_station_admin_headers(),
            ),
            201,
        )
        pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 88,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": outage["version"],
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        assert pattern["created_by_user_id"] == "re-alpha"

        validate_error(
            api_client.approve_core_load_pattern(
                pattern["id"], make_reactor_engineer_headers("re-alpha")
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert read_pattern(pattern["id"])["status"] == CoreLoadPatternStatus.DRAFT

        approved = validate_success(
            api_client.approve_core_load_pattern(
                pattern["id"], make_reactor_engineer_headers("re-beta")
            )
        )
        assert approved["status"] == CoreLoadPatternStatus.APPROVED

        work_order = validate_success(
            api_client.create_work_order(
                outage["id"],
                {
                    "wo_type": WorkOrderType.MAINTENANCE,
                    "title": "Reactor coolant pump seal",
                    "estimated_hours": 20,
                    "estimated_cost_usd": 60000,
                    "estimated_dose_mrem": 0,
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        validate_success(
            api_client.plan_work_order(work_order["id"], make_outage_planner_headers())
        )
        validate_success(
            api_client.approve_work_order_scope(
                work_order["id"], make_outage_director_headers()
            )
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )

        regulatory = validate_success(
            api_client.create_startup_test(
                outage["id"],
                {
                    "test_code": "MODE-3-HOLD",
                    "sequence_index": 1,
                    "hold_point_type": HoldPointType.REGULATORY,
                    "predicted_reactivity_pcm": 500,
                },
                make_regulatory_affairs_headers("ra-1"),
            ),
            201,
        )
        station = validate_success(
            api_client.create_startup_test(
                outage["id"],
                {
                    "test_code": "TURBINE-ROLL",
                    "sequence_index": 2,
                    "hold_point_type": HoldPointType.STATION,
                    "predicted_reactivity_pcm": 500,
                },
                make_regulatory_affairs_headers("ra-1"),
            ),
            201,
        )
        validate_success(
            api_client.defer_work_order(
                work_order["id"], "Removed from outage scope", make_outage_director_headers()
            )
        )
        validate_success(
            api_client.authorize_startup(outage["id"], make_outage_director_headers())
        )

        validate_error(
            api_client.satisfy_startup_test(
                regulatory["id"],
                500,
                make_regulatory_affairs_headers("ra-1"),
                nrc_release_reference="NRC-REL-2026-0031",
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

        released = validate_success(
            api_client.satisfy_startup_test(
                regulatory["id"],
                500,
                make_regulatory_affairs_headers("ra-2"),
                nrc_release_reference="NRC-REL-2026-0031",
            )
        )
        assert released["status"] == StartupTestStatus.SATISFIED
        assert released["satisfied_by_user_id"] == "ra-2"

        self_satisfied = validate_success(
            api_client.satisfy_startup_test(
                station["id"], 500, make_regulatory_affairs_headers("ra-1")
            )
        )
        assert self_satisfied["status"] == StartupTestStatus.SATISFIED, (
            "the two-person rule binds only REGULATORY hold points"
        )
        assert read_outage(outage["id"])["status"] == OutageStatus.ONLINE
