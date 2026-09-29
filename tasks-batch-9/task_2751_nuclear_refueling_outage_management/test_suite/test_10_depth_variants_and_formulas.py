"""Depth coverage: dual-variant admission, composite indices and pinned
rounding orders."""

import pytest

from test_helpers import (
    ALARA_REVIEW_THRESHOLD_MREM,
    ApiErrorId,
    AvailabilityVariant,
    CLOCK_EPOCH,
    OutageStatus,
    ReservationPurpose,
    ReservationStatus,
    RwpStatus,
    StationUnit,
    WorkOrderType,
    api_client,
    assert_pool_ledger_consistent,
    assert_scope_rollup_consistent,
    expected_rwp_doses,
    given_approved_core_load_pattern,
    given_approved_rwp,
    given_approved_work_order,
    given_completed_activity,
    given_disposed_emergent_item,
    given_draft_rwp,
    given_emergent_item,
    given_outage,
    given_planned_work_order,
    given_rad_area,
    given_schedule_activity,
    given_spent_fuel_pool,
    given_started_activity,
    given_startup_test,
    given_work_order,
    make_outage_director_headers,
    make_outage_planner_headers,
    make_reactor_engineer_headers,
    make_regulatory_affairs_headers,
    pool_version,
    read_outage,
    read_pool,
    set_clock,
    validate_error,
    validate_success,
)


def _pool_and_outage_with_approved_pattern():
    set_clock(CLOCK_EPOCH)
    pool = given_spent_fuel_pool(
        station_unit=StationUnit.UNIT_1,
        cells_total=1200,
        cells_baseline_occupied=900,
        full_core_offload_reserve_cells=193,
    )
    outage = given_outage(
        station_unit=StationUnit.UNIT_1,
        designation="2R26",
        duration_target_hours=720,
        dose_budget_total_mrem=5000,
        cost_budget_usd=40000000,
        scope_freeze_at="2026-08-15T00:00:00.000Z",
        required_training_modules=4,
        required_badged_workers=0,
    )
    given_approved_core_load_pattern(
        outage["id"], cycle_length_mwd_mtu=18000, fresh_assembly_count=88,
        discharge_assembly_count=80,
    )
    return pool, outage


class TestPoolHeadroomVariants:
    def test_discharge_reservation_is_refused_against_protected_headroom(self):
        """A 200-cell DISCHARGE booking exceeds protected_cells_available (107)
        even though cells_available (300) would have covered it, so the
        FULL_CORE_PROTECTED variant refuses it and the pool ledger is untouched.

        PRD 3.3: "Admission then compares `cells_requested` against the headroom
        the variant selects: `protected_cells_available` for
        `FULL_CORE_PROTECTED`, and `cells_available` for `NOMINAL`."

        Design: Difficulty/dual_variant_calc/pool_headroom_nominal_admits_where_full_core_protected_rejects
        """
        pool, outage = _pool_and_outage_with_approved_pattern()
        before = read_pool(pool["id"])
        assert before["cells_available"] == 300
        assert before["protected_cells_available"] == 107

        response = api_client.create_pool_cell_reservation(
            {
                "outage_id": outage["id"],
                "spent_fuel_pool_id": pool["id"],
                "cells_requested": 200,
                "purpose": ReservationPurpose.DISCHARGE,
                "expected_spent_fuel_pool_version": before["version"],
            },
            make_reactor_engineer_headers(),
        )
        validate_error(response, ApiErrorId.POOL_CAPACITY_EXCEEDED.value)

        after = read_pool(pool["id"])
        assert after["cells_reserved"] == 0, "a refused booking must reserve nothing"
        assert after["version"] == before["version"], (
            "a refused booking must not bump the pool version"
        )

    def test_identical_contingency_reservation_is_admitted_against_nominal_headroom(self):
        """The same 200 cells booked as CONTINGENCY take the NOMINAL variant and
        are admitted against cells_available, driving protected_cells_available
        legitimately negative.

        PRD 3.3: "The practical difference between the two variants is exactly
        `full_core_offload_reserve_cells`: for identical pool state and an
        identical `cells_requested`, the `NOMINAL` variant admits requests the
        `FULL_CORE_PROTECTED` variant refuses, because a planned occupancy may
        never encroach on the block held open for an unplanned full-core offload
        while a contingency may."

        Design: Difficulty/dual_variant_calc/pool_headroom_nominal_admits_where_full_core_protected_rejects
        """
        pool, outage = _pool_and_outage_with_approved_pattern()
        version_before = pool_version(pool["id"])

        response = api_client.create_pool_cell_reservation(
            {
                "outage_id": outage["id"],
                "spent_fuel_pool_id": pool["id"],
                "cells_requested": 200,
                "purpose": ReservationPurpose.CONTINGENCY,
                "expected_spent_fuel_pool_version": version_before,
            },
            make_reactor_engineer_headers(),
        )
        reservation = validate_success(response, 201)
        assert reservation["availability_variant"] == AvailabilityVariant.NOMINAL
        assert reservation["status"] == ReservationStatus.RESERVED

        after = read_pool(pool["id"])
        assert after["cells_reserved"] == 200
        assert after["cells_occupied"] == 900, "reserving cells never occupies them"
        assert after["cells_available"] == 100
        assert after["protected_cells_available"] == -93, (
            "PRD 3.1 permits this headroom figure to be negative"
        )
        assert_pool_ledger_consistent(after)


