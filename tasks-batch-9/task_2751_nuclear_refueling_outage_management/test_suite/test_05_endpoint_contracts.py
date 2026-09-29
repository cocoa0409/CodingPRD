"""Endpoint coverage: the reference-data CRUD surface, action endpoints and
their conditions, computed reads, declared list filters and body-side links."""

import pytest

from test_helpers import (
    ApiErrorId,
    AvailabilityVariant,
    CLOCK_EPOCH,
    ConstraintStatus,
    DoseDirection,
    DoseReason,
    NON_EXISTENT_UUID,
    ReservationPurpose,
    ReservationStatus,
    SchedulePosture,
    StationUnit,
    WorkOrderType,
    api_client,
    assert_pool_ledger_consistent,
    assert_rad_area,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_draft_rwp,
    given_outage,
    given_pool_cell_reservation,
    given_rad_area,
    given_schedule_activity,
    given_spent_fuel_pool,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    make_station_admin_headers,
    pool_version,
    read_activity,
    read_outage,
    read_pool,
    read_reservation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestRadAreaCrudSurface:
    def test_the_create_persists_every_field_and_the_read_returns_it_unchanged(self):
        """A radiological area is written once and read back identically, with
        survey_buffer_hours at its declared lower bound of zero and the version
        untouched by the read.

        PRD 3.1: "and `survey_buffer_hours`, the post-work survey and decay buffer
        appended to the trailing edge of every occupied window in that area, which
        must be at least zero."

        Design: Corner/endpoints/rad_area_create_and_read_are_the_whole_crud_surface
        """
        set_clock(CLOCK_EPOCH)

        created = validate_success(
            api_client.create_rad_area(
                {
                    "station_unit": StationUnit.UNIT_2,
                    "area_code": "RB-EL240",
                    "dose_rate_mrem_per_hr": 40,
                    "occupancy_limit_workers": 4,
                    "survey_buffer_hours": 0,
                },
                make_station_admin_headers(),
            ),
            201,
        )
        assert created["station_unit"] == StationUnit.UNIT_2
        assert created["area_code"] == "RB-EL240"
        assert created["dose_rate_mrem_per_hr"] == pytest.approx(40, abs=0.01)
        assert created["occupancy_limit_workers"] == 4
        assert created["survey_buffer_hours"] == pytest.approx(0, abs=0.01)
        assert created["version"] == 1
        assert_rad_area(created)

        read_back = validate_success(
            api_client.get_rad_area(created["id"], make_rad_protection_planner_headers())
        )
        assert read_back == created, "the read is a pure projection of the stored row"
        assert read_back["version"] == 1


class TestReservationConsumption:
    def _locked_outage_with_a_large_reservation(self, cells_requested=250):
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            station_unit=StationUnit.UNIT_1,
            cells_total=1200,
            cells_baseline_occupied=900,
            full_core_offload_reserve_cells=193,
        )
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Fuel handling machine service",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        reservation = given_pool_cell_reservation(
            outage["id"],
            pool["id"],
            cells_requested=cells_requested,
            purpose=ReservationPurpose.CONTINGENCY,
        )
        return pool, outage, reservation

    def test_consumption_is_a_transfer_that_leaves_both_headroom_figures_alone(self):
        """250 cells move out of cells_reserved and into cells_occupied, so
        cells_available stays at 50 and protected_cells_available stays at -143
        while the pool version still advances.

        PRD 3.3: "Consumption is a ledger transfer rather than a new booking: the
        pool's `cells_reserved` falls by `cells_requested` while its
        `cells_occupied` rises by the same number, both headroom figures are
        recomputed, and the pool's `version` increments by 1."

        Design: Corner/endpoints/consume_moves_reserved_cells_into_occupied
        """
        pool, outage, reservation = self._locked_outage_with_a_large_reservation()
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        before = read_pool(pool["id"])
        assert before["cells_occupied"] == 900
        assert before["cells_reserved"] == 250
        assert before["cells_available"] == 50
        assert before["protected_cells_available"] == -143

        consumed = validate_success(
            api_client.consume_pool_cell_reservation(
                reservation["id"], make_reactor_engineer_headers()
            )
        )
        assert consumed["status"] == ReservationStatus.CONSUMED
        assert consumed["availability_variant"] == AvailabilityVariant.NOMINAL

        after = read_pool(pool["id"])
        assert after["cells_occupied"] == 1150
        assert after["cells_reserved"] == 0
        assert after["cells_available"] == 50
        assert after["protected_cells_available"] == -143
        assert after["version"] == before["version"] + 1
        assert_pool_ledger_consistent(after)

    def test_consumption_waits_for_the_outage_to_leave_planning(self):
        """The same call on the same RESERVED row is refused while the owning
        outage is in PLANNING and succeeds unchanged once scope is locked.

        PRD 3.3: "Consuming a reservation moves it `RESERVED → CONSUMED` and
        requires the owning outage to be in `SCOPE_LOCKED` or `EXECUTION`, otherwise
        `ERR_OUTAGE_STATE_INVALID`; a reservation that is not in `RESERVED` yields
        `ERR_POOL_RESERVATION_STATE_INVALID`."

        Design: Corner/endpoints/consume_is_refused_while_the_outage_is_still_planning
        """
        pool, outage, reservation = self._locked_outage_with_a_large_reservation(
            cells_requested=100
        )

        validate_error(
            api_client.consume_pool_cell_reservation(
                reservation["id"], make_reactor_engineer_headers()
            ),
            ApiErrorId.OUTAGE_STATE_INVALID.value,
            409,
        )
        assert read_reservation(reservation["id"])["status"] == ReservationStatus.RESERVED
        assert read_pool(pool["id"])["cells_occupied"] == 900

        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        consumed = validate_success(
            api_client.consume_pool_cell_reservation(
                reservation["id"], make_reactor_engineer_headers()
            )
        )
        assert consumed["status"] == ReservationStatus.CONSUMED

        after = read_pool(pool["id"])
        assert after["cells_occupied"] == 1000
        assert after["cells_reserved"] == 0
        assert after["cells_available"] == 200
        assert after["protected_cells_available"] == 7


