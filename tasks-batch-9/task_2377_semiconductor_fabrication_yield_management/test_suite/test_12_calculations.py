"""Derived numbers: the dispatch score, the SPC engine, pricing, yield and cycle time.

Each scenario arranges inputs whose arithmetic is fully determined, then pins the
computed value and the rounding scale the specification assigns to it.
"""

from test_helpers import (
    ChamberSpec,
    EquipmentSpec,
    LotSpec,
    StepSpec,
    build_line,
    metrology_step_spec,
    open_run,
    quality_manager_headers,
    raise_particle_excursion,
    single_step_spec,
    sorted_run,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_days,
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
    assert_timestamp_equals,
)
from test_helpers.factories import wafer_result


# --------------------------------------------------------------------------
# The dispatch score: 100 less three penalties
# --------------------------------------------------------------------------


class TestDispatchScore:
    def test_a_freshly_qualified_idle_chamber_scores_the_full_hundred(self, fab):
        """No decay, no contamination and no maintenance proximity leaves 100.00.

        PRD: "The **qualification-decay penalty** uses the remaining fraction of
        the chamber's qualification window: take the interval from the current
        logical instant to `qual_expires_at`, divide it by the full interval from
        `qualified_at` to `qual_expires_at`, and floor the result at zero; the
        penalty is 40.0 multiplied by one minus that remaining fraction, so a
        freshly qualified chamber loses nothing and a chamber at the very end of
        its window loses the full 40 points."

        Design: Corner/calculations/dispatch_score_is_one_hundred_for_a_freshly_qualified_idle_chamber
        """
        env = build_line(fab, single_step_spec())
        assert_hours(fab.read_equipment(env.equipments[0]["id"])["hours_since_pm"], 0.0, "hours_since_pm")
        assert_hours(fab.read_chamber(env.chambers[0]["id"])["particle_count"], 0.0, "particle_count")

        run = open_run(fab, env, step_ix=0, lot_ix=0)

        assert run["chamber_id"] == env.chambers[0]["id"]
        assert_hours(run["dispatch_score"], 100.00, "dispatch_score")
        assert_hours(run["reserved_hours"], 2.00, "reserved_hours")
        assert run["status"] == "OPEN"
        assert_timestamp_equals(
            run["tracked_in_at"], "2026-08-01T00:00:00Z", "tracked_in_at"
        )
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "OCCUPIED"
        tool = fab.read_equipment(env.equipments[0]["id"])
        assert tool["state"] == "PRODUCTIVE"
        assert_hours(
            tool["available_capacity_hours"], 718.00, "available_capacity_hours"
        )

    def test_a_tool_deep_into_its_pm_window_costs_the_maintenance_penalty(self, fab):
        """140 of 168 hours is 83.33 percent through, so 20.0 times that comes off.

        PRD: "The **maintenance-proximity penalty** is 20.0 multiplied by the
        smaller of 1.0 and the tool's `hours_since_pm` divided by its
        `pm_interval_hours` — except that for a lot whose `priority_class` is
        `SUPER_HOT` this penalty is forced to zero, so a super-hot lot ignores
        maintenance proximity entirely and can win a different chamber than a
        `STANDARD` or `HOT` lot would from exactly the same chamber population."

        Design: Corner/calculations/dispatch_pm_proximity_penalty_applies_the_pm_weight_constant
        """
        env = build_line(
            fab,
            single_step_spec(
                equipments=[EquipmentSpec("LITHO-1", "LITHO", 168.0, 24.0, 140.0)],
                lots=[LotSpec("LOT-001", 3, "STANDARD")],
            ),
        )

        run = open_run(fab, env, step_ix=0, lot_ix=0)

        assert run["chamber_id"] == env.chambers[0]["id"]
        # 100 less 20.0 times 140.0 / 168.0.
        assert_hours(run["dispatch_score"], 83.33, "dispatch_score")
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["hours_since_pm"],
            140.0,
            "hours_since_pm",
        )
        assert_hours(
            fab.read_chamber(env.chambers[0]["id"])["particle_count"],
            0.0,
            "particle_count",
        )

    def test_an_exact_tie_between_two_free_chambers_goes_to_the_lower_code(self, fab):
        """Both chambers score 100.00, so CH_L1 wins first and CH_L2 takes the next lot.

        PRD: "Candidates are ordered by score descending, and ties are broken by
        ascending `chamber_code`."

        PRD: "Chambers on tools in `PM` or `DOWN` are excluded by that filter, as
        are chambers already `OCCUPIED` by an open run."

        Design: Corner/calculations/dispatch_skips_the_occupied_chamber_and_breaks_ties_on_chamber_code
        """
        env = build_line(
            fab,
            single_step_spec(
                chambers=[
                    ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0),
                    ChamberSpec("CH_L2", equipment_ix=0, recipe_ix=0),
                ],
                lots=[LotSpec("LOT-001", 3), LotSpec("LOT-002", 3)],
            ),
        )
        first = open_run(fab, env, step_ix=0, lot_ix=0)
        assert first["chamber_id"] == env.chambers[0]["id"]
        assert_hours(first["dispatch_score"], 100.00, "dispatch_score")

        second = open_run(fab, env, step_ix=0, lot_ix=1)

        assert second["chamber_id"] == env.chambers[1]["id"]
        assert_hours(second["dispatch_score"], 100.00, "dispatch_score")
        assert second["chamber_id"] != first["chamber_id"]
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "OCCUPIED"
        assert fab.read_chamber(env.chambers[1]["id"])["occupancy_state"] == "OCCUPIED"
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            716.00,
            "available_capacity_hours",
        )


