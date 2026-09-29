"""Cross-cutting layers: optimistic concurrency on the two shared aggregates,
version semantics, all-or-nothing cascades and the ALARA review threshold."""

import pytest

from test_helpers import (
    ALARA_REVIEW_THRESHOLD_MREM,
    ApiErrorId,
    AvailabilityVariant,
    BackgroundOutcome,
    CLOCK_EPOCH,
    CoreLoadPatternStatus,
    Craft,
    ExecutionStatus,
    OutageStatus,
    REASON_SCOPE_LOCK_AUTO_DEFERRAL,
    REASON_WORK_ORDER_DEFERRED,
    ReservationPurpose,
    ReservationStatus,
    RwpStatus,
    StationUnit,
    WorkOrderStatus,
    WorkOrderType,
    WorkerStatus,
    api_client,
    given_approved_work_order,
    given_core_load_pattern,
    given_draft_rwp,
    given_outage,
    given_rad_area,
    given_schedule_activity,
    given_spent_fuel_pool,
    given_supplemental_worker,
    given_work_order,
    make_access_authority_headers,
    make_outage_director_headers,
    make_reactor_engineer_headers,
    read_activity,
    read_dose_rows,
    read_outage,
    read_pattern,
    read_pool,
    read_rwp,
    read_work_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStaleOutageVersionOnPatternCreate:
    def test_replaying_the_version_that_just_succeeded_is_the_stale_case(self):
        """The first submission bumps the outage itself, so re-sending the version
        the client observed before it is exactly a stale write: it is refused, it
        supersedes nothing, and the same body with the refreshed version is
        admitted.

        PRD 2.7: "If that value does not equal the outage's current stored
        `version`, the request is rejected with `ERR_OUTAGE_VERSION_STALE` (HTTP
        412) and no pattern is created."

        PRD 3.3: "Because only one draft design per outage is ever live, the
        submission also moves any existing pattern of the same outage that is still
        in `DRAFT` to `SUPERSEDED`, bumping that pattern's own `version` by 1 — a
        design under revision is superseded rather than deleted."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_outage_version_is_rejected_on_pattern_create
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        first_version = outage["version"]

        first_pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 88,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": first_version,
                },
                make_reactor_engineer_headers("re-alpha"),
            ),
            201,
        )
        second_version = read_outage(outage["id"])["version"]
        assert second_version == first_version + 1, "the first create bumped the parent"

        revision = {
            "cycle_length_mwd_mtu": 18000,
            "fresh_assembly_count": 84,
            "discharge_assembly_count": 80,
            "expected_outage_version": first_version,
        }
        validate_error(
            api_client.create_core_load_pattern(
                outage["id"], revision, make_reactor_engineer_headers("re-alpha")
            ),
            ApiErrorId.OUTAGE_VERSION_STALE.value,
            412,
        )
        rows, meta = validate_paginated(
            api_client.list_core_load_patterns(
                outage["id"], make_reactor_engineer_headers()
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert read_pattern(first_pattern["id"])["status"] == CoreLoadPatternStatus.DRAFT, (
            "the refused submission superseded nothing"
        )

        revision["expected_outage_version"] = second_version
        second_pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"], revision, make_reactor_engineer_headers("re-alpha")
            ),
            201,
        )
        assert second_pattern["reactivity_margin_pcm"] == pytest.approx(1538.00, abs=0.01)
        assert read_pattern(first_pattern["id"])["status"] == CoreLoadPatternStatus.SUPERSEDED
        assert read_outage(outage["id"])["version"] == second_version + 1


class TestStalePoolVersionOnReservationCreate:
    def test_the_cell_ledger_is_the_witness_that_the_stale_write_never_landed(self):
        """The pool's own counters answer the question: after the refusal
        cells_reserved is still the 100 cells the first booking took, and the
        retry against the refreshed version books the second 100.

        PRD 2.7: "If that value does not equal the pool's current stored
        `version`, the request is rejected with `ERR_POOL_VERSION_STALE` (HTTP 412)
        and no reservation is created."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_pool_version_is_rejected_on_reservation_create
        """
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
        first_version = pool["version"]

        booking = {
            "outage_id": outage["id"],
            "spent_fuel_pool_id": pool["id"],
            "cells_requested": 100,
            "purpose": ReservationPurpose.CONTINGENCY,
            "expected_spent_fuel_pool_version": first_version,
        }
        first_reservation = validate_success(
            api_client.create_pool_cell_reservation(
                dict(booking), make_reactor_engineer_headers()
            ),
            201,
        )
        after_first = read_pool(pool["id"])
        assert after_first["cells_reserved"] == 100
        second_version = after_first["version"]
        assert second_version == first_version + 1

        validate_error(
            api_client.create_pool_cell_reservation(
                dict(booking), make_reactor_engineer_headers()
            ),
            ApiErrorId.POOL_VERSION_STALE.value,
            412,
        )
        assert read_pool(pool["id"])["cells_reserved"] == 100, (
            "the stale write reserved nothing"
        )
        rows, meta = validate_paginated(
            api_client.list_pool_cell_reservations(
                make_reactor_engineer_headers(), spent_fuel_pool_id=pool["id"]
            )
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1

        booking["expected_spent_fuel_pool_version"] = second_version
        second_reservation = validate_success(
            api_client.create_pool_cell_reservation(
                booking, make_reactor_engineer_headers()
            ),
            201,
        )
        assert second_reservation["availability_variant"] == AvailabilityVariant.NOMINAL
        after_second = read_pool(pool["id"])
        assert after_second["cells_reserved"] == 200
        assert after_second["cells_available"] == 100
        assert after_second["protected_cells_available"] == -93
        assert first_reservation["status"] == ReservationStatus.RESERVED
        assert second_reservation["status"] == ReservationStatus.RESERVED


class TestVersionMovesOnWritesOnly:
    def test_reads_leave_every_counter_still_and_a_badge_bumps_its_outage(self):
        """Two reads change nothing; three worker writes each move the worker's
        own counter; and the badge issue moves the outage's counter through the
        headcount reprojection rather than through any direct write to the outage.

        PRD 2.4: "Most resources additionally carry `updated_at`, in the same ISO
        8601 UTC format with three fractional digits, and `version`, an integer
        that starts at 1 when the row is created and increases by exactly 1 on
        every mutation of that row."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
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
        worker = given_supplemental_worker(
            outage["id"],
            full_name="R. Kowalski",
            craft=Craft.PIPEFITTER,
            sponsoring_contractor="Northline Mechanical",
        )
        pool_v1 = pool["version"]
        outage_v1 = outage["version"]
        worker_v1 = worker["version"]

        assert read_outage(outage["id"])["version"] == outage_v1
        assert read_pool(pool["id"])["version"] == pool_v1, "reads never bump a version"

        screened = validate_success(
            api_client.record_background_result(
                worker["id"], BackgroundOutcome.CLEAR, make_access_authority_headers()
            )
        )
        trained = validate_success(
            api_client.record_training_completion(
                worker["id"], 4, make_access_authority_headers()
            )
        )
        badged = validate_success(
            api_client.badge_worker(worker["id"], "B-1000", make_access_authority_headers())
        )
        assert worker_v1 < screened["version"] < trained["version"] < badged["version"]
        assert badged["status"] == WorkerStatus.BADGED

        after_badge = read_outage(outage["id"])
        assert after_badge["badged_worker_count"] == 1
        assert after_badge["version"] == outage_v1 + 1, (
            "the badge issue reaches the outage through its headcount reprojection"
        )

        reservation = validate_success(
            api_client.create_pool_cell_reservation(
                {
                    "outage_id": outage["id"],
                    "spent_fuel_pool_id": pool["id"],
                    "cells_requested": 100,
                    "purpose": ReservationPurpose.CONTINGENCY,
                    "expected_spent_fuel_pool_version": pool_v1,
                },
                make_reactor_engineer_headers(),
            ),
            201,
        )
        assert reservation["status"] == ReservationStatus.RESERVED
        assert read_pool(pool["id"])["version"] == pool_v1 + 1


class TestRefusedScopeLockWritesNoneOfItsCascade:
    def _outage_that_fails_the_second_precondition(self):
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
            duration_target_hours=720,
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        approved_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Approved order",
            estimated_hours=20,
            estimated_cost_usd=60000,
            estimated_dose_mrem=0,
        )
        scoped_order = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Still scoped inspection",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        activity = given_schedule_activity(
            outage["id"],
            label="Scoped inspection window",
            planned_start_offset_hours=0,
            planned_duration_hours=60,
            work_order_id=scoped_order["id"],
        )
        permit = given_draft_rwp(
            scoped_order["id"],
            rad_area["id"],
            worker_count=2,
            shielding_factor=0.5,
            planned_start_offset_hours=0,
            planned_duration_hours=6,
        )
        pattern = given_core_load_pattern(
            outage["id"],
            cycle_length_mwd_mtu=18000,
            fresh_assembly_count=88,
            discharge_assembly_count=80,
        )
        assert pattern["status"] == CoreLoadPatternStatus.DRAFT
        return {
            "outage_id": outage["id"],
            "approved_order_id": approved_order["id"],
            "scoped_order_id": scoped_order["id"],
            "activity_id": activity["id"],
            "permit_id": permit["id"],
            "pattern_id": pattern["id"],
        }

    def test_the_refusal_leaves_all_three_cascade_targets_untouched(self):
        """The request clears the approved-work-order precondition and fails on the
        pattern, so none of the three deferral hops may run: the scoped order keeps
        its state, its activity is not cancelled and its permit is not voided.

        PRD 3.6: "And the outage must own at least one core loading pattern in
        `APPROVED`, otherwise `ERR_CORE_LOAD_PATTERN_NOT_APPROVED`."

        Design: Corner/cross_cutting_complexity_layers/a_refused_lock_scope_writes_none_of_its_cascade_hops
        """
        ctx = self._outage_that_fails_the_second_precondition()

        validate_error(
            api_client.lock_scope(ctx["outage_id"], make_outage_director_headers()),
            ApiErrorId.CORE_LOAD_PATTERN_NOT_APPROVED.value,
            409,
        )

        assert read_work_order(ctx["scoped_order_id"])["status"] == WorkOrderStatus.SCOPED
        assert (
            read_activity(ctx["activity_id"])["execution_status"]
            == ExecutionStatus.NOT_STARTED
        )
        assert read_rwp(ctx["permit_id"])["status"] == RwpStatus.DRAFT
        assert read_outage(ctx["outage_id"])["scope_locked_at"] is None

    def test_supplying_the_approved_pattern_runs_the_whole_cascade_in_one_request(self):
        """With the pattern approved the second attempt succeeds and every hop
        lands at once — deferral, activity cancellation and permit void — while the
        cost rollup keeps only the surviving approved order.

        PRD 3.6: "On success `scope_locked_at` is stamped with the current
        logical-clock instant, and the auto-deferral cascade runs: every work order
        of the outage still sitting in `SCOPED` moves `SCOPED → DEFERRED` with its
        `deferral_reason` set to the literal string `SCOPE_LOCK_AUTO_DEFERRAL`,
        processed in ascending work-order `created_at` order."

        Design: Corner/cross_cutting_complexity_layers/a_refused_lock_scope_writes_none_of_its_cascade_hops
        """
        ctx = self._outage_that_fails_the_second_precondition()
        validate_error(
            api_client.lock_scope(ctx["outage_id"], make_outage_director_headers()),
            ApiErrorId.CORE_LOAD_PATTERN_NOT_APPROVED.value,
            409,
        )
        validate_success(
            api_client.approve_core_load_pattern(
                ctx["pattern_id"], make_reactor_engineer_headers("re-beta")
            )
        )

        locked = validate_success(
            api_client.lock_scope(ctx["outage_id"], make_outage_director_headers())
        )
        assert locked["status"] == OutageStatus.SCOPE_LOCKED

        deferred = read_work_order(ctx["scoped_order_id"])
        assert deferred["status"] == WorkOrderStatus.DEFERRED
        assert deferred["deferral_reason"] == REASON_SCOPE_LOCK_AUTO_DEFERRAL
        assert (
            read_activity(ctx["activity_id"])["execution_status"]
            == ExecutionStatus.CANCELLED
        )
        voided = read_rwp(ctx["permit_id"])
        assert voided["status"] == RwpStatus.VOIDED
        assert voided["void_reason"] == REASON_WORK_ORDER_DEFERRED
        assert read_dose_rows(ctx["permit_id"]) == [], (
            "a permit that never reached APPROVED holds no committed dose to release"
        )
        assert locked["approved_scope_cost_usd"] == pytest.approx(60000.00, abs=0.01)