class TestPoolReadExposesTheWholeLedger:
    def test_the_read_shows_both_halves_of_the_formula_and_a_negative_headroom(self):
        """One consumed and one reserved booking on the same pool put 1000 in
        cells_occupied and 50 in cells_reserved, and the protected headroom is
        returned as -43 rather than clamped at zero.

        PRD 3.3: "`protected_cells_available` is `cells_available` less
        `full_core_offload_reserve_cells`, and it may be negative."

        Design: Corner/endpoints/pool_read_exposes_all_four_derived_cell_figures
        """
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            station_unit=StationUnit.UNIT_1,
            cells_total=1200,
            cells_baseline_occupied=900,
            full_core_offload_reserve_cells=193,
        )
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        given_approved_core_load_pattern(outage["id"])
        given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Fuel handling machine service",
            estimated_hours=10,
            estimated_cost_usd=1000,
            estimated_dose_mrem=0,
        )
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))

        discharge = given_pool_cell_reservation(
            outage["id"],
            pool["id"],
            cells_requested=100,
            purpose=ReservationPurpose.DISCHARGE,
        )
        validate_success(
            api_client.consume_pool_cell_reservation(
                discharge["id"], make_reactor_engineer_headers()
            )
        )
        contingency = given_pool_cell_reservation(
            outage["id"],
            pool["id"],
            cells_requested=50,
            purpose=ReservationPurpose.CONTINGENCY,
        )

        projected = validate_success(
            api_client.get_spent_fuel_pool(pool["id"], make_outage_director_headers())
        )
        assert projected["cells_occupied"] == 1000
        assert projected["cells_reserved"] == 50
        assert projected["cells_available"] == 150
        assert projected["protected_cells_available"] == -43
        assert_pool_ledger_consistent(projected)

        assert discharge["availability_variant"] == AvailabilityVariant.FULL_CORE_PROTECTED
        assert contingency["availability_variant"] == AvailabilityVariant.NOMINAL