def _drive_outage_to_online_with_approved_emergent_work():
    """Builds an outage that reaches ONLINE having absorbed 90 hours of approved
    emergent work and committed 750.00 mrem of dose."""
    set_clock(CLOCK_EPOCH)
    rad_area = given_rad_area(
        station_unit=StationUnit.UNIT_2,
        area_code="RA-1",
        dose_rate_mrem_per_hr=25,
        occupancy_limit_workers=12,
        survey_buffer_hours=2,
    )
    outage = given_outage(
        station_unit=StationUnit.UNIT_2,
        designation="2R28",
        duration_target_hours=720,
        dose_budget_total_mrem=1000,
        cost_budget_usd=40000000,
        scope_freeze_at="2026-08-15T00:00:00.000Z",
    )
    given_approved_core_load_pattern(outage["id"])
    work_order = given_approved_work_order(
        outage["id"],
        wo_type=WorkOrderType.MODIFICATION,
        title="Reactor coolant pump seal replacement",
        estimated_hours=200,
        estimated_cost_usd=1200000,
        estimated_dose_mrem=300,
        regulatory_commitment=True,
    )
    activity = given_schedule_activity(
        outage["id"],
        label="A1 seal replacement",
        planned_start_offset_hours=0,
        planned_duration_hours=200,
        work_order_id=work_order["id"],
    )
    validate_success(api_client.lock_scope(outage["id"], make_outage_director_headers()))
    validate_success(
        api_client.commence_execution(outage["id"], make_outage_director_headers())
    )
    given_approved_rwp(
        work_order["id"],
        rad_area["id"],
        alara_review_reference="ALARA-2R28-001",
        worker_count=5,
        shielding_factor=0,
        planned_start_offset_hours=0,
        planned_duration_hours=5,
    )
    given_started_activity(activity["id"])

    item = given_emergent_item(
        work_order["id"],
        description="Degraded pump casing bolting found once lagging was removed",
        estimated_hours=90,
        estimated_cost_usd=400000,
        estimated_dose_mrem=150,
    )
    disposed = given_disposed_emergent_item(item["id"])

    validate_success(
        api_client.complete_activity(activity["id"], make_outage_planner_headers())
    )
    emergent_activities = validate_success(
        api_client.list_schedule_activities(
            make_outage_planner_headers(),
            work_order_id=disposed["created_work_order_id"],
        )
    )
    given_completed_activity(emergent_activities[0]["id"])

    test_row = given_startup_test(
        outage["id"],
        test_code="CRD-DROP",
        sequence_index=1,
        predicted_reactivity_pcm=500,
    )
    validate_success(
        api_client.authorize_startup(outage["id"], make_outage_director_headers())
    )
    validate_success(
        api_client.satisfy_startup_test(
            test_row["id"], 520, make_regulatory_affairs_headers()
        )
    )
    return {
        "outage_id": outage["id"],
        "work_order_id": work_order["id"],
        "emergent_work_order_id": disposed["created_work_order_id"],
    }


