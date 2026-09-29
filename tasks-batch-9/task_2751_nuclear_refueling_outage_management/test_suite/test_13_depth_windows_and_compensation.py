"""Depth coverage: opposing interval conventions and exact compensations."""

import pytest

from test_helpers import (
    AlaraPosture,
    ApiErrorId,
    CLOCK_EPOCH,
    DoseDirection,
    DoseReason,
    ReservationPurpose,
    ReservationStatus,
    RwpStatus,
    SafetyFunctionCode,
    StationUnit,
    WorkOrderType,
    api_client,
    assert_dose_budget_consistent,
    assert_ledger_rows_ascending,
    assert_pool_ledger_consistent,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_draft_rwp,
    given_outage,
    given_pool_cell_reservation,
    given_rad_area,
    given_safety_function,
    given_schedule_activity,
    given_spent_fuel_pool,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_reactor_engineer_headers,
    read_dose_rows,
    read_outage,
    read_pool,
    read_reservation,
    read_rwp,
    set_clock,
    validate_error,
    validate_success,
)


class TestRadAreaHalfOpenBufferedWindow:
    def _locked_outage_with_three_permits(self):
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="RA-9",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="2R26",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Reactor head area inspections",
            estimated_hours=60,
            estimated_cost_usd=150000,
            estimated_dose_mrem=100,
            regulatory_commitment=True,
            requires_rad_work=True,
        )
        permits = [
            given_draft_rwp(
                work_order["id"],
                rad_area["id"],
                worker_count=2,
                shielding_factor=0.5,
                planned_start_offset_hours=offset,
                planned_duration_hours=duration,
            )
            for offset, duration in ((10, 6), (17.5, 6), (18, 4))
        ]
        validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        first = validate_success(
            api_client.approve_rwp(permits[0]["id"], make_rad_protection_manager_headers())
        )
        assert first["status"] == RwpStatus.APPROVED
        assert first["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)
        return outage, permits

    def test_a_permit_starting_inside_the_buffered_window_is_refused(self):
        """The approved permit occupies [10, 10 + 6 + 2) = [10, 18), so a permit
        starting at 17.5 intersects the trailing survey buffer and is refused
        without touching the dose ledger.

        PRD 3.7: "A conflict exists when that window intersects the window of any
        *other* permit sharing the same `rad_area_id` whose status is `APPROVED`."

        Design: Difficulty/resource_temporal_overlap/rad_area_half_open_buffered_window_admits_exact_adjacency
        """
        _outage, permits = self._locked_outage_with_three_permits()

        response = api_client.approve_rwp(
            permits[1]["id"], make_rad_protection_manager_headers()
        )
        validate_error(response, ApiErrorId.RAD_AREA_WINDOW_CONFLICT.value)

        assert read_rwp(permits[1]["id"])["status"] == RwpStatus.DRAFT
        assert read_dose_rows(permits[1]["id"]) == []

    def test_a_permit_starting_exactly_at_the_buffered_end_is_admitted(self):
        """Because the occupied window excludes its own end offset, a permit
        beginning at precisely 18 is adjacent rather than overlapping and commits
        its own 120.00 mrem on top of the first permit's 180.00.

        PRD 3.7: "Exact adjacency is explicitly admitted: a permit beginning
        precisely at another permit's buffered end offset does not conflict."

        Design: Difficulty/resource_temporal_overlap/rad_area_half_open_buffered_window_admits_exact_adjacency
        """
        outage, permits = self._locked_outage_with_three_permits()
        validate_error(
            api_client.approve_rwp(permits[1]["id"], make_rad_protection_manager_headers()),
            ApiErrorId.RAD_AREA_WINDOW_CONFLICT.value,
        )

        adjacent = validate_success(
            api_client.approve_rwp(permits[2]["id"], make_rad_protection_manager_headers())
        )
        assert adjacent["status"] == RwpStatus.APPROVED
        assert adjacent["per_worker_dose_mrem"] == pytest.approx(50.00, abs=0.01)
        assert adjacent["collective_dose_mrem"] == pytest.approx(100.00, abs=0.01)
        assert adjacent["contingency_dose_mrem"] == pytest.approx(20.00, abs=0.01)
        assert adjacent["committed_dose_mrem"] == pytest.approx(120.00, abs=0.01)

        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(300.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(4700.00, abs=0.01)
        assert after["alara_posture"] == AlaraPosture.NORMAL
        assert_dose_budget_consistent(after)


class TestSafetyFunctionClosedWindowAggregatesTrains:
    def _outage_with_one_train_out_of_service(self):
        set_clock(CLOCK_EPOCH)
        safety_function = given_safety_function(
            station_unit=StationUnit.UNIT_1,
            function_code=SafetyFunctionCode.DECAY_HEAT_REMOVAL,
            trains_total=3,
            min_trains_required=2,
        )
        assert safety_function["max_concurrent_oos_trains"] == 1
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="2R26")
        first = given_schedule_activity(
            outage["id"],
            label="RHR train A out of service",
            planned_start_offset_hours=100,
            planned_duration_hours=50,
            oos_safety_function_id=safety_function["id"],
            oos_train_label="A",
        )
        return safety_function, outage, first

    def test_a_second_train_touching_the_closed_window_endpoint_conflicts(self):
        """[100, 150] and [150, 170] share only the instant 150, but both
        endpoints are inclusive, so the distinct label set {A, B} has size 2
        against a capacity of 1 and the creation is refused.

        PRD 3.4: "The activity's out-of-service window is a **closed** interval
        running from `planned_start_offset_hours` to `planned_start_offset_hours`
        plus `planned_duration_hours`, with both endpoints inclusive —
        deliberately the opposite of the radiological window semantics of §3.7, so
        two out-of-service windows that merely touch at an endpoint *do* conflict."

        Design: Difficulty/resource_temporal_overlap/safety_function_closed_window_aggregates_distinct_trains
        """
        safety_function, outage, _first = self._outage_with_one_train_out_of_service()

        response = api_client.create_schedule_activity(
            outage["id"],
            {
                "label": "RHR train B touching at 150",
                "planned_start_offset_hours": 150,
                "planned_duration_hours": 20,
                "oos_safety_function_id": safety_function["id"],
                "oos_train_label": "B",
            },
            make_outage_planner_headers(),
        )
        validate_error(response, ApiErrorId.SAFETY_FUNCTION_CAPACITY_EXCEEDED.value)

        rows = validate_success(
            api_client.list_schedule_activities(
                make_outage_planner_headers(),
                oos_safety_function_id=safety_function["id"],
            )
        )
        assert len(rows) == 1, "the refused request must persist nothing"

    def test_capacity_counts_distinct_labels_so_reusing_train_a_is_admitted(self):
        """Moving the second train's window one hour clear is admitted, and a
        third activity that overlaps the first but re-uses label A is also
        admitted because the two rows consume one unit of capacity between them.

        PRD 3.4: "Because the aggregate is over *distinct* labels, two activities
        taking the same train out at overlapping times consume one unit of
        capacity rather than two."

        Design: Difficulty/resource_temporal_overlap/safety_function_closed_window_aggregates_distinct_trains
        """
        safety_function, outage, _first = self._outage_with_one_train_out_of_service()
        validate_error(
            api_client.create_schedule_activity(
                outage["id"],
                {
                    "label": "RHR train B touching at 150",
                    "planned_start_offset_hours": 150,
                    "planned_duration_hours": 20,
                    "oos_safety_function_id": safety_function["id"],
                    "oos_train_label": "B",
                },
                make_outage_planner_headers(),
            ),
            ApiErrorId.SAFETY_FUNCTION_CAPACITY_EXCEEDED.value,
        )

        disjoint = validate_success(
            api_client.create_schedule_activity(
                outage["id"],
                {
                    "label": "RHR train B starting at 151",
                    "planned_start_offset_hours": 151,
                    "planned_duration_hours": 20,
                    "oos_safety_function_id": safety_function["id"],
                    "oos_train_label": "B",
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        assert disjoint["oos_train_label"] == "B"

        same_train = validate_success(
            api_client.create_schedule_activity(
                outage["id"],
                {
                    "label": "RHR train A second window",
                    "planned_start_offset_hours": 120,
                    "planned_duration_hours": 10,
                    "oos_safety_function_id": safety_function["id"],
                    "oos_train_label": "A",
                },
                make_outage_planner_headers(),
            ),
            201,
        )
        assert same_train["oos_train_label"] == "A"

        rows = validate_success(
            api_client.list_schedule_activities(
                make_outage_planner_headers(),
                oos_safety_function_id=safety_function["id"],
            )
        )
        assert len(rows) == 3


class TestPermitVoidRestoresTheDoseLedger:
    def _restricted_outage_with_approved_and_held_permits(self):
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="RA-10",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="2R26",
            duration_target_hours=720,
            dose_budget_total_mrem=1000,
            cost_budget_usd=40000000,
        )
        given_approved_core_load_pattern(outage["id"])
        work_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Steam generator secondary side inspection",
            estimated_hours=100,
            estimated_cost_usd=250000,
            estimated_dose_mrem=400,
            regulatory_commitment=True,
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
        validate_success(
            api_client.lock_scope(outage["id"], make_outage_director_headers())
        )
        validate_success(
            api_client.approve_rwp(
                permit_a["id"],
                make_rad_protection_manager_headers(),
                alara_review_reference="ALARA-2R26-021",
            )
        )
        baseline = read_outage(outage["id"])
        assert baseline["dose_committed_mrem"] == pytest.approx(750.00, abs=0.01)
        assert baseline["dose_budget_remaining_mrem"] == pytest.approx(250.00, abs=0.01)
        assert baseline["alara_posture"] == AlaraPosture.RESTRICTED
        assert_dose_budget_consistent(baseline)
        assert read_rwp(permit_b["id"])["status"] == RwpStatus.HELD_FOR_ALARA
        return outage, permit_a, permit_b

    def test_voiding_appends_an_offsetting_release_rather_than_erasing_the_commit(self):
        """The permit's ledger holds two rows after the void — the original
        750.00 COMMIT and a 750.00 RELEASE — and the permit itself keeps its
        computed 750.00 committed dose.

        PRD 3.7: "hop one appends a `RELEASE` row whose `amount_mrem` is the
        permit's `committed_dose_mrem` and whose `reason` is `RWP_VOIDED`, exactly
        reversing the `COMMIT` written at approval."

        Design: Difficulty/compensating_invariant/permit_void_restores_outage_dose_ledger_exactly
        """
        _outage, permit_a, _permit_b = self._restricted_outage_with_approved_and_held_permits()

        voided = validate_success(
            api_client.void_rwp(
                permit_a["id"],
                "Scope moved to the next refueling outage",
                make_rad_protection_manager_headers(),
            )
        )
        assert voided["status"] == RwpStatus.VOIDED
        assert voided["void_reason"] == "Scope moved to the next refueling outage"
        assert voided["committed_dose_mrem"] == pytest.approx(750.00, abs=0.01), (
            "the permit keeps its computed dose; the ledger is what compensates"
        )

        rows = read_dose_rows(permit_a["id"])
        assert len(rows) == 2
        assert_ledger_rows_ascending(rows)
        assert rows[0]["direction"] == DoseDirection.COMMIT
        assert rows[0]["amount_mrem"] == pytest.approx(750.00, abs=0.01)
        assert rows[0]["reason"] == DoseReason.RWP_APPROVED
        assert rows[1]["direction"] == DoseDirection.RELEASE
        assert rows[1]["amount_mrem"] == pytest.approx(750.00, abs=0.01)
        assert rows[1]["reason"] == DoseReason.RWP_VOIDED

    def test_the_reprojected_budget_returns_to_zero_and_frees_the_held_permit(self):
        """Replaying the two-row ledger returns the outage to 0.00 committed and
        1000.00 remaining, which flips the posture back to NORMAL and runs the
        hold cascade in reverse.

        PRD 3.7: "hop three recomputes `alara_posture`, and if it returns to
        `NORMAL` every `HELD_FOR_ALARA` permit of the outage returns to `DRAFT` in
        ascending `created_at` order."

        Design: Difficulty/compensating_invariant/permit_void_restores_outage_dose_ledger_exactly
        """
        outage, permit_a, permit_b = self._restricted_outage_with_approved_and_held_permits()

        validate_success(
            api_client.void_rwp(
                permit_a["id"],
                "Scope moved to the next refueling outage",
                make_rad_protection_manager_headers(),
            )
        )

        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(0.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(1000.00, abs=0.01)
        assert after["dose_budget_total_mrem"] == pytest.approx(
            after["dose_committed_mrem"] + after["dose_budget_remaining_mrem"], abs=0.01
        )
        assert after["alara_posture"] == AlaraPosture.NORMAL
        assert read_rwp(permit_b["id"])["status"] == RwpStatus.DRAFT


class TestPoolReservationReleaseRestoresTheCellLedger:
    def _pool_with_a_large_contingency_reservation(self):
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            station_unit=StationUnit.UNIT_1,
            cells_total=1200,
            cells_baseline_occupied=900,
            full_core_offload_reserve_cells=193,
        )
        assert pool["version"] == 1
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="2R26")
        reservation = given_pool_cell_reservation(
            outage["id"],
            pool["id"],
            cells_requested=250,
            purpose=ReservationPurpose.CONTINGENCY,
        )
        baseline = read_pool(pool["id"])
        assert baseline["cells_reserved"] == 250
        assert baseline["cells_available"] == 50
        assert baseline["protected_cells_available"] == -143
        assert baseline["version"] == 2
        return pool, reservation

    def test_release_returns_both_headroom_figures_to_their_prior_values(self):
        """Releasing 250 reserved cells drops cells_reserved to zero without ever
        converting them into occupied cells, so cells_available returns to 300 and
        protected_cells_available to 107.

        PRD 3.3: "Releasing a reservation instead moves it `RESERVED → RELEASED`,
        storing the supplied `release_reason`; the pool's `cells_reserved` falls by
        `cells_requested` and `cells_occupied` is left untouched, so both headroom
        figures return exactly to their pre-reservation values, and the pool's
        `version` increments by 1."

        Design: Difficulty/compensating_invariant/pool_reservation_release_restores_cell_ledger_exactly
        """
        pool, reservation = self._pool_with_a_large_contingency_reservation()

        released = validate_success(
            api_client.release_pool_cell_reservation(
                reservation["id"],
                "Contingency block no longer required",
                make_reactor_engineer_headers(),
            )
        )
        assert released["status"] == ReservationStatus.RELEASED
        assert released["release_reason"] == "Contingency block no longer required"

        after = read_pool(pool["id"])
        assert after["cells_reserved"] == 0
        assert after["cells_occupied"] == 900
        assert after["cells_available"] == 300
        assert after["protected_cells_available"] == 107
        assert after["cells_total"] == (
            after["cells_occupied"] + after["cells_reserved"] + after["cells_available"]
        )
        assert_pool_ledger_consistent(after)

    def test_the_compensation_is_a_forward_write_that_keeps_the_row_intact(self):
        """The pool's version climbs from 2 to 3 rather than reverting to 1, and
        the released reservation keeps its 250-cell size because it is excluded
        from the projection rather than resized.

        PRD 3.3: "Reservations in `RELEASED` are excluded from the projection
        entirely, which is precisely what makes reserve-then-release an exact
        compensation."

        Design: Difficulty/compensating_invariant/pool_reservation_release_restores_cell_ledger_exactly
        """
        pool, reservation = self._pool_with_a_large_contingency_reservation()

        validate_success(
            api_client.release_pool_cell_reservation(
                reservation["id"],
                "Contingency block no longer required",
                make_reactor_engineer_headers(),
            )
        )

        assert read_pool(pool["id"])["version"] == 3
        assert read_reservation(reservation["id"])["cells_requested"] == 250
