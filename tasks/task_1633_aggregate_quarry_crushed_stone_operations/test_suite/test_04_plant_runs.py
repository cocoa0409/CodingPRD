"""Plant runs: circuit yield, balance gates, cooldown, voids, and the
muckpile's design-vs-reconciled tonnage variants."""
import pytest

from test_helpers import (
    OPERATOR,
    ApiErrorId,
    complete_ticket,
    create_agreement,
    create_certified_scale,
    create_completed_run,
    create_confirmed_order,
    create_run,
    create_spec,
    create_stockpile,
    create_zone,
    get_muckpile,
    get_run,
    get_stockpile,
    run_output,
    set_clock,
    setup_plant_run_site,
    start_run,
    validate_error,
    validate_success,
)


def _setup_dual_pile(api):
    """Blast site + COARSE pile A + FINE pile B + certified belt scale."""
    ctx = setup_plant_run_site()
    spec_b = create_spec(spec_code="FINE-1", category="FINE",
                         gradation_bands=[{"sieve": "No4", "min_pct": 90,
                                           "max_pct": 100}],
                         base_price_per_ton=9.00)
    pile_b = create_stockpile(ctx["site"]["id"], spec_b["id"])
    ctx.update({"spec_b": spec_b, "pile_b": pile_b})
    return ctx


def _complete_dual_output_run(ctx, input_tons=1000.0, tons_a=620.0,
                              tons_b=350.0):
    outputs = [
        run_output(ctx["pile"]["id"], ctx["spec"]["id"], tons_a),
        run_output(ctx["pile_b"]["id"], ctx["spec_b"]["id"], tons_b),
    ]
    return create_completed_run(ctx, input_tons, outputs)


class TestDesignVsReconciledTonnage:
    def test_muckpile_design_vs_reconciled_divergence(self, api):
        """PRD 3.3: "The design estimate and the belt-measured actuals
        legitimately diverge: one is geometric, the other is measured
        through dilution and recovery."
        PRD 3.3: "that volume times the in-situ density of 1.6 tons per
        cubic yard gives `estimated_tons`, rounded half-up to one decimal
        place."

        Design: Difficulty/dual_variant_calc/muckpile_design_vs_reconciled_tonnage
        """
        ctx = _setup_dual_pile(api)
        _complete_dual_output_run(ctx)
        mp = get_muckpile(ctx["muckpile"]["id"])
        # Design variant: 20*8*10*40/27 yd3 x 1.6 -> 3792.6 (1 dp).
        assert mp["estimated_tons"] == pytest.approx(3792.6, abs=1e-6)
        # Reconciled variant: belt-measured run input.
        assert mp["actual_fed_tons"] == pytest.approx(1000.0, abs=1e-6)
        assert mp["remaining_tons"] == pytest.approx(2792.6, abs=1e-6)
        assert mp["status"] == "OPEN"
        # The two variants diverge for identical blast data.
        assert mp["estimated_tons"] != mp["actual_fed_tons"]

    def test_muckpile_powder_factor_from_actual_load(self, api):
        """PRD 3.3: "The `powder_factor` — pounds of explosive per estimated
        ton, rounded half-up to two decimals — is computed against the
        design load of `hole_count` times `explosive_per_hole_lbs` until an
        actual load is reported, and against `loaded_explosive_lbs`
        thereafter."

        Design: Difficulty/dual_variant_calc/muckpile_design_vs_reconciled_tonnage
        """
        ctx = _setup_dual_pile(api)
        _complete_dual_output_run(ctx)
        plan = validate_success(
            api.get_shot_plan(ctx["plan"]["id"], OPERATOR))
        # loaded_explosive_lbs 1000 / estimated_tons 3792.6 -> 0.26 (2 dp).
        assert plan["powder_factor"] == pytest.approx(0.26, abs=1e-6)
        mp = get_muckpile(ctx["muckpile"]["id"])
        assert mp["status"] == "OPEN"


