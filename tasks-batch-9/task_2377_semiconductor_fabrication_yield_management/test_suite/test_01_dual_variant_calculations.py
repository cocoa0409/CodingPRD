"""Calculations that exist in two variants over one identical population.

Each scenario builds a single line, then reads the same quantity twice: once
under the narrow variant and once under the wide one, and pins the gap between
them.
"""

from test_helpers import (
    ChamberSpec,
    EquipmentSpec,
    LotSpec,
    USER_QUALITY_MANAGER,
    build_line,
    complete_step,
    raise_spc_excursion,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_days,
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_ratio,
)


# --------------------------------------------------------------------------
# Excursion severity: PROVISIONAL at creation, FINAL at containment
# --------------------------------------------------------------------------


def _etch_excursion_line(fab):
    """Two lots reach the etch step; the second one's reading sits on the UCL."""
    env = build_line(fab, two_recipe_line_spec(cycle_time_target_days=1.0))
    # LOT-002 passes through the etch step dead on target and tracks out, so
    # its run there is COMPLETED rather than OPEN.
    complete_step(fab, env, step_ix=0, lot_ix=1)
    complete_step(fab, env, step_ix=1, lot_ix=1, measured_value=100.0)
    # LOT-001 arrives at the same step and its reading lands exactly on the UCL.
    complete_step(fab, env, step_ix=0, lot_ix=0)
    raised = raise_spc_excursion(fab, env, 106.0, step_ix=1, lot_ix=0)
    env.raised = raised
    return env


class TestExcursionSeverityVariants:
    def test_provisional_severity_counts_only_material_in_the_tool(self, fab):
        """A newly opened SPC excursion scores over the open-run population only.

        PRD: "Under the `PROVISIONAL` variant, set at creation before any human
        has looked at the excursion, the set is the narrow "what is in the tool
        right now" population: for an `SPC` excursion, lots with an `OPEN` run
        on the chart's `step_id` whose `flow_state` is `RELEASED` or
        `IN_PROCESS`; for a `PARTICLE` excursion, lots with an `OPEN` run on the
        excursion's `chamber_id` whose `flow_state` is `RELEASED` or
        `IN_PROCESS`; for a `DIE_SORT` excursion, exactly one — the sort run's
        own lot."

        Design: Difficulty/dual_variant_calc/excursion_severity_provisional_widens_to_final_and_flips_band
        """
        env = _etch_excursion_line(fab)
        measurement = env.raised["measurement"]
        excursion = env.raised["excursion"]

        assert measurement["classification"] == "OUT_OF_CONTROL"
        assert_ratio(measurement["deviation_sigma"], 3.0, "deviation_sigma")
        assert excursion is not None, "an out-of-control reading must open an excursion"

        # 60.0 * (6/10) deviation + 3.0 * 1 lot + no out-of-spec penalty.
        assert_fields(
            excursion,
            source_type="SPC",
            status="OPEN",
            severity_variant="PROVISIONAL",
            affected_lot_count=1,
            severity_band="LOW",
        )
        assert_hours(excursion["severity_score"], 39.00, "severity_score")
        assert_ratio(excursion["trigger_value"], 106.0, "trigger_value")

    def test_containment_widens_the_lot_set_and_flips_the_band(self, fab):
        """Finalisation re-scores over exposed material and pushes LOW to MEDIUM.

        PRD: "On identical data the `FINAL` set is therefore never smaller than
        the `PROVISIONAL` one, which is why finalisation can push
        `severity_band` up a band."

        Design: Difficulty/dual_variant_calc/excursion_severity_provisional_widens_to_final_and_flips_band
        """
        env = _etch_excursion_line(fab)
        excursion_id = env.raised["excursion"]["id"]
        provisional = env.raised["excursion"]

        contained = fab.contain(excursion_id, "SPC_CHART", user_id=USER_QUALITY_MANAGER)

        # The completed LOT-002 run on the same step now counts too: 36 + 3*2.
        assert_fields(
            contained,
            severity_variant="FINAL",
            affected_lot_count=2,
            severity_band="MEDIUM",
            status="CONTAINED",
            containment_scope="SPC_CHART",
            contained_by_user_id=USER_QUALITY_MANAGER,
        )
        assert_hours(contained["severity_score"], 42.00, "severity_score")
        assert contained["affected_lot_count"] > provisional["affected_lot_count"]
        assert contained["severity_band"] != provisional["severity_band"]

        # The SPC_CHART cascade freezes the chart and holds the open-run lot.
        chart = fab.read_chart(env.charts[0]["id"])
        assert_fields(chart, status="SUSPENDED", violation_count=1)
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="SPC_HOLD")
        assert_lot_state(fab.read_lot(env.lots[1]["id"]), hold_state="NONE")