class TestDoseTransactionListFilter:
    def test_the_direction_filter_narrows_total_count_while_pagination_does_not(self):
        """A permit approved at 180.00 and closed at 100.00 owns one COMMIT and one
        RELEASE row; each filtered page returns one row with total_count 1, while an
        unfiltered page of size one reports total_count 2 and has_more true.

        PRD 2.3: "where `total_count` is the number of rows matching the filters
        before pagination is applied and `has_more` is true exactly when rows
        matching the filters remain beyond the returned page."

        Design: Corner/endpoints/dose_transaction_list_filters_by_direction
        """
        set_clock(CLOCK_EPOCH)
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
            dose_budget_total_mrem=5000,
        )
        given_approved_core_load_pattern(outage["id"])
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
        validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
        validate_success(
            api_client.commence_execution(outage["id"], make_outage_director_headers())
        )
        validate_success(
            api_client.approve_rwp(permit["id"], make_rad_protection_manager_headers())
        )
        validate_success(
            api_client.close_rwp(permit["id"], 100, make_rad_protection_planner_headers())
        )

        releases, release_meta = validate_paginated(
            api_client.list_dose_transactions(
                permit["id"],
                make_rad_protection_manager_headers(),
                direction=DoseDirection.RELEASE,
            )
        )
        assert len(releases) == 1
        assert releases[0]["amount_mrem"] == pytest.approx(80.00, abs=0.01)
        assert releases[0]["reason"] == DoseReason.RWP_CLOSED_UNDERRUN
        assert release_meta["total_count"] == 1
        assert release_meta["has_more"] is False

        commits, commit_meta = validate_paginated(
            api_client.list_dose_transactions(
                permit["id"],
                make_rad_protection_manager_headers(),
                direction=DoseDirection.COMMIT,
            )
        )
        assert len(commits) == 1
        assert commits[0]["amount_mrem"] == pytest.approx(180.00, abs=0.01)
        assert commits[0]["reason"] == DoseReason.RWP_APPROVED
        assert commit_meta["total_count"] == 1

        page, page_meta = validate_paginated(
            api_client.list_dose_transactions(
                permit["id"], make_rad_protection_manager_headers(), limit=1, offset=0
            )
        )
        assert len(page) == 1
        assert page_meta["total_count"] == 2
        assert page_meta["has_more"] is True


