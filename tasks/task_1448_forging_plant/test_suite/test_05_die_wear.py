"""Die wear accumulation, the WORN boundary, the resink cycle, the die-worn
run cascade, and validation ordering between state and safety (PRD §3.4,
§2.10)."""
from test_helpers import (
    ApiErrorId,
    cut_billets,
    factories,
    get_success_data,
    install_die,
    new_alloy,
    new_certified_heat,
    new_die_set,
    new_forge_run,
    new_furnace,
    new_ready_charges,
    new_work_center,
    new_work_order,
    record_heat,
    start_run,
    validate_error,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
FURN = TEST_USERS["furnace_operator_headers"]
FORGE = TEST_USERS["forge_operator_headers"]
DIE = TEST_USERS["die_tech_headers"]
QE = TEST_USERS["quality_engineer_headers"]
SP = TEST_USERS["sales_planner_headers"]


def _setup_wear_scenario(api, wear_limit=30, max_resinks=1, extra_billet=False):
    """Ten billets in two READY charges (9 + 1) and a die with the given wear
    budget installed on WC-1; one order with a started run (op-1).

    When extra_billet is set, an eleventh billet sits READY in a third charge
    so a heat can be attempted on a second (cancelled) run.
    """
    alloy = new_alloy()
    heat = new_certified_heat(alloy["id"], "H-5001")
    n = 11 if extra_billet else 10
    billets = cut_billets(heat["id"], 20.0, n)
    furnace = new_furnace()
    ids = [b["id"] for b in billets]
    specs = [
        (ids[:9], "2026-08-02T08:00:00Z", "2026-08-02T11:00:00Z"),
        (ids[9:10], "2026-08-02T12:00:00Z", "2026-08-02T15:00:00Z"),
    ]
    if extra_billet:
        specs.append((ids[10:], "2026-08-02T16:00:00Z", "2026-08-02T18:00:00Z"))
    charges = new_ready_charges(furnace["id"], specs)
    die = new_die_set("DIE-W32", wear_limit, max_resinks)
    wc = new_work_center("WC-1", "PRESS", 500)
    install_die(die["id"], wc["id"])
    wo = new_work_order(alloy["id"], "WO-12", ordered_qty=10)
    run = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                        "2026-08-03T10:30:00Z", 10, work_center_id=wc["id"])
    start_run(run["id"])
    return {
        "alloy": alloy, "heat": heat, "billets": billets, "furnace": furnace,
        "charges": charges, "die": die, "wc": wc, "wo": wo, "run": run,
    }


def _setup_cascade_scenario(api):
    """Run A started on DIE-W31/WC-1 (09:00-10:30); run B SCHEDULED on the same
    die + center at 11:00-12:30 (exactly the 30-minute turnaround)."""
    ctx = _setup_wear_scenario(api, wear_limit=30, max_resinks=1)
    wo_b = new_work_order(ctx["alloy"]["id"], "WO-9", ordered_qty=10)
    run_b = new_forge_run(wo_b["id"], ctx["die"]["id"], "2026-08-03T11:00:00Z",
                          "2026-08-03T12:30:00Z", 10,
                          work_center_id=ctx["wc"]["id"])
    ctx["wo_b"] = wo_b
    ctx["run_b"] = run_b
    return ctx


class TestDieWearBoundary:
    def test_die_hits_below_wear_limit_stays_installed(self, api):
        """PRD §3.4: "The moment `cumulative_hits` reaches or exceeds
        `wear_limit_hits`, the boundary included, the die turns `WORN`, is
        automatically uninstalled with its `installed_work_center_id` cleared,
        and every forge run still `SCHEDULED` that references the die is
        cancelled, freeing those work-center windows."
        PRD §3.4: "Every recorded forge heat adds its `hits_added` — the heat's
        total part count, good plus scrapped, multiplied by the alloy's
        `strokes_per_part` — to the die's `cumulative_hits`."

        Nine parts at 3 strokes per part give 27 hits, one short of 30.

        Design: Difficulty/boundary_precision_check/die_hits_exactly_at_wear_limit
        """
        ctx = _setup_wear_scenario(api)
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        die = get_success_data(api.get_die_set(ctx["die"]["id"], DIE))
        assert die["cumulative_hits"] == 27, (
            f"9 parts * 3 strokes = 27, got {die['cumulative_hits']}"
        )
        assert die["status"] == "INSTALLED", (
            f"27 < wear limit 30 must leave the die INSTALLED, got {die['status']}"
        )
        assert die["installed_work_center_id"] == ctx["wc"]["id"]

    def test_die_hits_exactly_at_wear_limit_turns_worn(self, api):
        """PRD §3.4: "The moment `cumulative_hits` reaches or exceeds
        `wear_limit_hits`, the boundary included, the die turns `WORN`, is
        automatically uninstalled with its `installed_work_center_id` cleared,
        and every forge run still `SCHEDULED` that references the die is
        cancelled, freeing those work-center windows."

        The tenth part lands cumulative_hits exactly on the limit of 30.

        Design: Difficulty/boundary_precision_check/die_hits_exactly_at_wear_limit
        """
        ctx = _setup_wear_scenario(api)
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:],
                    parts_good=1)
        die = get_success_data(api.get_die_set(ctx["die"]["id"], DIE))
        assert die["cumulative_hits"] == 30, (
            f"10 parts * 3 strokes = 30, got {die['cumulative_hits']}"
        )
        assert die["status"] == "WORN", (
            f"cumulative_hits == wear_limit_hits must flip the die to WORN, "
            f"got {die['status']}"
        )
        assert die["installed_work_center_id"] is None, (
            "crossing the wear limit must auto-uninstall the die"
        )