# --------------------------------------------------------------------------
# The capacity ledger when the run overruns its reservation
# --------------------------------------------------------------------------


class TestCapacitySettlement:
    def test_the_ledger_settles_on_actual_hours_not_the_reservation(self, fab):
        """Three hours were spent against a two-hour reservation, and 3.00 is charged.

        PRD: "The tool's `available_capacity_hours` has `reserved_hours` credited
        back and `actual_hours` debited, and its `hours_since_pm` has
        `actual_hours` added."

        Design: Corner/calculations/ledger_settles_to_actual_hours_when_a_run_overruns_its_reservation
        """
        env = build_line(fab, single_step_spec())
        operator_id = env.operators[0]["id"]

        opening = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            opening["available_capacity_hours"], 720.00, "available_capacity_hours"
        )
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        assert_hours(run["reserved_hours"], 2.00, "reserved_hours")
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            718.00,
            "available_capacity_hours",
        )

        fab.set_clock("2026-08-01T03:00:00Z")
        closed = fab.track_out(run["id"], operator_id)

        assert closed["status"] == "COMPLETED"
        assert_hours(closed["actual_hours"], 3.00, "actual_hours")
        assert_timestamp_equals(
            closed["tracked_out_at"], "2026-08-01T03:00:00Z", "tracked_out_at"
        )
        settled = fab.read_equipment(env.equipments[0]["id"])
        assert_hours(
            settled["available_capacity_hours"], 717.00, "available_capacity_hours"
        )
        assert_hours(settled["hours_since_pm"], 3.0, "hours_since_pm")
        assert settled["state"] == "IDLE"
        assert fab.read_chamber(env.chambers[0]["id"])["occupancy_state"] == "FREE"


# --------------------------------------------------------------------------
# The SPC engine: classification, the run rule and severity
# --------------------------------------------------------------------------


class TestMeasurementClassification:
    def test_a_reading_exactly_on_target_is_in_control_and_clears_the_run_count(self, fab):
        """Zero deviation is inside the one-sigma band, so the chart stays pristine.

        PRD: "So the `classification` is `OUT_OF_SPEC` when the reading is
        strictly above `usl` or strictly below `lsl`; otherwise `OUT_OF_CONTROL`
        when the reading is at or above `ucl` or at or below `lcl`; otherwise
        `WARN` when the absolute deviation is at least twice `sigma`; otherwise
        `IN_CONTROL`."

        PRD: "If the absolute deviation is below one `sigma` — inside the
        one-sigma band — the count is reset to 0."

        Design: Corner/calculations/measurement_at_target_is_in_control_and_opens_no_excursion
        """
        env = build_line(fab, metrology_step_spec())
        run = open_run(fab, env, step_ix=0, lot_ix=0)

        measurement = fab.measure(
            run["id"], env.charts[0]["id"], 100.0, env.operators[0]["id"]
        )

        assert measurement["classification"] == "IN_CONTROL"
        assert_ratio(measurement["deviation_sigma"], 0.0000, "deviation_sigma")
        assert measurement["run_rule_triggered"] is False
        assert_nulls(measurement, "excursion_id")
        assert_fields(
            fab.read_chart(env.charts[0]["id"]),
            violation_count=0,
            consecutive_same_side_count=0,
            last_side="NONE",
            status="MONITORING",
        )

    def test_a_reading_sitting_on_the_upper_spec_limit_is_only_out_of_control(self, fab):
        """Spec limits are strict and control limits inclusive, so 110.0 misses OUT_OF_SPEC.

        PRD: "The boundary semantics are asymmetric on purpose: specification
        limits are strict, control limits are inclusive."

        PRD: "A specification penalty of 10.0 is added when the opening
        measurement's `classification` was `OUT_OF_SPEC`, and 0.0 otherwise."

        Design: Corner/calculations/measurement_exactly_at_the_upper_spec_limit_is_out_of_control_not_out_of_spec
        """
        env = build_line(fab, metrology_step_spec())
        run = open_run(fab, env, step_ix=0, lot_ix=0)

        measurement = fab.measure(
            run["id"], env.charts[0]["id"], 110.0, env.operators[0]["id"]
        )

        assert measurement["classification"] == "OUT_OF_CONTROL"
        assert_ratio(measurement["deviation_sigma"], 5.0000, "deviation_sigma")
        assert measurement["excursion_id"] is not None

        excursion = fab.read_excursion(measurement["excursion_id"])
        assert_fields(
            excursion,
            source_type="SPC",
            severity_variant="PROVISIONAL",
            affected_lot_count=1,
            severity_band="MEDIUM",
            status="OPEN",
        )
        assert_ratio(excursion["trigger_value"], 110.0000, "trigger_value")
        # 60.0 at the capped deviation ratio plus 3.0 for the single lot, and no
        # specification penalty because the reading never left specification.
        assert_hours(excursion["severity_score"], 63.00, "severity_score")
        assert_fields(
            fab.read_chart(env.charts[0]["id"]),
            violation_count=1,
            consecutive_same_side_count=1,
            last_side="ABOVE",
        )