class TestPerformanceIndexGrossVersusAdjusted:
    def test_four_variance_percentages_are_computed_from_the_stored_actuals(self):
        """780 actual hours against a 720-hour target is an 8.33 percent
        overrun, but netting off the 90 approved emergent hours turns the same
        outage into a 4.17 percent underrun.

        PRD 3.9: "The fourth figure is the emergent-adjusted duration variance:
        subtract the outage's `approved_emergent_hours` from
        `actual_duration_hours` to obtain the adjusted hours, then compute
        `adjusted_duration_variance_pct` as the adjusted hours less
        `duration_target_hours`, divided by `duration_target_hours`, multiplied
        by 100 and rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/performance_index_gross_versus_emergent_adjusted_diverge
        """
        ctx = _drive_outage_to_online_with_approved_emergent_work()
        outage = read_outage(ctx["outage_id"])
        assert outage["status"] == OutageStatus.ONLINE

        reviewed = validate_success(
            api_client.post_outage_review(
                ctx["outage_id"],
                {"actual_duration_hours": 780, "actual_cost_usd": 42000000},
                make_outage_director_headers(),
            )
        )
        assert reviewed["status"] == OutageStatus.REVIEWED
        assert reviewed["approved_emergent_hours"] == pytest.approx(90.00, abs=0.01)
        assert reviewed["dose_committed_mrem"] == pytest.approx(750.00, abs=0.01)
        assert reviewed["duration_variance_pct"] == pytest.approx(8.33, abs=0.01)
        assert reviewed["adjusted_duration_variance_pct"] == pytest.approx(-4.17, abs=0.01)
        assert reviewed["dose_variance_pct"] == pytest.approx(-25.00, abs=0.01)
        assert reviewed["cost_variance_pct"] == pytest.approx(5.00, abs=0.01)

    def test_the_two_composite_indices_diverge_on_the_duration_term_alone(self):
        """The gross index carries a 4.165-point duration penalty the adjusted
        index does not, because an underrun contributes zero rather than credit.

        PRD 3.9: "`adjusted_performance_index` is the same index computed with
        `adjusted_duration_variance_pct` — the number used for crew performance
        review, in which hours the crew could not have foreseen are excluded."

        Design: Difficulty/dual_variant_calc/performance_index_gross_versus_emergent_adjusted_diverge
        """
        ctx = _drive_outage_to_online_with_approved_emergent_work()
        reviewed = validate_success(
            api_client.post_outage_review(
                ctx["outage_id"],
                {"actual_duration_hours": 780, "actual_cost_usd": 42000000},
                make_outage_director_headers(),
            )
        )
        assert reviewed["outage_performance_index"] == pytest.approx(94.84, abs=0.01)
        assert reviewed["adjusted_performance_index"] == pytest.approx(99.00, abs=0.01)
        assert reviewed["adjusted_performance_index"] > reviewed["outage_performance_index"], (
            "with approved emergent hours on record the two indices must diverge"
        )


class TestRwpDoseRoundingOrder:
    def test_per_worker_figure_is_rounded_before_the_crew_multiplication(self):
        """23 mrem/hr over 5.5 hours with a 0.135 shielding credit gives an
        unrounded 109.4225 mrem per worker. Rounding first and then multiplying
        by three workers gives 328.26; multiplying first gives 328.27.

        PRD 3.7: "Second, multiply that **already rounded** per-worker figure by
        `worker_count` and round half up to two decimal places to give
        `collective_dose_mrem`; multiplying the unrounded per-worker figure and
        rounding the product afterwards is a different and incorrect answer for
        most inputs."

        Design: Difficulty/combinatorial_formula/rwp_dose_rounds_per_worker_before_multiplying_by_crew
        """
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            area_code="RA-2", dose_rate_mrem_per_hr=23, survey_buffer_hours=2
        )
        outage = given_outage(designation="2R26", dose_budget_total_mrem=5000)
        work_order = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Steam generator eddy current inspection",
            estimated_hours=40,
            estimated_cost_usd=250000,
            estimated_dose_mrem=100,
        )
        permit = given_draft_rwp(
            work_order["id"],
            rad_area["id"],
            worker_count=3,
            shielding_factor=0.135,
            planned_start_offset_hours=10,
            planned_duration_hours=5.5,
        )

        expected = expected_rwp_doses(23, 5.5, 0.135, 3)
        assert permit["per_worker_dose_mrem"] == pytest.approx(109.42, abs=0.01)
        assert permit["collective_dose_mrem"] == pytest.approx(328.26, abs=0.01)
        assert permit["collective_dose_mrem"] != pytest.approx(328.27, abs=0.001), (
            "328.27 is the answer produced by multiplying the unrounded per-worker figure"
        )
        assert permit["contingency_dose_mrem"] == pytest.approx(65.65, abs=0.01)
        assert permit["committed_dose_mrem"] == pytest.approx(393.91, abs=0.01)
        assert permit["committed_dose_mrem"] == pytest.approx(
            expected["committed_dose_mrem"], abs=0.01
        )

    def test_drafting_sets_the_alara_flag_but_commits_no_dose(self):
        """The 328.26 mrem collective figure clears the 300-mrem ALARA gate, yet
        the outage's dose ledger is still at zero because the permit is only
        drafted.

        PRD 3.7: "A drafted permit lands in `status` `DRAFT` with
        `alara_review_reference` null, `actual_dose_mrem` null and `void_reason`
        null, and drafting commits no dose whatsoever to the outage."

        Design: Difficulty/combinatorial_formula/rwp_dose_rounds_per_worker_before_multiplying_by_crew
        """
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            area_code="RA-2", dose_rate_mrem_per_hr=23, survey_buffer_hours=2
        )
        outage = given_outage(designation="2R26", dose_budget_total_mrem=5000)
        work_order = given_work_order(
            outage["id"], wo_type=WorkOrderType.INSPECTION, estimated_hours=40
        )
        permit = given_draft_rwp(
            work_order["id"],
            rad_area["id"],
            worker_count=3,
            shielding_factor=0.135,
            planned_start_offset_hours=10,
            planned_duration_hours=5.5,
        )
        assert permit["status"] == RwpStatus.DRAFT
        assert permit["alara_review_required"] is True, (
            "a 328.26 mrem collective figure is at or above {} mrem".format(
                ALARA_REVIEW_THRESHOLD_MREM
            )
        )
        assert permit["alara_review_reference"] is None
        assert permit["actual_dose_mrem"] is None
        assert permit["void_reason"] is None

        outage_after = read_outage(outage["id"])
        assert outage_after["dose_committed_mrem"] == pytest.approx(0.00, abs=0.01)
        assert outage_after["dose_budget_remaining_mrem"] == pytest.approx(5000.00, abs=0.01)


