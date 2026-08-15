"""Forge run lifecycle: initial states, heat recording, reopen cycle,
trim-ticket gating, order cancellation cascade, and material accounting
(PRD §3.5, §2.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_forge_heat,
    cut_billets,
    factories,
    get_success_data,
    install_die,
    new_alloy,
    new_certified_heat,
    new_die_set,
    new_forge_run,
    new_furnace,
    new_invoice,
    new_ready_charge,
    new_ready_charges,
    new_surcharge_index,
    new_work_center,
    new_work_order,
    order_parts,
    record_heat,
    set_logical_clock,
    setup_production_ctx,
    start_run,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
SAW = TEST_USERS["saw_operator_headers"]
FURN = TEST_USERS["furnace_operator_headers"]
FORGE = TEST_USERS["forge_operator_headers"]
DIE = TEST_USERS["die_tech_headers"]
QE = TEST_USERS["quality_engineer_headers"]
SP = TEST_USERS["sales_planner_headers"]


class TestInitialStates:
    def test_initial_states_across_pipeline(self, api):
        """PRD §3.1: "A new lot starts in `RECEIVED` status with its
        `remaining_weight_lbs` equal to `received_weight_lbs`, and its measured
        chemistry fields `carbon_pct` and `manganese_pct` remain null until
        verification."
        PRD §3.2: "A fresh billet starts in `CUT` with its `charge_count` at
        zero, its `current_charge_id` null, and its `consumed_by_run_id` null."
        PRD §3.3: "The charge itself begins in `LOADING`, stamps
        `load_started_at` from the logical clock, and becomes the furnace's
        `active_charge_id`."
        PRD §3.4: "A new die set is `AVAILABLE` with `cumulative_hits` at zero
        and `resink_count` at zero, and the die roster can be filtered by
        `status` or by `installed_work_center_id`."
        PRD §3.5: "A newly created order stands in `RELEASED` status."
        PRD §3.5: "Successful scheduling leaves the run in `SCHEDULED` and
        increments the order's `version` by one."
        PRD §3.8: "A new invoice starts in `PROVISIONAL`."
        PRD §3.6: "The ticket, bound to its parent run via `forge_run_id`,
        starts in `DRAFT`."

        Design: Corner/state_machines/initial_states_across_pipeline
        """
        alloy = new_alloy()
        new_surcharge_index(alloy["id"])
        # A freshly registered heat lot starts in RECEIVED.
        heat_received = get_success_data(api.create_mill_heat(
            factories.mill_heat_payload(alloy["id"], "H-7101A"), PM))
        assert heat_received["status"] == "RECEIVED"
        heat = new_certified_heat(alloy["id"], "H-7101")
        billets = cut_billets(heat["id"], 20.0, 2)
        assert billets[0]["status"] == "CUT"
        furnace = new_furnace()
        resp = api.create_furnace_charge(
            factories.furnace_charge_payload(
                furnace["id"], [b["id"] for b in billets],
                "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            FURN,
        )
        charge = validate_success(resp, 201)
        assert charge["status"] == "LOADING"
        die = new_die_set("DIE-22")
        assert die["status"] == "AVAILABLE"
        wc = new_work_center("WC-1")
        install_die(die["id"], wc["id"])
        wo = new_work_order(alloy["id"], "WO-21", ordered_qty=2)
        assert wo["status"] == "RELEASED"
        run = new_forge_run(wo["id"], die["id"], planned_qty=2,
                            work_center_id=wc["id"])
        assert run["status"] == "SCHEDULED"
        invoice = new_invoice(wo["id"])
        assert invoice["status"] == "PROVISIONAL"
        # Drive the run to FORGED so a trim ticket can be opened.
        start_run(run["id"])
        get_success_data(api.close_charge_loading(charge["id"], FURN))
        set_logical_clock("2026-08-02T09:30:00Z")
        get_success_data(api.mark_charge_ready(charge["id"], FURN))
        record_heat(run["id"], charge["id"], [b["id"] for b in billets],
                    parts_good=2)
        get_success_data(api.finish_forging(run["id"], FORGE))
        ticket = get_success_data(api.create_trim_ticket(run["id"], FORGE))
        assert ticket["status"] == "DRAFT"


class TestForgeHeatShape:
    def test_forge_heat_has_no_version_field(self, api):
        """PRD §2.4: "One entity deviates from this convention: a recorded
        forge heat is an immutable event and carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from it."
        PRD §3.4: "Every recorded forge heat adds its `hits_added` — the heat's
        total part count, good plus scrapped, multiplied by the alloy's
        `strokes_per_part` — to the die's `cumulative_hits`."

        Two parts at 3 strokes per part give hits_added == 6.

        Design: Corner/entities/forge_heat_has_no_version_field
        """
        ctx = setup_production_ctx(qty=2, record_trim_ticket=False)
        forge_heat = ctx["forge_heat"]
        assert_forge_heat(forge_heat)
        assert forge_heat["hits_added"] == 6, (
            f"2 parts * 3 strokes per part = 6, got {forge_heat['hits_added']}"
        )


class TestRunTransitionGuards:
    def test_finish_forging_without_heats_rejected(self, api):
        """PRD §3.5: "Finishing forging moves a run from `IN_PROGRESS` to
        `FORGED` and requires at least one recorded heat, failing with
        `ERR_RUN_NO_HEATS` otherwise."

        Design: Corner/state_machines/finish_forging_without_heats_rejected
        """
        alloy = new_alloy()
        die = new_die_set("DIE-23")
        wc = new_work_center("WC-1")
        install_die(die["id"], wc["id"])
        wo = new_work_order(alloy["id"], "WO-22", ordered_qty=2)
        run = new_forge_run(wo["id"], die["id"], planned_qty=2,
                            work_center_id=wc["id"])
        start_run(run["id"])
        resp = api.finish_forging(run["id"], FORGE)
        validate_error(resp, ApiErrorId.ERR_RUN_NO_HEATS, 409)
        after = get_success_data(api.get_forge_run(run["id"], FORGE))
        assert after["status"] == "IN_PROGRESS"

    def test_reopen_blocked_while_trim_ticket_active(self, api):
        """PRD §3.5: "A `FORGED` run can be reopened for additional heats or a
        re-strike — back to `IN_PROGRESS` — but only while no trim ticket of
        the run sits in `DRAFT` or `FLAGGED`, else
        `ERR_TRIM_TICKET_ACTIVE_EXISTS`; this `FORGED` → `IN_PROGRESS` →
        `FORGED` loop is the reheat cycle, and each pass may consume new
        heats."

        Design: Corner/state_machines/reopen_blocked_while_trim_ticket_active
        """
        ctx = setup_production_ctx(qty=2, record_trim_ticket=False)
        run = ctx["run"]
        assert run["status"] == "FORGED"
        ticket = get_success_data(api.create_trim_ticket(run["id"], FORGE))
        assert ticket["status"] == "DRAFT"
        resp = api.reopen_forge_run(run["id"], FORGE)
        validate_error(resp, ApiErrorId.ERR_TRIM_TICKET_ACTIVE_EXISTS, 409)
        after = get_success_data(api.get_forge_run(run["id"], FORGE))
        assert after["status"] == "FORGED"

    def test_run_complete_blocked_while_parts_untrimmed(self, api):
        """PRD §3.5: "Completing a run requires at least one `ACCEPTED` trim
        ticket on the run and no part of the run remaining in `FORGED` (else
        `ERR_TRIM_PENDING`), moving it from `FORGED` to the terminal
        `COMPLETED`."

        With a DRAFT ticket open and both parts still FORGED, completion is
        refused with ERR_TRIM_PENDING.

        Design: Corner/state_machines/run_complete_blocked_while_parts_untrimmed
        """
        ctx = setup_production_ctx(qty=2, record_trim_ticket=False)
        run = ctx["run"]
        get_success_data(api.create_trim_ticket(run["id"], FORGE))
        resp = api.complete_forge_run(run["id"], FORGE)
        validate_error(resp, ApiErrorId.ERR_TRIM_PENDING, 409)
        after = get_success_data(api.get_forge_run(run["id"], FORGE))
        assert after["status"] == "FORGED"

    def test_scrap_consumed_billet_rejected(self, api):
        """PRD §3.2: "A `SawOperator` may scrap a billet in `CUT` or
        `DISCHARGED` by supplying a `reason`, moving it to the terminal
        `SCRAPPED` state — and scrapped weight does not return to the heat."

        A billet already CONSUMED by a forge heat is outside that set.

        Design: Corner/state_machines/scrap_consumed_billet_rejected
        """
        ctx = setup_production_ctx(qty=2, record_trim_ticket=False)
        billet = ctx["billets"][0]
        after_heat = get_success_data(api.get_billet(billet["id"], SAW))
        assert after_heat["status"] == "CONSUMED"
        resp = api.scrap_billet(billet["id"], {"reason": "too late"}, SAW)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_billet(billet["id"], SAW))
        assert after["status"] == "CONSUMED"

    def test_inspect_forged_part_rejected(self, api):
        """PRD §3.6: "A `QualityEngineer` inspects a `TRIMMED` part to move it
        to `INSPECTED`, and may scrap a part in `FORGED`, `TRIMMED`, or
        `INSPECTED` by supplying a `reason`, moving it to `SCRAPPED` and
        recomputing the order's `scrapped_qty`."

        A freshly FORGED part (no trim recorded yet) cannot be inspected.

        Design: Corner/state_machines/inspect_forged_part_rejected
        """
        ctx = setup_production_ctx(qty=2, record_trim_ticket=False)
        parts = order_parts(ctx["wo"]["id"])
        assert parts[0]["status"] == "FORGED"
        resp = api.inspect_part_serial(parts[0]["id"], QE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        after = get_success_data(api.get_part_serial(parts[0]["id"], QE))
        assert after["status"] == "FORGED"


class TestWorkOrderCancelCascade:
    def test_workorder_cancel_cascades_scheduled_runs(self, api):
        """PRD §3.5: "From `RELEASED` it proceeds unconditionally and cascades
        every `SCHEDULED` run of the order to `CANCELLED`."

        The cascade is conditional on ownership: the surviving order's run is
        untouched.

        Design: Corner/state_machines/workorder_cancel_cascades_scheduled_runs
        """
        alloy = new_alloy()
        die = new_die_set("DIE-31")
        wc = new_work_center("WC-1")
        wo_a = new_work_order(alloy["id"], "WO-30", ordered_qty=2)
        run_1 = new_forge_run(wo_a["id"], die["id"], "2026-08-03T09:00:00Z",
                              "2026-08-03T10:30:00Z", 2, work_center_id=wc["id"])
        wo_b = new_work_order(alloy["id"], "WO-31", ordered_qty=2)
        run_2 = new_forge_run(wo_b["id"], die["id"], "2026-08-03T11:00:00Z",
                              "2026-08-03T12:30:00Z", 2, work_center_id=wc["id"])
        cancelled = get_success_data(api.cancel_work_order(wo_a["id"], SP))
        assert cancelled["status"] == "CANCELLED"
        run_1_after = get_success_data(api.get_forge_run(run_1["id"], FORGE))
        assert run_1_after["status"] == "CANCELLED", (
            "cancelling the order must cascade to its SCHEDULED run"
        )
        run_2_after = get_success_data(api.get_forge_run(run_2["id"], FORGE))
        assert run_2_after["status"] == "SCHEDULED", (
            "the cascade touches only the cancelled order's runs"
        )


class TestRunStartDieGate:
    def test_run_start_requires_die_installed(self, api):
        """PRD §3.5: "Starting a run requires its order to be in `RELEASED`,
        `IN_PROGRESS`, `PRODUCED`, or `CERTIFIED`; the die set to be
        `INSTALLED` with its `installed_work_center_id` equal to the run's own
        work center (else `ERR_DIE_NOT_INSTALLED`); and the center to be `UP`
        (else `ERR_WORKCENTER_DOWN`)."

        Run creation is not gated on installation — the run schedules fine
        while the die is AVAILABLE; only the start is refused.

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_die_installed
        """
        alloy = new_alloy()
        die = new_die_set("DIE-17")
        wc = new_work_center("WC-1")
        wo = new_work_order(alloy["id"], "WO-14", ordered_qty=10)
        run = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                            "2026-08-03T10:30:00Z", 10, work_center_id=wc["id"])
        assert run["status"] == "SCHEDULED", "creation is not gated on install"
        resp = api.start_forge_run(run["id"], FORGE)
        validate_error(resp, ApiErrorId.ERR_DIE_NOT_INSTALLED, 409)
        after = get_success_data(api.get_forge_run(run["id"], FORGE))
        assert after["status"] == "SCHEDULED"

    def test_run_start_requires_die_on_its_own_center(self, api):
        """PRD §3.5: "Starting a run requires its order to be in `RELEASED`,
        `IN_PROGRESS`, `PRODUCED`, or `CERTIFIED`; the die set to be
        `INSTALLED` with its `installed_work_center_id` equal to the run's own
        work center (else `ERR_DIE_NOT_INSTALLED`); and the center to be `UP`
        (else `ERR_WORKCENTER_DOWN`)."

        A die INSTALLED on a different center than the run's own center fails
        the equality clause.

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_die_installed
        """
        alloy = new_alloy()
        die = new_die_set("DIE-17B")
        wc1 = new_work_center("WC-1")
        wc2 = new_work_center("WC-2")
        install_die(die["id"], wc2["id"])
        wo = new_work_order(alloy["id"], "WO-14B", ordered_qty=10)
        run = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                            "2026-08-03T10:30:00Z", 10, work_center_id=wc1["id"])
        resp = api.start_forge_run(run["id"], FORGE)
        validate_error(resp, ApiErrorId.ERR_DIE_NOT_INSTALLED, 409)


class TestReopenReheatCycle:
    def _setup_two_charge_run(self, api):
        """Six billets in two READY charges (4 + 2); run started (WO qty 6)."""
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-2101")
        billets = cut_billets(heat["id"], 20.0, 6)
        furnace = new_furnace()
        ids = [b["id"] for b in billets]
        charges = new_ready_charge_pair(api, furnace["id"], ids)
        die = new_die_set("DIE-14")
        wc = new_work_center("WC-1")
        install_die(die["id"], wc["id"])
        wo = new_work_order(alloy["id"], "WO-6", ordered_qty=6)
        run = new_forge_run(wo["id"], die["id"], "2026-08-03T09:00:00Z",
                            "2026-08-03T12:00:00Z", 6, work_center_id=wc["id"])
        start_run(run["id"])
        return {
            "alloy": alloy, "heat": heat, "billets": billets,
            "furnace": furnace, "charges": charges, "die": die, "wc": wc,
            "wo": wo, "run": run,
        }

    def test_forge_run_reopen_cycle_edges(self, api):
        """PRD §3.5: "A `FORGED` run can be reopened for additional heats or a
        re-strike — back to `IN_PROGRESS` — but only while no trim ticket of
        the run sits in `DRAFT` or `FLAGGED`, else
        `ERR_TRIM_TICKET_ACTIVE_EXISTS`; this `FORGED` → `IN_PROGRESS` →
        `FORGED` loop is the reheat cycle, and each pass may consume new
        heats."

        Design: Difficulty/non_linear_state_machine/forge_run_reopen_reheat_cycle
        """
        ctx = self._setup_two_charge_run(api)
        run_id = ctx["run"]["id"]
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(run_id, ctx["charges"][0]["id"], ids[:4], parts_good=4)
        forged = get_success_data(api.finish_forging(run_id, FORGE))
        assert forged["status"] == "FORGED"
        reopened = get_success_data(api.reopen_forge_run(run_id, FORGE))
        assert reopened["status"] == "IN_PROGRESS", (
            "the FORGED -> IN_PROGRESS cycle edge must be taken"
        )
        heat2 = record_heat(run_id, ctx["charges"][1]["id"], ids[4:],
                            parts_good=2)
        assert heat2["parts_good"] == 2, "reopened run must accept new heats"

    def test_forge_run_reopen_accumulates_part_totals(self, api):
        """PRD §3.5: "this `FORGED` → `IN_PROGRESS` → `FORGED` loop is the
        reheat cycle, and each pass may consume new heats."
        PRD §3.5: "The run's own tallies — `parts_good_total` and
        `parts_scrapped_total` summing the per-heat counts, and
        `input_weight_lbs` summing the `cut_weight_lbs` of the billets the run
        has consumed — grow accordingly."

        Design: Difficulty/non_linear_state_machine/forge_run_reopen_reheat_cycle
        """
        ctx = self._setup_two_charge_run(api)
        run_id = ctx["run"]["id"]
        ids = [b["id"] for b in ctx["billets"]]
        record_heat(run_id, ctx["charges"][0]["id"], ids[:4], parts_good=4)
        get_success_data(api.finish_forging(run_id, FORGE))
        get_success_data(api.reopen_forge_run(run_id, FORGE))
        record_heat(run_id, ctx["charges"][1]["id"], ids[4:], parts_good=2)
        final = get_success_data(api.finish_forging(run_id, FORGE))
        assert final["status"] == "FORGED"
        run_after = get_success_data(api.get_forge_run(run_id, FORGE))
        assert run_after["parts_good_total"] == 6, (
            f"part totals must accumulate across cycles: 4 + 2 = 6, got "
            f"{run_after['parts_good_total']}"
        )


def new_ready_charge_pair(api, furnace_id, billet_ids):
    """Two READY charges on one furnace: first four billets [08:00,12:00),
    remaining two [13:00,17:00)."""
    return new_ready_charges(
        furnace_id,
        [
            (billet_ids[:4], "2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z"),
            (billet_ids[4:], "2026-08-02T13:00:00Z", "2026-08-02T17:00:00Z"),
        ],
    )


class TestMaterialAccounting:
    def test_planned_material_is_forward_looking(self, api):
        """PRD §3.5: "The forward-looking `planned_billet_weight_lbs` is
        `ordered_qty` times `billet_weight_lbs`, used for feasibility review
        and blind to shop-floor reality; the chronological
        `consumed_billet_weight_lbs` sums the `cut_weight_lbs` of billets whose
        `consumed_by_run_id` references a run of this order, reflecting
        actuals only."
        PRD §3.5: "All four counters, along with `consumed_billet_weight_lbs`
        and `trimmed_net_lbs`, start at zero on a freshly released order."

        Ten parts at 50.00 lbs planned billet each plan 500.00 lbs before any
        shop-floor activity.

        Design: Difficulty/dual_variant_calc/workorder_planned_vs_consumed_material
        """
        alloy = new_alloy()
        wo = new_work_order(alloy["id"], "WO-2", ordered_qty=10)
        assert wo["planned_billet_weight_lbs"] == pytest.approx(500.00, abs=1e-9), (
            f"10 * 50.00 = 500.00, got {wo['planned_billet_weight_lbs']}"
        )
        assert wo["consumed_billet_weight_lbs"] == pytest.approx(0.0, abs=1e-9), (
            "a fresh order has consumed nothing"
        )

    def test_consumed_material_is_chronological_actual(self, api):
        """PRD §3.5: "The forward-looking `planned_billet_weight_lbs` is
        `ordered_qty` times `billet_weight_lbs`, used for feasibility review
        and blind to shop-floor reality; the chronological
        `consumed_billet_weight_lbs` sums the `cut_weight_lbs` of billets whose
        `consumed_by_run_id` references a run of this order, reflecting
        actuals only."

        After one heat consumes four 50.00-lb billets, the two sanctioned
        answers diverge on the same order at the same instant.

        Design: Difficulty/dual_variant_calc/workorder_planned_vs_consumed_material
        """
        alloy = new_alloy()
        heat = new_certified_heat(alloy["id"], "H-1101")
        billets = cut_billets(heat["id"], 20.0, 4)
        furnace = new_furnace()
        charge = new_ready_charge(furnace["id"], [b["id"] for b in billets])
        die = new_die_set("DIE-11")
        wc = new_work_center("WC-1")
        install_die(die["id"], wc["id"])
        wo = new_work_order(alloy["id"], "WO-2", ordered_qty=10)
        run = new_forge_run(wo["id"], die["id"], planned_qty=4,
                            work_center_id=wc["id"])
        start_run(run["id"])
        record_heat(run["id"], charge["id"], [b["id"] for b in billets],
                    parts_good=4)
        after = get_success_data(api.get_work_order(wo["id"], SP))
        assert after["planned_billet_weight_lbs"] == pytest.approx(500.00, abs=1e-9), (
            f"planned stays forward-looking at 500.00, got "
            f"{after['planned_billet_weight_lbs']}"
        )
        assert after["consumed_billet_weight_lbs"] == pytest.approx(200.00, abs=1e-9), (
            f"4 * 50.00 = 200.00 consumed, got {after['consumed_billet_weight_lbs']}"
        )
        assert after["planned_billet_weight_lbs"] != after["consumed_billet_weight_lbs"]