# --------------------------------------------------------------------------
# Cycle time: forward projection vs pinned chronological actual
# --------------------------------------------------------------------------


def _lot_one_step_in(fab):
    """A single released lot that has tracked out of step 10 only."""
    env = build_line(
        fab,
        two_recipe_line_spec(
            cycle_time_target_days=1.0, lots=[LotSpec("LOT-001", 3, "STANDARD")]
        ),
    )
    complete_step(fab, env, step_ix=0, lot_ix=0)
    return env


class TestCycleTimeVariants:
    def test_projection_adds_a_modelled_queued_remainder_to_elapsed_time(self, fab):
        """The forward projection prices the unfinished steps at a queue factor.

        PRD: "`projected_remaining_days` is `remaining_standard_hours`
        multiplied by `queue_factor`, divided by 24, rounded to 3 decimal
        places."

        Design: Difficulty/dual_variant_calc/lot_cycle_time_projection_vs_chronological_actual
        """
        env = _lot_one_step_in(fab)
        fab.set_clock("2026-08-02T00:00:00Z")

        projection = fab.cycle_time_projection(env.lots[0]["id"])

        # 3.0 + 2.0 hours remain; STANDARD queues at 1.60; 5 * 1.6 / 24.
        assert_hours(projection["remaining_standard_hours"], 5.00, "remaining_standard_hours")
        assert float(projection["queue_factor"]) == 1.60
        assert_days(projection["projected_remaining_days"], 0.333, "projected_remaining_days")
        assert_days(projection["elapsed_days"], 1.000, "elapsed_days")
        assert_days(projection["projected_cycle_time_days"], 1.333, "projected_cycle_time_days")
        assert projection["cycle_time_status"] == "AT_RISK"

    def test_actual_cycle_time_ignores_the_queue_factor_entirely(self, fab):
        """The pinned chronological value differs from the projection by the remainder.

        PRD: "It uses no queue factor and no step data at all, and for the same
        lot at the same instant it differs from the projection by exactly
        `projected_remaining_days`."

        Design: Difficulty/dual_variant_calc/lot_cycle_time_projection_vs_chronological_actual
        """
        env = _lot_one_step_in(fab)
        fab.set_clock("2026-08-02T00:00:00Z")
        projection = fab.cycle_time_projection(env.lots[0]["id"])

        complete_step(fab, env, step_ix=1, lot_ix=0, measured_value=100.0)
        complete_step(fab, env, step_ix=2, lot_ix=0)
        sort_run = fab.die_sort(
            env.lots[0]["id"],
            [
                {"wafer_slot": 1, "tested_die": 100, "good_die": 90,
                 "edge_ring_fails": 7, "center_cluster_fails": 1,
                 "scratch_line_fails": 0, "parametric_shift_fails": 2},
                {"wafer_slot": 2, "tested_die": 10, "good_die": 8,
                 "edge_ring_fails": 2, "center_cluster_fails": 0,
                 "scratch_line_fails": 0, "parametric_shift_fails": 0},
                {"wafer_slot": 3, "tested_die": 50, "good_die": 47,
                 "edge_ring_fails": 2, "center_cluster_fails": 1,
                 "scratch_line_fails": 0, "parametric_shift_fails": 0},
            ],
        )
        fab.bin_sort_run(sort_run["id"], 50, 60)

        lot = fab.read_lot(env.lots[0]["id"])
        assert_lot_state(lot, flow_state="COMPLETED")
        assert_days(lot["actual_cycle_time_days"], 1.000, "actual_cycle_time_days")

        projected = float(projection["projected_cycle_time_days"])
        actual = float(lot["actual_cycle_time_days"])
        assert projected != actual, "the two variants must disagree"
        assert_days(
            round(projected - actual, 3),
            float(projection["projected_remaining_days"]),
            "projection minus actual",
        )


# --------------------------------------------------------------------------
# Dispatch score: STANDARD_QUEUE vs SUPER_HOT_WAIVER
# --------------------------------------------------------------------------