class TestSetPredecessorRewalksThePath:
    def _outage_with_a_chain_and_a_lone_root(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
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
        third = given_schedule_activity(
            outage["id"],
            label="B1 main generator rotor work",
            planned_start_offset_hours=0,
            planned_duration_hours=300,
        )
        return outage, first, second, third

    def test_attaching_the_lone_root_blocks_it_and_lengthens_the_projection(self):
        """Re-pointing B1 behind the incomplete A2 closes its constraint gate and
        extends its path to 550.00, which becomes the outage projection and makes
        the whole ancestry critical.

        PRD 3.4: "The activity's `constraint_status` is then re-evaluated on the same
        predicate as at creation — `CLEAR` when the new predecessor is null or already
        `COMPLETE`, `BLOCKED` otherwise — every activity's `path_length_hours`,
        `risk_adjusted_path_length_hours` and `is_critical_path` are reprojected
        across the outage, the outage's `projected_duration_hours`,
        `risk_adjusted_duration_hours`, `critical_path_activity_id` and
        `schedule_posture` are recomputed, and the outage's `version` increments by 1."

        Design: Corner/endpoints/set_predecessor_repoints_the_chain_and_rewalks_the_path
        """
        outage, first, second, third = self._outage_with_a_chain_and_a_lone_root()

        attached = validate_success(
            api_client.set_activity_predecessor(
                third["id"], second["id"], make_outage_planner_headers()
            )
        )
        assert attached["constraint_status"] == ConstraintStatus.BLOCKED
        assert attached["path_length_hours"] == pytest.approx(550.00, abs=0.01)
        assert read_activity(third["id"])[
            "risk_adjusted_path_length_hours"
        ] == pytest.approx(605.00, abs=0.01)

        after = read_outage(outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(550.00, abs=0.01)
        assert after["risk_adjusted_duration_hours"] == pytest.approx(605.00, abs=0.01)
        assert after["critical_path_activity_id"] == third["id"]
        assert after["schedule_posture"] == SchedulePosture.ON_TRACK
        for activity_id in (first["id"], second["id"], third["id"]):
            assert read_activity(activity_id)["is_critical_path"] is True

    def test_passing_null_detaches_the_activity_and_restores_the_projection(self):
        """Supplying a null predecessor makes B1 a chain root again, returning it to
        CLEAR at a 300.00 path length and dropping the two former ancestors off the
        critical path.

        PRD 3.4: "Re-sequencing an activity sets its `predecessor_activity_id` from
        the payload, and supplying null detaches the activity and makes it a chain
        root."

        Design: Corner/endpoints/set_predecessor_repoints_the_chain_and_rewalks_the_path
        """
        outage, first, second, third = self._outage_with_a_chain_and_a_lone_root()
        validate_success(
            api_client.set_activity_predecessor(
                third["id"], second["id"], make_outage_planner_headers()
            )
        )

        detached = validate_success(
            api_client.set_activity_predecessor(
                third["id"], None, make_outage_planner_headers()
            )
        )
        assert detached["constraint_status"] == ConstraintStatus.CLEAR
        assert detached["path_length_hours"] == pytest.approx(300.00, abs=0.01)
        assert detached["predecessor_activity_id"] is None

        after = read_outage(outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(300.00, abs=0.01)
        assert after["critical_path_activity_id"] == third["id"]
        assert after["schedule_posture"] == SchedulePosture.ON_TRACK
        assert read_activity(first["id"])["is_critical_path"] is False
        assert read_activity(second["id"])["is_critical_path"] is False


class TestReservationLinksTwoParentsFromTheBody:
    def test_an_unknown_pool_in_the_body_is_a_404_and_writes_nothing(self):
        """A reservation whose outage_id resolves but whose spent_fuel_pool_id does
        not is refused on the body foreign key, and the admitted retry is then
        reachable from both parents through the declared filters.

        PRD 2.8: "Body foreign keys: every identifier supplied in the body resolves
        to a stored row — otherwise the matching 404 code from §2.6."

        Design: Corner/endpoints/reservation_create_links_an_outage_and_a_pool_from_the_body
        """
        set_clock(CLOCK_EPOCH)
        pool = given_spent_fuel_pool(
            station_unit=StationUnit.UNIT_1,
            cells_total=1200,
            cells_baseline_occupied=900,
            full_core_offload_reserve_cells=193,
        )
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        version_before = pool_version(pool["id"])

        validate_error(
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": outage["id"],
                    "spent_fuel_pool_id": NON_EXISTENT_UUID,
                    "cells_requested": 10,
                    "purpose": ReservationPurpose.CONTINGENCY,
                    "expected_spent_fuel_pool_version": version_before,
                },
                make_reactor_engineer_headers(),
            ),
            ApiErrorId.SPENT_FUEL_POOL_NOT_FOUND.value,
            404,
        )

        reservation = validate_success(
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": outage["id"],
                    "spent_fuel_pool_id": pool["id"],
                    "cells_requested": 10,
                    "purpose": ReservationPurpose.CONTINGENCY,
                    "expected_spent_fuel_pool_version": version_before,
                },
                make_reactor_engineer_headers(),
            ),
            201,
        )
        assert reservation["outage_id"] == outage["id"]
        assert reservation["spent_fuel_pool_id"] == pool["id"]

        from_outage, outage_meta = validate_paginated(
            api_client.list_pool_cell_reservations(
                make_reactor_engineer_headers(), outage_id=outage["id"]
            )
        )
        assert [row["id"] for row in from_outage] == [reservation["id"]]
        assert outage_meta["total_count"] == 1

        from_pool, pool_meta = validate_paginated(
            api_client.list_pool_cell_reservations(
                make_reactor_engineer_headers(),
                spent_fuel_pool_id=pool["id"],
                status=ReservationStatus.RESERVED,
            )
        )
        assert [row["id"] for row in from_pool] == [reservation["id"]]
        assert pool_meta["total_count"] == 1

        assert read_pool(pool["id"])["cells_reserved"] == 10, (
            "the refused attempt reserved nothing"
        )