class TestDieResinkCycle:
    def test_die_wear_resink_cycle_completes(self, api):
        """PRD §3.4: "Resinking is the die's second life, within budget:
        starting a resink on a `WORN` die requires `resink_count` still below
        `max_resinks` (otherwise `ERR_DIE_RESINK_LIMIT`) and moves the die to
        `RESINKING`; completing the resink returns it to `AVAILABLE` with
        `cumulative_hits` reset to zero and `resink_count` incremented by one."

        Design: Difficulty/non_linear_state_machine/die_set_wear_resink_cycle
        """
        ctx = _setup_wear_scenario(api)
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:],
                    parts_good=1)
        resinking = get_success_data(api.start_die_resink(ctx["die"]["id"], DIE))
        assert resinking["status"] == "RESINKING"
        completed = get_success_data(api.complete_die_resink(ctx["die"]["id"], DIE))
        assert completed["status"] == "AVAILABLE", (
            f"complete-resink returns the die to AVAILABLE, got {completed['status']}"
        )
        assert completed["cumulative_hits"] == 0, "resink resets cumulative_hits"
        assert completed["resink_count"] == 1, (
            f"resink_count increments by one, got {completed['resink_count']}"
        )

    def test_die_reinstall_after_resink(self, api):
        """PRD §3.4: "Resinking is the die's second life, within budget:
        starting a resink on a `WORN` die requires `resink_count` still below
        `max_resinks` (otherwise `ERR_DIE_RESINK_LIMIT`) and moves the die to
        `RESINKING`; completing the resink returns it to `AVAILABLE` with
        `cumulative_hits` reset to zero and `resink_count` incremented by one."
        PRD §3.4: "Installing an `AVAILABLE` die on a work center requires the
        center to be `UP` (`ERR_WORKCENTER_DOWN`) and no other die set already
        `INSTALLED` there (`ERR_WORKCENTER_HAS_DIE`); success moves the die to
        `INSTALLED` and records the `installed_work_center_id`."

        The full loop AVAILABLE -> INSTALLED -> WORN -> RESINKING -> AVAILABLE
        -> INSTALLED leaves the die usable again.

        Design: Difficulty/non_linear_state_machine/die_set_wear_resink_cycle
        """
        ctx = _setup_wear_scenario(api)
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:],
                    parts_good=1)
        get_success_data(api.start_die_resink(ctx["die"]["id"], DIE))
        get_success_data(api.complete_die_resink(ctx["die"]["id"], DIE))
        reinstalled = install_die(ctx["die"]["id"], ctx["wc"]["id"])
        assert reinstalled["status"] == "INSTALLED"
        assert reinstalled["installed_work_center_id"] == ctx["wc"]["id"]


class TestDieWornCascade:
    def test_die_worn_cascade_cancels_scheduled_run(self, api):
        """PRD §3.4: "The moment `cumulative_hits` reaches or exceeds
        `wear_limit_hits`, the boundary included, the die turns `WORN`, is
        automatically uninstalled with its `installed_work_center_id` cleared,
        and every forge run still `SCHEDULED` that references the die is
        cancelled, freeing those work-center windows."

        The heat on run A tips the die; the SCHEDULED run B is cancelled by
        the die mutation, not by the heat request directly.

        Design: Difficulty/transitive_cascade/heat_record_die_wear_cancels_scheduled_runs
        """
        ctx = _setup_cascade_scenario(api)
        assert ctx["run_b"]["status"] == "SCHEDULED"
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:],
                    parts_good=1)
        die = get_success_data(api.get_die_set(ctx["die"]["id"], DIE))
        assert die["status"] == "WORN"
        assert die["cumulative_hits"] == 30
        assert die["installed_work_center_id"] is None
        run_b_after = get_success_data(api.get_forge_run(ctx["run_b"]["id"], FORGE))
        assert run_b_after["status"] == "CANCELLED", (
            f"SCHEDULED run referencing the WORN die must be cancelled, got "
            f"{run_b_after['status']}"
        )
        run_a_after = get_success_data(api.get_forge_run(ctx["run"]["id"], FORGE))
        assert run_a_after["status"] == "IN_PROGRESS", (
            "the in-progress run that wore the die is unaffected"
        )

    def test_die_worn_cascade_frees_workcenter_window(self, api):
        """PRD §3.4: "The moment `cumulative_hits` reaches or exceeds
        `wear_limit_hits`, the boundary included, the die turns `WORN`, is
        automatically uninstalled with its `installed_work_center_id` cleared,
        and every forge run still `SCHEDULED` that references the die is
        cancelled, freeing those work-center windows."

        After the cascade, run B's old window [11:00,12:30] accepts a new run
        on a fresh die.

        Design: Difficulty/transitive_cascade/heat_record_die_wear_cancels_scheduled_runs
        """
        ctx = _setup_cascade_scenario(api)
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:],
                    parts_good=1)
        die_new = new_die_set("DIE-FRESH")
        install_die(die_new["id"], ctx["wc"]["id"])
        wo_c = new_work_order(ctx["alloy"]["id"], "WO-9C", ordered_qty=10)
        run_c = new_forge_run(wo_c["id"], die_new["id"], "2026-08-03T11:00:00Z",
                              "2026-08-03T12:30:00Z", 10,
                              work_center_id=ctx["wc"]["id"])
        assert run_c["status"] == "SCHEDULED", (
            "the cancelled run's window must be reusable"
        )