class TestAlaraReviewFlagAtExactlyThreeHundredMrem:
    def test_one_hundredth_of_an_hour_separates_the_flagged_permit_from_the_clear_one(self):
        """Both permits are drafted in identical 25 mrem/hr fields with four
        workers and no shielding; three hours give exactly the threshold and set
        the flag, while 2.99 hours fall one mrem short and leave it clear.

        PRD 3.7: "The flag `alara_review_required` is true when
        `collective_dose_mrem` is greater than or equal to 300 mrem — note that the
        ALARA gate reads the pre-contingency collective figure, never the
        post-contingency committed figure."

        Design: Corner/cross_cutting_complexity_layers/alara_review_flag_trips_at_exactly_three_hundred_collective_mrem
        """
        set_clock(CLOCK_EPOCH)
        first_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="CTMT-EL471",
            dose_rate_mrem_per_hr=25,
            occupancy_limit_workers=10,
            survey_buffer_hours=2,
        )
        second_area = given_rad_area(
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
            dose_budget_total_mrem=5000,
            cost_budget_usd=40000000,
        )
        first_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Survey X",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )
        second_order = given_approved_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Survey Y",
            estimated_hours=60,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            requires_rad_work=True,
        )

        at_threshold = given_draft_rwp(
            first_order["id"],
            first_area["id"],
            worker_count=4,
            shielding_factor=0,
            planned_start_offset_hours=0,
            planned_duration_hours=3,
        )
        below_threshold = given_draft_rwp(
            second_order["id"],
            second_area["id"],
            worker_count=4,
            shielding_factor=0,
            planned_start_offset_hours=0,
            planned_duration_hours=2.99,
        )

        assert at_threshold["per_worker_dose_mrem"] == pytest.approx(75.00, abs=0.01)
        assert at_threshold["collective_dose_mrem"] == pytest.approx(300.00, abs=0.01)
        assert at_threshold["alara_review_required"] is True, (
            "the comparison is inclusive at {} mrem".format(ALARA_REVIEW_THRESHOLD_MREM)
        )
        assert at_threshold["contingency_dose_mrem"] == pytest.approx(60.00, abs=0.01)
        assert at_threshold["committed_dose_mrem"] == pytest.approx(360.00, abs=0.01)

        assert below_threshold["per_worker_dose_mrem"] == pytest.approx(74.75, abs=0.01)
        assert below_threshold["collective_dose_mrem"] == pytest.approx(299.00, abs=0.01)
        assert below_threshold["alara_review_required"] is False
        assert below_threshold["contingency_dose_mrem"] == pytest.approx(59.80, abs=0.01)
        assert below_threshold["committed_dose_mrem"] == pytest.approx(358.80, abs=0.01)

        assert at_threshold["status"] == RwpStatus.DRAFT
        assert below_threshold["status"] == RwpStatus.DRAFT
        assert read_outage(outage["id"])["dose_committed_mrem"] == pytest.approx(
            0.00, abs=0.01
        ), "the flag is a creation-time property and commits no dose"