class TestScopeContingencyTierSelection:
    def _outage_with_two_approved_work_orders(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(designation="2R26", cost_budget_usd=40000000)
        first = given_approved_work_order(
            outage["id"],
            title="WO-1 turbine overhaul",
            estimated_hours=100,
            estimated_cost_usd=3000000,
            estimated_dose_mrem=0,
        )
        second = given_planned_work_order(
            outage["id"],
            title="WO-2 condenser retube",
            estimated_hours=100,
            estimated_cost_usd=1800000,
            estimated_dose_mrem=0,
        )
        return outage, first, second

    def test_base_below_five_million_takes_the_eight_percent_rate(self):
        """A 4,800,000 base sits below the 5,000,000 boundary, so the flat rate
        is 8 percent and the contingency is 384,000.00.

        PRD 3.2: "`scope_contingency_usd` is the base multiplied by the selected
        rate, rounded half up to two decimal places, and `total_scope_cost_usd`
        is the base plus the contingency, likewise rounded."

        Design: Difficulty/combinatorial_formula/scope_contingency_tier_selected_from_base_not_from_total
        """
        outage, _first, second = self._outage_with_two_approved_work_orders()
        validate_success(
            api_client.approve_work_order_scope(
                second["id"], make_outage_director_headers()
            )
        )
        after = read_outage(outage["id"])
        assert after["approved_scope_cost_usd"] == pytest.approx(4800000.00, abs=0.01)
        assert after["scope_contingency_usd"] == pytest.approx(384000.00, abs=0.01)
        assert after["total_scope_cost_usd"] == pytest.approx(5184000.00, abs=0.01)
        assert_scope_rollup_consistent(after)

    def test_tier_is_not_reselected_from_the_base_plus_contingency(self):
        """The total of 5,184,000.00 crosses the 5,000,000 boundary, but the rate
        stays at 8 percent because the tier is chosen from the base alone.

        PRD 3.2: "The rate is flat across the whole base, not marginal per band,
        and the tier is selected from the base alone — selecting it from the base
        plus contingency is a different and incorrect answer whenever the
        contingency would push the base across a boundary."

        Design: Difficulty/combinatorial_formula/scope_contingency_tier_selected_from_base_not_from_total
        """
        outage, _first, second = self._outage_with_two_approved_work_orders()
        validate_success(
            api_client.approve_work_order_scope(
                second["id"], make_outage_director_headers()
            )
        )
        after = read_outage(outage["id"])
        assert after["scope_contingency_usd"] != pytest.approx(576000.00, abs=0.01), (
            "576000.00 is the 12 percent answer produced by reselecting the tier "
            "from the base plus contingency"
        )
        assert after["total_scope_cost_usd"] != pytest.approx(5376000.00, abs=0.01)
        assert after["total_scope_cost_usd"] == pytest.approx(5184000.00, abs=0.01)