def _two_etch_tool_line(fab):
    """Two eligible etch chambers whose penalties trade off against each other."""
    spec = two_recipe_line_spec(
        equipments=[
            EquipmentSpec("LITHO-1", "LITHO", 168.0, 24.0, 0.0),
            EquipmentSpec("ETCH-A", "ETCH", 168.0, 24.0, 140.0),
            EquipmentSpec("ETCH-B", "ETCH", 168.0, 24.0, 0.0),
        ],
        chambers=[
            ChamberSpec("CH_L1", equipment_ix=0, recipe_ix=0),
            ChamberSpec("CH_E_A", equipment_ix=1, recipe_ix=1),
            ChamberSpec("CH_E_B", equipment_ix=2, recipe_ix=1),
        ],
        lots=[],
    )
    env = build_line(fab, spec)

    # CH_E_A is clean but its tool is close to maintenance; CH_E_B is the
    # mirror image, carrying a sub-limit particle load on a freshly PM'd tool.
    env.chambers[2] = fab.particle_reading(env.chambers[2]["id"], 24.0)

    # Every chamber now has exactly 80 of its 100 qualification days left.
    fab.set_clock("2026-08-21T00:00:00Z")

    lot_std = fab.release_lot(
        fab.lot(env.plan["id"], env.flow["id"], "LOT-001", 3, "STANDARD")["id"],
        env.plan["id"],
    )
    lot_sh = fab.release_lot(
        fab.lot(env.plan["id"], env.flow["id"], "LOT-002", 3, "SUPER_HOT")["id"],
        env.plan["id"],
    )
    env.lots = [lot_std, lot_sh]
    env.lot = lot_std
    complete_step(fab, env, step_ix=0, lot_ix=0)
    complete_step(fab, env, step_ix=0, lot_ix=1)
    return env


class TestDispatchScoreVariants:
    def test_standard_lot_pays_the_maintenance_proximity_penalty(self, fab):
        """A STANDARD lot is dispatched away from the tool that is due for PM.

        PRD: "The **maintenance-proximity penalty** is 20.0 multiplied by the
        smaller of 1.0 and the tool's `hours_since_pm` divided by its
        `pm_interval_hours` — except that for a lot whose `priority_class` is
        `SUPER_HOT` this penalty is forced to zero, so a super-hot lot ignores
        maintenance proximity entirely and can win a different chamber than a
        `STANDARD` or `HOT` lot would from exactly the same chamber
        population."

        Design: Difficulty/dual_variant_calc/chamber_dispatch_super_hot_waiver_flips_winning_chamber
        """
        env = _two_etch_tool_line(fab)
        operator_id = env.operators[0]["id"]

        run = fab.track_in(env.lots[0]["id"], env.steps[1]["id"], operator_id)

        # CH_E_A: 100 - 8.00 qual decay - 0 particles - 16.67 PM = 75.33.
        # CH_E_B: 100 - 8.00 qual decay - 12.00 particles - 0 PM = 80.00.
        assert run["chamber_id"] == env.chambers[2]["id"]
        assert_hours(run["dispatch_score"], 80.00, "dispatch_score")

    def test_super_hot_waiver_flips_the_winning_chamber(self, fab):
        """Zeroing the PM term alone hands the same population a different winner.

        PRD: "Candidates are ordered by score descending, and ties are broken by
        ascending `chamber_code`."

        Design: Difficulty/dual_variant_calc/chamber_dispatch_super_hot_waiver_flips_winning_chamber
        """
        env = _two_etch_tool_line(fab)
        operator_id = env.operators[0]["id"]
        etch_step = env.steps[1]["id"]

        standard_run = fab.track_in(env.lots[0]["id"], etch_step, operator_id)
        fab.measure(standard_run["id"], env.charts[0]["id"], 100.0, operator_id)
        fab.track_out(standard_run["id"], operator_id)

        super_hot_run = fab.track_in(env.lots[1]["id"], etch_step, operator_id)

        assert standard_run["chamber_id"] == env.chambers[2]["id"]
        assert_hours(standard_run["dispatch_score"], 80.00, "dispatch_score")
        assert super_hot_run["chamber_id"] == env.chambers[1]["id"]
        assert_hours(super_hot_run["dispatch_score"], 92.00, "dispatch_score")
        assert standard_run["chamber_id"] != super_hot_run["chamber_id"]

        # Neither variant moved the underlying tool ledgers.
        assert_hours(
            fab.read_equipment(env.equipments[1]["id"])["hours_since_pm"], 140.0,
            "hours_since_pm",
        )
        assert_hours(
            fab.read_equipment(env.equipments[2]["id"])["hours_since_pm"], 0.0,
            "hours_since_pm",
        )
        assert fab.read_chamber(env.chambers[1]["id"])["occupancy_state"] == "OCCUPIED"
        assert fab.read_chamber(env.chambers[2]["id"])["occupancy_state"] == "FREE"