class TestYieldAndBalance:
    def test_yield_summary_variance_values(self, api):
        """PRD 3.5: "For every output row, the measured share is one hundred
        times the row's `tons` divided by `input_tons`, rounded half-up to
        one decimal, recorded as `measured_pct`. ... on the `PRIMARY`
        circuit the design is 65.0 for `COARSE`, 35.0 for `FINE`, and 50.0
        for `RIPRAP` ... The deviation `variance_pts` is the measured share
        minus the design share, rounded half-up to one decimal."
        PRD 3.5: "The balance gate requires the absolute difference between
        the summed output tonnage and `input_tons` to be at most three
        percent of `input_tons`, with exactly three percent passing
        (`ERR_OUTPUT_IMBALANCE`, 422)."

        Design: Corner/calculations/yield_summary_variance_values
        """
        ctx = _setup_dual_pile(api)
        run = _complete_dual_output_run(ctx)
        summary = run["yield_summary"]
        assert summary["A57"]["measured_pct"] == pytest.approx(62.0,
                                                               abs=1e-6)
        assert summary["A57"]["design_pct"] == pytest.approx(65.0, abs=1e-6)
        assert summary["A57"]["variance_pts"] == pytest.approx(-3.0,
                                                               abs=1e-6)
        assert summary["FINE-1"]["measured_pct"] == pytest.approx(35.0,
                                                                  abs=1e-6)
        assert summary["FINE-1"]["design_pct"] == pytest.approx(35.0,
                                                                abs=1e-6)
        assert summary["FINE-1"]["variance_pts"] == pytest.approx(0.0,
                                                                  abs=1e-6)
        # |620+350 - 1000| / 1000 == 3.0% passes the inclusive tolerance.
        assert run["production_status"] == "COMPLETED"

    def test_run_complete_imbalance_over_tolerance_rejected(self, api):
        """PRD 3.5: "The balance gate requires the absolute difference
        between the summed output tonnage and `input_tons` to be at most
        three percent of `input_tons`, with exactly three percent passing
        (`ERR_OUTPUT_IMBALANCE`, 422)."

        Design: Corner/calculations/run_complete_imbalance_over_tolerance_rejected
        """
        ctx = setup_plant_run_site()
        run = create_run(ctx)
        start_run(run["id"])
        outputs = [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 969.0)]
        # |969 - 1000| / 1000 == 3.1% > 3.0%.
        resp = api.complete_plant_run(run["id"],
                                      {"input_tons": 1000.0,
                                       "outputs": outputs}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_OUTPUT_IMBALANCE)
        assert get_run(run["id"])["production_status"] == "RUNNING"
        assert get_stockpile(ctx["pile"]["id"])["on_hand_tons"] == \
            pytest.approx(0, abs=1e-9)
        assert get_muckpile(ctx["muckpile"]["id"])["remaining_tons"] == \
            pytest.approx(3792.6, abs=1e-6)


class TestParallelStateDimensions:
    def test_reconcile_out_of_tolerance_routes_to_disputed(self, api):
        """PRD 3.5: "A run carries two independent state dimensions on the
        same row: `production_status`, born `SCHEDULED`, and
        `reconciliation_status`, born `UNRECONCILED`."
        PRD 3.5: "When the reconciled figure differs from `input_tons` by
        at most two percent of `input_tons`, inclusive, the run moves to
        `RECONCILED` and the figure is stored; when it differs by more, the
        run routes to `DISPUTED` instead — a threshold branch, not an
        error."

        Design: Difficulty/non_linear_state_machine/plantrun_parallel_state_dimensions
        """
        ctx = setup_plant_run_site()
        run = create_completed_run(
            ctx, 1000.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 970.0)])
        assert run["production_status"] == "COMPLETED"
        assert run["reconciliation_status"] == "UNRECONCILED"
        # 960.0 is 4.0% off — beyond the inclusive 2% tolerance.
        run = validate_success(api.reconcile_plant_run(
            run["id"], {"reconciled_input_tons": 960.0}, OPERATOR))
        assert run["reconciliation_status"] == "DISPUTED"
        assert run["production_status"] == "COMPLETED"

    def test_reconcile_corrected_from_disputed_to_reconciled(self, api):
        """PRD 3.5: "A later corrected submission moves the run `DISPUTED`
        → `RECONCILED` under the same two-percent tolerance and overwrites
        `reconciled_input_tons` with the corrected value."
        PRD 3.5: "A successful completion stamps `ended_at`, computes
        `run_hours` as the elapsed time between `started_at` and `ended_at`
        in hours to two decimals".

        Design: Difficulty/non_linear_state_machine/plantrun_parallel_state_dimensions
        """
        ctx = setup_plant_run_site()
        run = create_completed_run(
            ctx, 1000.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 970.0)])
        # start and complete share one logical timestamp: zero hours.
        assert run["run_hours"] == pytest.approx(0.00, abs=1e-9)
        validate_success(api.reconcile_plant_run(
            run["id"], {"reconciled_input_tons": 960.0}, OPERATOR))
        # 990.0 is 1.0% off — within the inclusive 2% tolerance.
        run = validate_success(api.reconcile_plant_run(
            run["id"], {"reconciled_input_tons": 990.0}, OPERATOR))
        assert run["reconciliation_status"] == "RECONCILED"
        assert run["reconciled_input_tons"] == pytest.approx(990.0, abs=1e-6)
        assert run["production_status"] == "COMPLETED"


