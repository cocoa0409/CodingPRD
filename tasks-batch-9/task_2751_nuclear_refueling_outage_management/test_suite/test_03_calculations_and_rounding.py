"""Calculation coverage: pinned formulas, input-set filtering, constants,
rounding mode, tier boundaries, topological maxima, ledger replay and the two
posture thresholds."""

import pytest

from test_helpers import (
    ALARA_REVIEW_THRESHOLD_MREM,
    AlaraPosture,
    CoreLoadPatternStatus,
    CLOCK_EPOCH,
    DoseDirection,
    DoseReason,
    MIN_SHUTDOWN_MARGIN_PCM,
    Priority,
    RwpStatus,
    SafetyFunctionCode,
    SchedulePosture,
    StationUnit,
    WorkOrderStatus,
    WorkOrderType,
    api_client,
    assert_dose_budget_consistent,
    assert_ledger_rows_ascending,
    assert_priority_band_matches_score,
    assert_scope_rollup_consistent,
    expected_reactivity_margin,
    expected_rwp_doses,
    given_approved_core_load_pattern,
    given_approved_work_order,
    given_draft_rwp,
    given_outage,
    given_planned_work_order,
    given_rad_area,
    given_safety_function,
    given_schedule_activity,
    given_work_order,
    make_outage_director_headers,
    make_rad_protection_manager_headers,
    make_rad_protection_planner_headers,
    make_reactor_engineer_headers,
    read_activity,
    read_dose_rows,
    read_outage,
    read_work_order,
    set_clock,
    validate_success,
)