class TestParticleExcursionScope:
    def test_a_reading_short_of_twice_the_limit_contains_at_chamber_scope(self, fab):
        """99.0 against a 50.0 limit is under the doubling, so only the chamber falls.

        PRD: "The automatic `containment_scope` is chosen by magnitude:
        `EQUIPMENT` when the reading is at or above twice the chamber's
        `particle_limit`, and `CHAMBER` otherwise."

        PRD: "At `CHAMBER` scope, the implicated chamber is driven `QUALIFIED →
        DISQUALIFIED` with `qualified_at` and `qual_expires_at` cleared to null,
        its open run is driven `OPEN → ABORTED` with the full reservation
        credited back to the tool, and that run's lot is raised to `QUAL_HOLD`
        with its `hold_excursion_id` set to this excursion."

        Design: Corner/calculations/particle_reading_below_twice_the_limit_contains_at_chamber_scope_only
        """
        env = build_line(fab, single_step_spec())
        run = open_run(fab, env, step_ix=0, lot_ix=0)
        assert_hours(
            fab.read_equipment(env.equipments[0]["id"])["available_capacity_hours"],
            718.00,
            "available_capacity_hours",
        )

        raised = raise_particle_excursion(fab, env, 99.0, chamber_ix=0)

        assert_hours(raised.chamber["particle_count"], 99.0, "particle_count")
        assert raised.chamber["qual_state"] == "DISQUALIFIED"
        assert raised.chamber["occupancy_state"] == "FREE"

        assert fab.count(
            fab.client.list_excursions(
                quality_manager_headers(), {"chamber_id": env.chambers[0]["id"]}
            )
        ) == 1
        assert_fields(
            raised.excursion,
            source_type="PARTICLE",
            status="CONTAINED",
            containment_scope="CHAMBER",
            severity_variant="FINAL",
            affected_lot_count=1,
            severity_band="MEDIUM",
        )
        assert_hours(raised.excursion["severity_score"], 63.00, "severity_score")
        assert_nulls(raised.excursion, "contained_by_user_id")

        tool = fab.read_equipment(env.equipments[0]["id"])
        assert tool["state"] == "IDLE"
        assert_hours(
            tool["available_capacity_hours"], 720.00, "available_capacity_hours"
        )
        aborted = fab.read_step_run(run["id"])
        assert aborted["status"] == "ABORTED"
        assert_nulls(aborted, "actual_hours")
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="QUAL_HOLD")


# --------------------------------------------------------------------------
# The speed-grade waterfall
# --------------------------------------------------------------------------


class TestSpeedGradeWaterfall:
    def test_a_premium_target_above_the_pool_absorbs_all_of_it(self, fab):
        """A 300-die premium target against 270 good die leaves the other buckets empty.

        PRD: "The waterfall then runs in a fixed order: `premium_die` is the
        smaller of `premium_target_die` and `good_die_total`; `standard_die` is
        the smaller of `standard_target_die` and whatever remains of
        `good_die_total` after `premium_die` is taken; and `value_die` absorbs the
        entire remainder, being `good_die_total` less `premium_die` less
        `standard_die`."

        Design: Corner/calculations/speed_grade_waterfall_fills_premium_first_and_leaves_no_remainder
        """
        env = build_line(fab, single_step_spec())
        sort_run = sorted_run(
            fab,
            env,
            [
                wafer_result(1, 100, 90, edge_ring_fails=10),
                wafer_result(2, 100, 90, edge_ring_fails=10),
                wafer_result(3, 100, 90, edge_ring_fails=10),
            ],
            gross_die_per_wafer=100,
            baseline_yield=0.92,
        )
        assert sort_run["good_die_total"] == 270

        binned = fab.bin_sort_run(sort_run["id"], 300, 50)

        assert_fields(binned, premium_die=270, standard_die=0, value_die=0)
        assert_fields(
            binned,
            premium_target_die=300,
            standard_target_die=50,
            status="BINNED",
        )
        assert (
            binned["premium_die"] + binned["standard_die"] + binned["value_die"]
            == sort_run["good_die_total"]
        )