class TestCircuitCooldown:
    def test_circuit_cooldown_blocks_start_inside_buffer(self, api):
        """PRD 3.5: "no completed run on the same circuit may have ended so
        recently that thirty minutes have not yet elapsed since its
        `ended_at` (`ERR_CIRCUIT_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/circuit_cooldown_buffer_overlap
        """
        ctx = setup_plant_run_site()
        run_a = create_completed_run(
            ctx, 100.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 100.0)])
        run_b = create_run(ctx)
        set_clock("2026-08-01T10:20:00Z")
        resp = api.start_plant_run(run_b["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CIRCUIT_OVERLAP)
        assert get_run(run_b["id"])["production_status"] == "SCHEDULED"
        assert get_run(run_a["id"])["production_status"] == "COMPLETED"

    def test_circuit_cooldown_boundary_allows_start(self, api):
        """PRD 3.5: "no completed run on the same circuit may have ended so
        recently that thirty minutes have not yet elapsed since its
        `ended_at` (`ERR_CIRCUIT_OVERLAP`)" — at exactly thirty minutes the
        buffer has elapsed and the start succeeds.

        Design: Difficulty/resource_temporal_overlap/circuit_cooldown_buffer_overlap
        """
        ctx = setup_plant_run_site()
        create_completed_run(
            ctx, 100.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 100.0)])
        run_b = create_run(ctx)
        set_clock("2026-08-01T10:30:00Z")
        run_b = validate_success(api.start_plant_run(run_b["id"], OPERATOR))
        assert run_b["production_status"] == "RUNNING"


class TestCancelledRunComplete:
    def test_state_beats_fiscal_on_cancelled_run_complete_error(self, api):
        """PRD 2.7: "Every request is validated against a fixed sequence of
        rule tiers, and the sequence is part of the contract: when several
        rules fail at once, the rejection returned is the one belonging to
        the earliest tier." Tier 5 (own state) precedes tier 11 (inventory,
        capacity, and fiscal guards).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_run_complete
        """
        ctx = setup_plant_run_site(capacity_tons=500)
        run = create_run(ctx)
        validate_success(api.cancel_plant_run(run["id"], OPERATOR))
        outputs = [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 620.0)]
        # 620 t would exceed the 500 t capacity, but the CANCELLED state
        # failure is reported first.
        resp = api.complete_plant_run(run["id"],
                                      {"input_tons": 620.0,
                                       "outputs": outputs}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_beats_fiscal_on_cancelled_run_complete_no_effects(self,
                                                                    api):
        """PRD 2.7 tier 5: "Own state — the target resource's own state must
        permit the requested transition, and terminal states accept no
        further transitions at all, otherwise `ERR_INVALID_STATE` (409)."
        The rejected completion mutates nothing.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_cancelled_run_complete
        """
        ctx = setup_plant_run_site(capacity_tons=500)
        run = create_run(ctx)
        validate_success(api.cancel_plant_run(run["id"], OPERATOR))
        outputs = [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 620.0)]
        validate_error(api.complete_plant_run(
            run["id"], {"input_tons": 620.0, "outputs": outputs}, OPERATOR),
            ApiErrorId.ERR_INVALID_STATE)
        assert get_run(run["id"])["production_status"] == "CANCELLED"
        assert get_stockpile(ctx["pile"]["id"])["on_hand_tons"] == \
            pytest.approx(0, abs=1e-9)