class TestCoreLoadReactivityMargin:
    def test_the_margin_reads_fresh_assemblies_and_burnup_but_not_discharge(self):
        """40 fresh assemblies against an 18000 MWd/MTU cycle give
        800 + 480 - 270 = 1010.00 pcm, which clears the 1000-pcm floor, and the
        80 discharged assemblies never enter the arithmetic.

        PRD 3.3: "Start from a base shutdown margin of 800 pcm. Add 12 pcm for
        each fresh assembly the pattern loads. Then subtract a burnup penalty:
        divide `cycle_length_mwd_mtu` by 1000 to express the cycle in gigawatt-days
        per metric ton, multiply that quotient by 15 pcm, and subtract the product."

        Design: Corner/calculations/core_load_reactivity_margin_computed_from_known_inputs
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(station_unit=StationUnit.UNIT_1, designation="1R24")
        version_before = outage["version"]

        pattern = validate_success(
            api_client.create_core_load_pattern(
                outage["id"],
                {
                    "cycle_length_mwd_mtu": 18000,
                    "fresh_assembly_count": 40,
                    "discharge_assembly_count": 80,
                    "expected_outage_version": version_before,
                },
                make_reactor_engineer_headers(),
            ),
            201,
        )
        assert pattern["reactivity_margin_pcm"] == pytest.approx(1010.00, abs=0.01)
        assert pattern["reactivity_margin_pcm"] == pytest.approx(
            expected_reactivity_margin(40, 18000), abs=0.01
        )
        assert pattern["reactivity_margin_pcm"] >= MIN_SHUTDOWN_MARGIN_PCM
        assert pattern["status"] == CoreLoadPatternStatus.DRAFT
        assert pattern["discharge_assembly_count"] == 80

        assert read_outage(outage["id"])["version"] == version_before + 1


class TestScopeCostRollupInputSet:
    def _outage_with_three_work_orders(self):
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=720,
        )
        first = given_planned_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="WO-A main generator inspection support",
            estimated_hours=200,
            estimated_cost_usd=1000000,
            estimated_dose_mrem=0,
        )
        second = given_planned_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="WO-B valve rebuild",
            estimated_hours=100,
            estimated_cost_usd=500000,
            estimated_dose_mrem=0,
        )
        third = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="WO-C insulation replacement",
            estimated_hours=50,
            estimated_cost_usd=300000,
            estimated_dose_mrem=0,
        )
        return outage, first, second, third

    def test_planned_and_scoped_work_orders_never_enter_the_base(self):
        """Approving the 1,000,000 job makes the base exactly that figure rather
        than the 1,800,000 of all three rows, and the 8 percent tier then gives a
        1,080,000.00 total.

        PRD 3.2: "First, `approved_scope_cost_usd` is the sum of
        `estimated_cost_usd` over the outage's work orders whose status is
        `APPROVED`, `EXECUTING` or `COMPLETE`, rounded half up to two decimal
        places; work orders in `SCOPED`, `PLANNED` or `DEFERRED` are excluded
        entirely."

        Design: Corner/calculations/scope_cost_rollup_counts_only_approved_executing_and_complete
        """
        outage, first, second, third = self._outage_with_three_work_orders()

        approved = validate_success(
            api_client.approve_work_order_scope(first["id"], make_outage_director_headers())
        )
        assert approved["status"] == WorkOrderStatus.APPROVED
        assert approved["priority_score"] == pytest.approx(50.00, abs=0.01)
        assert approved["priority"] == Priority.HIGH
        assert_priority_band_matches_score(approved)

        mid = read_outage(outage["id"])
        assert mid["approved_scope_cost_usd"] == pytest.approx(1000000.00, abs=0.01)
        assert mid["scope_contingency_usd"] == pytest.approx(80000.00, abs=0.01)
        assert mid["total_scope_cost_usd"] == pytest.approx(1080000.00, abs=0.01)
        assert mid["approved_scope_cost_usd"] != pytest.approx(1800000.00, abs=0.01), (
            "1800000.00 is the answer produced by summing every work order"
        )
        assert_scope_rollup_consistent(mid)

        assert read_work_order(second["id"])["status"] == WorkOrderStatus.PLANNED
        assert read_work_order(third["id"])["status"] == WorkOrderStatus.SCOPED

    def test_deferring_the_only_approved_row_empties_the_input_set(self):
        """Once the approved job is deferred the base falls back to 0.00, so the
        contingency and total collapse with it even though two other work orders
        still exist.

        PRD 3.2: "Because deferred work orders leave the base, deferring one
        approved job can drop the rate an entire tier."

        Design: Corner/calculations/scope_cost_rollup_counts_only_approved_executing_and_complete
        """
        outage, first, _second, _third = self._outage_with_three_work_orders()
        validate_success(
            api_client.approve_work_order_scope(first["id"], make_outage_director_headers())
        )

        validate_success(
            api_client.defer_work_order(
                first["id"],
                "Scope moved to the following cycle",
                make_outage_director_headers(),
            )
        )

        after = read_outage(outage["id"])
        assert after["approved_scope_cost_usd"] == pytest.approx(0.00, abs=0.01)
        assert after["scope_contingency_usd"] == pytest.approx(0.00, abs=0.01)
        assert after["total_scope_cost_usd"] == pytest.approx(0.00, abs=0.01)
        assert read_work_order(first["id"])["status"] == WorkOrderStatus.DEFERRED


class TestPriorityBandConstants:
    def test_a_score_of_exactly_seventy_five_is_critical_and_seventy_four_is_high(self):
        """Both work orders score 30 + 25 + 20 with a duration-pressure term that
        rounds to 0.00 against a 100000-hour target; the second differs only by
        100 mrem, which subtracts exactly one whole penalty block.

        PRD 3.2: "Both comparisons are inclusive and are made on the rounded
        figure, so a score of exactly 75.00 is `CRITICAL` while 74.99 is `HIGH`."

        Design: Corner/calculations/priority_band_constants_decide_at_exactly_seventy_five
        """
        set_clock(CLOCK_EPOCH)
        safety_function = given_safety_function(
            station_unit=StationUnit.UNIT_1,
            function_code=SafetyFunctionCode.DECAY_HEAT_REMOVAL,
            trains_total=3,
            min_trains_required=1,
        )
        assert safety_function["max_concurrent_oos_trains"] == 2
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=100000,
        )

        critical = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Steam generator eddy current inspection",
            estimated_hours=1,
            estimated_cost_usd=100000,
            estimated_dose_mrem=0,
            regulatory_commitment=True,
            safety_function_id=safety_function["id"],
        )
        high = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Reactor coolant pump inspection",
            estimated_hours=1,
            estimated_cost_usd=100000,
            estimated_dose_mrem=100,
            regulatory_commitment=True,
            safety_function_id=safety_function["id"],
        )

        assert critical["priority_score"] == pytest.approx(75.00, abs=0.01)
        assert critical["priority"] == Priority.CRITICAL, (
            "the band test is at least 75, not strictly greater than 75"
        )
        assert high["priority_score"] == pytest.approx(74.00, abs=0.01)
        assert high["priority"] == Priority.HIGH
        assert critical["priority_score"] - high["priority_score"] == pytest.approx(
            1.00, abs=0.01
        ), "100 mrem is exactly one completed penalty block"
        assert_priority_band_matches_score(critical)
        assert_priority_band_matches_score(high)


class TestPerWorkerDoseRoundingMode:
    def test_a_third_decimal_half_rounds_up_rather_than_to_the_even_digit(self):
        """12.5 mrem/h over 3.7 hours with a 0.5 shielding credit is exactly
        23.125, so half-up gives 23.13 and the whole downstream chain follows from
        that digit.

        PRD 2.5: "Money, collective dose in mrem, hours, percentages and computed
        scores are all Decimal quantities carried to exactly 2 decimal places, and
        every rounding step is round-half-up."

        Design: Corner/calculations/per_worker_dose_tie_rounds_half_up_not_half_even
        """
        set_clock(CLOCK_EPOCH)
        rad_area = given_rad_area(
            station_unit=StationUnit.UNIT_1,
            area_code="AUX-EL306",
            dose_rate_mrem_per_hr=12.5,
            occupancy_limit_workers=10,
            survey_buffer_hours=1,
        )
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            dose_budget_total_mrem=5000,
        )
        work_order = given_work_order(
            outage["id"],
            wo_type=WorkOrderType.INSPECTION,
            title="Auxiliary building survey",
            estimated_hours=8,
            estimated_cost_usd=20000,
            estimated_dose_mrem=50,
            requires_rad_work=True,
        )

        permit = given_draft_rwp(
            work_order["id"],
            rad_area["id"],
            worker_count=2,
            shielding_factor=0.5,
            planned_start_offset_hours=0,
            planned_duration_hours=3.7,
        )
        assert permit["per_worker_dose_mrem"] == pytest.approx(23.13, abs=0.01)
        assert permit["per_worker_dose_mrem"] != pytest.approx(23.12, abs=0.001), (
            "23.12 is the answer banker's rounding would give for 23.125"
        )
        assert permit["collective_dose_mrem"] == pytest.approx(46.26, abs=0.01)
        assert permit["contingency_dose_mrem"] == pytest.approx(9.25, abs=0.01)
        assert permit["committed_dose_mrem"] == pytest.approx(55.51, abs=0.01)

        expected = expected_rwp_doses(12.5, 3.7, 0.5, 2)
        assert permit["committed_dose_mrem"] == pytest.approx(
            expected["committed_dose_mrem"], abs=0.01
        )
        assert permit["alara_review_required"] is False, (
            "46.26 mrem is below the {} mrem review threshold".format(
                ALARA_REVIEW_THRESHOLD_MREM
            )
        )
        assert permit["status"] == RwpStatus.DRAFT


class TestScopeContingencyTierBoundary:
    def test_a_base_of_exactly_five_million_falls_through_to_the_twelve_percent_rate(self):
        """Two independent outages differ by one dollar of base: 5,000,000.00 is
        not below the ceiling and takes 12 percent, while 4,999,999.00 keeps
        8 percent, so one dollar moves the contingency by 200,000.08.

        PRD 3.2: "A single contingency rate is then selected from that base:
        8 percent when the base is below 5,000,000 US dollars, 12 percent when the
        base is below 20,000,000, and 15 percent otherwise."

        Design: Corner/calculations/scope_contingency_tier_boundary_is_exclusive_below_and_inclusive_at
        """
        set_clock(CLOCK_EPOCH)
        at_boundary = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24-AT",
            duration_target_hours=720,
        )
        below_boundary = given_outage(
            station_unit=StationUnit.UNIT_2,
            designation="2R24-BELOW",
            duration_target_hours=720,
        )
        given_approved_work_order(
            at_boundary["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Turbine overhaul at the boundary",
            estimated_hours=200,
            estimated_cost_usd=5000000,
            estimated_dose_mrem=0,
        )
        given_approved_work_order(
            below_boundary["id"],
            wo_type=WorkOrderType.MAINTENANCE,
            title="Turbine overhaul one dollar below",
            estimated_hours=200,
            estimated_cost_usd=4999999,
            estimated_dose_mrem=0,
        )

        at_row = read_outage(at_boundary["id"])
        assert at_row["approved_scope_cost_usd"] == pytest.approx(5000000.00, abs=0.01)
        assert at_row["scope_contingency_usd"] == pytest.approx(600000.00, abs=0.01)
        assert at_row["total_scope_cost_usd"] == pytest.approx(5600000.00, abs=0.01)
        assert_scope_rollup_consistent(at_row)

        below_row = read_outage(below_boundary["id"])
        assert below_row["approved_scope_cost_usd"] == pytest.approx(4999999.00, abs=0.01)
        assert below_row["scope_contingency_usd"] == pytest.approx(399999.92, abs=0.01)
        assert below_row["total_scope_cost_usd"] == pytest.approx(5399998.92, abs=0.01)
        assert_scope_rollup_consistent(below_row)

        assert (
            at_row["scope_contingency_usd"] - below_row["scope_contingency_usd"]
        ) == pytest.approx(200000.08, abs=0.01), (
            "the rate is flat over the whole base, so crossing the boundary is a jump"
        )


class TestCriticalPathOverDisconnectedChains:
    def test_the_projection_is_the_maximum_over_components_never_their_sum(self):
        """A 250-hour two-hop chain and a lone 300-hour root are disconnected
        components; the projection is 300.00, and the flag is true only for the
        winning root, leaving both members of the losing chain false.

        PRD 3.4: "The outage's `projected_duration_hours` is then the largest
        `path_length_hours` in the input set, or 0.00 when the input set is empty,
        and its `risk_adjusted_duration_hours` is the largest
        `risk_adjusted_path_length_hours`, or 0.00 when the set is empty."

        Design: Corner/calculations/critical_path_over_disconnected_chains_takes_the_longest
        """
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

        lone_root = given_schedule_activity(
            outage["id"],
            label="B1 main generator rotor work",
            planned_start_offset_hours=0,
            planned_duration_hours=300,
        )

        a1 = read_activity(first["id"])
        assert a1["path_length_hours"] == pytest.approx(100.00, abs=0.01)
        assert a1["risk_adjusted_path_length_hours"] == pytest.approx(110.00, abs=0.01)
        a2 = read_activity(second["id"])
        assert a2["path_length_hours"] == pytest.approx(250.00, abs=0.01)
        assert a2["risk_adjusted_path_length_hours"] == pytest.approx(275.00, abs=0.01)
        b1 = read_activity(lone_root["id"])
        assert b1["path_length_hours"] == pytest.approx(300.00, abs=0.01)
        assert b1["risk_adjusted_path_length_hours"] == pytest.approx(330.00, abs=0.01)

        after = read_outage(outage["id"])
        assert after["projected_duration_hours"] == pytest.approx(300.00, abs=0.01)
        assert after["risk_adjusted_duration_hours"] == pytest.approx(330.00, abs=0.01)
        assert after["projected_duration_hours"] != pytest.approx(550.00, abs=0.01), (
            "550.00 is the answer produced by summing the two components"
        )
        assert after["critical_path_activity_id"] == lone_root["id"]
        assert after["schedule_posture"] == SchedulePosture.ON_TRACK

        assert b1["is_critical_path"] is True
        assert a1["is_critical_path"] is False
        assert a2["is_critical_path"] is False


class TestDoseLedgerReplayNetsAnUnderrun:
    def test_closeout_appends_a_release_and_the_replay_nets_to_the_actual(self):
        """A 180.00 commitment closed at an actual of 100.00 appends an 80.00
        RELEASE rather than replacing the original row, and the two-row replay
        leaves the outage carrying exactly 100.00.

        PRD 3.7: "when `actual_dose_mrem` is less than `committed_dose_mrem` a
        `RELEASE` row is appended whose `amount_mrem` is `committed_dose_mrem` less
        `actual_dose_mrem` and whose `reason` is `RWP_CLOSED_UNDERRUN`"

        Design: Corner/calculations/dose_ledger_replay_nets_a_closeout_underrun_against_the_commitment
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

        approved = validate_success(
            api_client.approve_rwp(permit["id"], make_rad_protection_manager_headers())
        )
        assert approved["committed_dose_mrem"] == pytest.approx(180.00, abs=0.01)
        mid = read_outage(outage["id"])
        assert mid["dose_committed_mrem"] == pytest.approx(180.00, abs=0.01)
        assert mid["dose_budget_remaining_mrem"] == pytest.approx(4820.00, abs=0.01)

        closed = validate_success(
            api_client.close_rwp(permit["id"], 100, make_rad_protection_planner_headers())
        )
        assert closed["status"] == RwpStatus.CLOSED
        assert closed["actual_dose_mrem"] == pytest.approx(100.00, abs=0.01)

        rows = read_dose_rows(permit["id"])
        assert len(rows) == 2
        assert_ledger_rows_ascending(rows)
        assert rows[0]["direction"] == DoseDirection.COMMIT
        assert rows[0]["amount_mrem"] == pytest.approx(180.00, abs=0.01)
        assert rows[0]["reason"] == DoseReason.RWP_APPROVED
        assert rows[1]["direction"] == DoseDirection.RELEASE
        assert rows[1]["amount_mrem"] == pytest.approx(80.00, abs=0.01)
        assert rows[1]["reason"] == DoseReason.RWP_CLOSED_UNDERRUN

        after = read_outage(outage["id"])
        assert after["dose_committed_mrem"] == pytest.approx(100.00, abs=0.01)
        assert after["dose_budget_remaining_mrem"] == pytest.approx(4900.00, abs=0.01)
        assert after["alara_posture"] == AlaraPosture.NORMAL
        assert_dose_budget_consistent(after)