class TestStateBeatsDieWorn:
    def test_start_cancelled_run_beats_die_worn(self, api):
        """PRD §2.10: "Every request passes through an ordered gauntlet and
        fails at the first violated tier:" — with "6. Source-state validity
        for the requested transition (`ERR_INVALID_STATE_TRANSITION`, alongside
        the dedicated state-flavored codes `ERR_CHARGE_NOT_READY`,
        `ERR_PART_NOT_INSPECTED`, and `ERR_RUN_NO_HEATS`)." preceding "7.
        Business-safety limits: the forge-temperature window, the re-heat
        ceiling, cert chemistry, the worn-die guard, trim mass balance,
        part-count accounting, and grain-flow acceptability."

        Run B is CANCELLED (die-worn cascade) and its die is WORN; starting it
        fails on the state tier.

        Design: Difficulty/priority_pair_validation_conflict/run_start_state_beats_die_worn
        """
        ctx = _setup_cascade_scenario(api)
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:],
                    parts_good=1)
        die = get_success_data(api.get_die_set(ctx["die"]["id"], DIE))
        assert die["status"] == "WORN"
        run_b = get_success_data(api.get_forge_run(ctx["run_b"]["id"], FORGE))
        assert run_b["status"] == "CANCELLED"
        resp = api.start_forge_run(ctx["run_b"]["id"], FORGE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_heat_record_on_cancelled_run_beats_die_worn(self, api):
        """PRD §2.10: "Every request passes through an ordered gauntlet and
        fails at the first violated tier:" — with "6. Source-state validity
        for the requested transition (`ERR_INVALID_STATE_TRANSITION`, alongside
        the dedicated state-flavored codes `ERR_CHARGE_NOT_READY`,
        `ERR_PART_NOT_INSPECTED`, and `ERR_RUN_NO_HEATS`)." preceding "7.
        Business-safety limits: the forge-temperature window, the re-heat
        ceiling, cert chemistry, the worn-die guard, trim mass balance,
        part-count accounting, and grain-flow acceptability."
        PRD §3.4: "Recording a heat on a run whose die is already `WORN` is
        forbidden outright and rejected with `ERR_DIE_WORN`."

        Recording a heat on the CANCELLED run B (whose die is WORN) fails on
        the state tier before the worn-die guard is examined.

        Design: Difficulty/priority_pair_validation_conflict/run_start_state_beats_die_worn
        """
        ctx = _setup_wear_scenario(api, wear_limit=30, max_resinks=1,
                                   extra_billet=True)
        wo_b = new_work_order(ctx["alloy"]["id"], "WO-11", ordered_qty=10)
        run_b = new_forge_run(wo_b["id"], ctx["die"]["id"],
                              "2026-08-03T11:00:00Z", "2026-08-03T12:30:00Z",
                              10, work_center_id=ctx["wc"]["id"])
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(ctx["run"]["id"], ctx["charges"][0]["id"], ids[:9],
                    parts_good=9)
        record_heat(ctx["run"]["id"], ctx["charges"][1]["id"], ids[9:10],
                    parts_good=1)
        run_b_after = get_success_data(api.get_forge_run(run_b["id"], FORGE))
        assert run_b_after["status"] == "CANCELLED"
        die = get_success_data(api.get_die_set(ctx["die"]["id"], DIE))
        assert die["status"] == "WORN"
        resp = api.record_forge_heat(
            run_b["id"],
            factories.forge_heat_payload(ctx["charges"][2]["id"], ids[10:],
                                         parts_good=1),
            FORGE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