class TestMuckpileDepleteReopen:
    def test_muckpile_deplete_block_reopen_cycle(self, api):
        """PRD 3.3: "When `remaining_tons` reaches exactly zero the pile
        auto-transitions `OPEN` → `DEPLETED`; if a later run void restores
        tonnage above zero, a `DEPLETED` pile auto-reopens to `OPEN`."
        PRD 3.5: "The muckpile must stand `OPEN` (`ERR_MUCKPILE_DEPLETED`)."

        Design: Corner/state_machines/muckpile_deplete_block_reopen_cycle
        """
        ctx = setup_plant_run_site()
        run1 = create_completed_run(
            ctx, 3792.6,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 3792.6)])
        mp = get_muckpile(ctx["muckpile"]["id"])
        assert mp["remaining_tons"] == pytest.approx(0, abs=1e-9)
        assert mp["status"] == "DEPLETED"
        run2 = create_run(ctx, circuit_line="SECONDARY")
        resp = api.start_plant_run(run2["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_MUCKPILE_DEPLETED)
        validate_success(api.void_plant_run(run1["id"], OPERATOR))
        mp = get_muckpile(ctx["muckpile"]["id"])
        assert mp["status"] == "OPEN"
        assert mp["remaining_tons"] == pytest.approx(3792.6, abs=1e-6)


class TestRunVoid:
    def test_run_void_reversal_blocked_after_shipment(self, api):
        """PRD 3.5: "only while the reversal is absorbable, meaning every
        credited pile still holds at least the tonnage it was credited
        (`ERR_REVERSAL_BLOCKED` when shipped tons have already drawn a pile
        below its credit)".

        Design: Corner/validations/run_void_reversal_blocked_after_shipment
        """
        ctx = setup_plant_run_site(capacity_tons=10000)
        run = create_completed_run(
            ctx, 620.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 620.0)])
        # Ship 100 t of the credit out through the scale house.
        create_agreement(ctx["site"]["id"])
        zone = create_zone()
        truck_scale = create_certified_scale(ctx["site"]["id"],
                                             scale_code="TRUCK-01",
                                             scale_type="TRUCK")
        order = create_confirmed_order(ctx["site"]["id"], ctx["spec"]["id"],
                                       zone["id"], quantity_tons=200)
        tctx = {"site": ctx["site"], "spec": ctx["spec"], "zone": zone,
                "pile": ctx["pile"], "agreement": None, "scale": truck_scale,
                "order": order}
        _entry, _ticket = complete_ticket(tctx, truck_id="TRK-1",
                                          gross_lbs=228000, tare_lbs=28000,
                                          max_payload_lbs=250000)
        pile = get_stockpile(ctx["pile"]["id"])
        assert pile["on_hand_tons"] == pytest.approx(520.0, abs=1e-6)
        resp = api.void_plant_run(run["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_REVERSAL_BLOCKED)
        assert get_run(run["id"])["production_status"] == "COMPLETED"
        assert get_stockpile(ctx["pile"]["id"])["on_hand_tons"] == \
            pytest.approx(520.0, abs=1e-6)

    def test_run_complete_debits_muckpile_and_credits_pile(self, api):
        """PRD 3.5: "Its cascades then fire in the same request: the
        muckpile's `actual_fed_tons` gains and `remaining_tons` loses
        `input_tons` (auto-depleting at exactly zero per §3.3); each output
        pile's `on_hand_tons` gains its credited `tons` with
        `available_tons` recomputed".

        Design: Difficulty/compensating_invariant/plant_run_void_roundtrip_conserves_production_mass
        """
        ctx = setup_plant_run_site()
        create_completed_run(
            ctx, 620.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 620.0)])
        mp = get_muckpile(ctx["muckpile"]["id"])
        pile = get_stockpile(ctx["pile"]["id"])
        assert mp["remaining_tons"] == pytest.approx(3172.6, abs=1e-6)
        assert mp["actual_fed_tons"] == pytest.approx(620.0, abs=1e-6)
        assert pile["on_hand_tons"] == pytest.approx(620.0, abs=1e-6)
        # Blast mass is conserved: remaining + credited == design estimate.
        assert mp["remaining_tons"] + pile["on_hand_tons"] == pytest.approx(
            3792.6, abs=1e-6)

    def test_run_void_restores_muckpile_and_reverses_credit(self, api):
        """PRD 3.5: "Voiding moves production to `VOIDED` and compensates
        everything: each credited pile loses its credited `tons` from
        `on_hand_tons` with `available_tons` recomputed, and the muckpile
        regains `input_tons` in `remaining_tons` while losing it from
        `actual_fed_tons` — reopening the pile from `DEPLETED` back to
        `OPEN` if the restoration lifts it above zero."

        Design: Difficulty/compensating_invariant/plant_run_void_roundtrip_conserves_production_mass
        """
        ctx = setup_plant_run_site()
        run = create_completed_run(
            ctx, 620.0,
            [run_output(ctx["pile"]["id"], ctx["spec"]["id"], 620.0)])
        validate_success(api.void_plant_run(run["id"], OPERATOR))
        run = get_run(run["id"])
        assert run["production_status"] == "VOIDED"
        mp = get_muckpile(ctx["muckpile"]["id"])
        assert mp["remaining_tons"] == pytest.approx(3792.6, abs=1e-6)
        assert mp["actual_fed_tons"] == pytest.approx(0, abs=1e-9)
        assert mp["status"] == "OPEN"
        assert get_stockpile(ctx["pile"]["id"])["on_hand_tons"] == \
            pytest.approx(0, abs=1e-9)