# --------------------------------------------------------------------------
# The forward-looking cycle-time projection
# --------------------------------------------------------------------------


class TestCycleTimeProjection:
    def test_a_super_hot_lot_projects_on_the_lowest_queue_factor(self, fab):
        """Five remaining hours at 1.05 over 24 gives 0.219 days, well inside target.

        PRD: "`queue_factor` is read from the lot's `priority_class`: 1.60 for
        `STANDARD`, 1.25 for `HOT`, and 1.05 for `SUPER_HOT`."

        PRD: "`projected_remaining_days` is `remaining_standard_hours` multiplied
        by `queue_factor`, divided by 24, rounded to 3 decimal places."

        Design: Corner/calculations/super_hot_queue_factor_scales_the_remaining_hours_projection
        """
        env = build_line(
            fab,
            two_recipe_line_spec(
                steps=[
                    StepSpec(10, "LITHO-1", 2.0, recipe_ix=0),
                    StepSpec(20, "ETCH-1", 3.0, recipe_ix=1),
                ],
                charts=[],
                planned_wafer_starts=10,
                capacity_budget_hours=200.0,
                cycle_time_target_days=30.0,
                lots=[LotSpec("LOT-001", 3, "SUPER_HOT")],
            ),
        )
        assert_hours(env.flow["total_standard_hours"], 5.0, "total_standard_hours")
        assert_lot_state(env.lots[0], flow_state="RELEASED", current_step_seq=0)
        assert_timestamp_equals(
            env.lots[0]["released_at"], "2026-08-01T00:00:00Z", "released_at"
        )

        projection = fab.cycle_time_projection(env.lots[0]["id"])

        assert_hours(
            projection["remaining_standard_hours"], 5.0, "remaining_standard_hours"
        )
        assert float(projection["queue_factor"]) == 1.05
        # 5.0 hours times 1.05 is 5.25 hours, and 5.25 / 24 is 0.21875.
        assert_days(
            projection["projected_remaining_days"], 0.219, "projected_remaining_days"
        )
        assert_days(projection["elapsed_days"], 0.000, "elapsed_days")
        assert_days(
            projection["projected_cycle_time_days"], 0.219, "projected_cycle_time_days"
        )
        assert projection["cycle_time_status"] == "ON_TARGET"


# --------------------------------------------------------------------------
# Plan pricing at the bottom tier
# --------------------------------------------------------------------------


class TestTierZeroPricing:
    def test_a_twenty_percent_utilisation_commits_without_a_surcharge(self, fab):
        """TIER_0 carries a zero rate, so committed hours equal base hours exactly.

        PRD: "Fourth, the surcharge rate follows from the tier: zero for
        `TIER_0`, five percent for `TIER_1`, twelve percent for `TIER_2`, and
        twenty-five percent for `TIER_3`."

        PRD: "A drafted plan opens in `DRAFT` `status` with
        `released_wafer_starts` 0, `committed_hours` 0.0, `surcharge_hours` 0.0
        and `commitment_tier` `TIER_0`."

        Design: Corner/calculations/tier_zero_plan_commits_with_a_zero_surcharge
        """
        env = build_line(fab, single_step_spec(commit_plan=False, lots=[]))
        assert_hours(env.flow["total_standard_hours"], 2.0, "total_standard_hours")
        assert_fields(env.plan, status="DRAFT", commitment_tier="TIER_0")
        assert_hours(env.plan["committed_hours"], 0.0, "committed_hours")

        committed = fab.commit_plan(env.plan["id"])

        # 10 starts times 2.0 hours is 20.00 base hours on a 100.0 budget.
        assert committed["commitment_tier"] == "TIER_0"
        assert_hours(committed["surcharge_hours"], 0.00, "surcharge_hours")
        assert_hours(committed["committed_hours"], 20.00, "committed_hours")
        assert committed["status"] == "COMMITTED"
        assert fab.read_plan(env.plan["id"])["released_wafer_starts"] == 0