class TestSchedulePostureThresholds:
    def test_both_posture_boundaries_are_inclusive_and_the_next_hour_tips_over(self):
        """Against a 100-hour target a 100.00 projection is ON_TRACK, a 110.00
        projection sits exactly on the ceiling and is AT_RISK, and 111.00 is
        RECOVERY_REQUIRED.

        PRD 3.4: "Both boundaries are inclusive: a projection exactly equal to the
        target is `ON_TRACK`, and a projection exactly equal to the rounded
        110-percent ceiling is `AT_RISK`."

        Design: Corner/calculations/schedule_posture_thresholds_at_target_and_at_the_ten_percent_ceiling
        """
        set_clock(CLOCK_EPOCH)
        outage = given_outage(
            station_unit=StationUnit.UNIT_1,
            designation="1R24",
            duration_target_hours=100,
        )

        on_target = given_schedule_activity(
            outage["id"],
            label="P1 exactly on target",
            planned_start_offset_hours=0,
            planned_duration_hours=100,
        )
        at_target = read_outage(outage["id"])
        assert at_target["projected_duration_hours"] == pytest.approx(100.00, abs=0.01)
        assert at_target["schedule_posture"] == SchedulePosture.ON_TRACK

        on_ceiling = given_schedule_activity(
            outage["id"],
            label="P2 exactly on the ceiling",
            planned_start_offset_hours=0,
            planned_duration_hours=110,
        )
        at_ceiling = read_outage(outage["id"])
        assert at_ceiling["projected_duration_hours"] == pytest.approx(110.00, abs=0.01)
        assert at_ceiling["schedule_posture"] == SchedulePosture.AT_RISK

        past_ceiling_activity = given_schedule_activity(
            outage["id"],
            label="P3 one hour past the ceiling",
            planned_start_offset_hours=0,
            planned_duration_hours=111,
        )
        past_ceiling = read_outage(outage["id"])
        assert past_ceiling["projected_duration_hours"] == pytest.approx(111.00, abs=0.01)
        assert past_ceiling["schedule_posture"] == SchedulePosture.RECOVERY_REQUIRED

        assert past_ceiling["critical_path_activity_id"] == past_ceiling_activity["id"]
        assert read_activity(past_ceiling_activity["id"])["is_critical_path"] is True
        assert read_activity(on_target["id"])["is_critical_path"] is False
        assert read_activity(on_ceiling["id"])["is_critical_path"] is False
