"""Run-close accounting: dual-variant reconciliation, variance alert boundary, purge on color change, FIFO material waterfall, void compensation, and immediate consistency."""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    close_production_run_payload,
    setup_running_scenario, setup_closed_run_scenario,
    setup_qualified_plant, create_customer, create_line, create_mold,
    create_spec, qualify_spec, create_draft_order, schedule_order,
    create_lot, install_mold, release_order, set_clock, start_run, close_run,
    get_qtl_id_for_run, sample_lot, record_results,
    assert_material_lot_conservation,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["plant_admin"]
ENGINEER = TEST_USERS["process_engineer"]
TECH = TEST_USERS["quality_technician"]
SCHEDULER = TEST_USERS["production_scheduler"]


class TestDualVariantReconciliation:
    def test_close_reports_provisional_and_actual_variants(self, api):
        """PRD §3.6: "The provisional variant computes what the machine counters imply — `cycles_completed` times `cavities_active_at_start` times the order's `planned_weight_g`, converted from grams to kilograms, rounded half-up to two decimals — and stores it as `provisional_consumption_kg`. The actual variant is the reported `actual_drawdown_kg`"

Design: Difficulty/dual_variant_calc/resin_provisional_vs_actual_variance"""
        ctx = setup_running_scenario()
        run = validate_success(api.close_production_run(
            ctx["run"]["id"],
            close_production_run_payload(cycles_completed=2000, good_count=11880,
                                         scrap_count=120, actual_drawdown_kg=360.0),
            ENGINEER), 200)
        # provisional: 2000 * 8 * 22 / 1000 = 352.0 kg (theoretical variant)
        assert run["provisional_consumption_kg"] == 352.0
        # actual variant: the reported silo drawdown, differing by scrap/startup
        assert run["actual_drawdown_kg"] == 360.0
        # gap: round_half_up((360 - 352) / 352 * 100, 2) = 2.27
        assert run["consumption_variance_pct"] == 2.27

    def test_variance_below_tolerance_no_alert_and_lot_debited(self, api):
        """PRD §3.6: "When that percentage is strictly greater than 3.0, `variance_alert` is set". "Each lot in turn first absorbs purge waste into its `purge_wasted_kg` and then consumption into its `consumed_kg`". "A lot debited for the first time moves `RELEASED` → `IN_USE`".

Design: Difficulty/dual_variant_calc/resin_provisional_vs_actual_variance"""
        ctx = setup_running_scenario()
        run = validate_success(api.close_production_run(
            ctx["run"]["id"],
            close_production_run_payload(cycles_completed=2000, good_count=11880,
                                         scrap_count=120, actual_drawdown_kg=360.0),
            ENGINEER), 200)
        # 2.27 <= 3.0 → no alert
        assert run["variance_alert"] is False
        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["consumed_kg"] == 360.0
        assert lot["purge_wasted_kg"] == 0.0
        assert lot["available_kg"] == 140.0
        assert lot["status"] == "IN_USE"


class TestConservationAcrossCloseAndVoid:
    def test_close_debits_lot_and_preserves_conservation(self, api):
        """PRD §3.4: "Its `available_kg` is always what remains of the received quantity after consumption and purge waste, and the server never lets it go negative."
PRD §3.6: "The material allocation waterfall then pays the bill from inventory. The requirement is the `actual_drawdown_kg` plus the `purge_kg`".

Design: Difficulty/compensating_invariant/material_lot_conservation_across_close_and_void"""
        ctx = setup_closed_run_scenario()
        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["available_kg"] == 140.0
        assert lot["consumed_kg"] == 360.0
        assert lot["purge_wasted_kg"] == 0.0
        assert lot["status"] == "IN_USE"
        assert_material_lot_conservation(lot)

    def test_void_restores_lot_exactly(self, api):
        """PRD §3.6: "Voiding reverses every debit the close made, crediting each touched lot's `consumed_kg` and `purge_wasted_kg` back by exactly the amounts taken". "The run's `PENDING` quality lot becomes `VOIDED`". "the line's `last_color_class` is rebuilt from the most recent remaining non-voided closed run — null when none remains."

Design: Difficulty/compensating_invariant/material_lot_conservation_across_close_and_void"""
        ctx = setup_closed_run_scenario()
        run = validate_success(api.void_production_run(ctx["run"]["id"], ADMIN), 200)
        assert run["status"] == "VOIDED"

        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["available_kg"] == 500.0
        assert lot["consumed_kg"] == 0.0
        assert lot["purge_wasted_kg"] == 0.0
        assert lot["status"] == "RELEASED"
        assert_material_lot_conservation(lot)

        qtl = get_success_data(api.get_quality_test_lot(ctx["qtl_id"], TECH))
        assert qtl["status"] == "VOIDED"
        line = get_success_data(api.get_machine_line(ctx["line"]["id"], ENGINEER))
        assert line["last_color_class"] is None


class TestVarianceAlertBoundary:
    def test_alert_at_exactly_tolerance_not_triggered_but_above_is(self, api):
        """PRD §3.6: "When that percentage is strictly greater than 3.0, `variance_alert` is set; a variance of exactly 3.00 does not alert."

Design: Corner/calculations/variance_alert_exactly_at_tolerance_not_triggered"""
        ctx = setup_running_scenario(lot_overrides={"received_kg": 1000})
        run1 = validate_success(api.close_production_run(
            ctx["run"]["id"],
            close_production_run_payload(actual_drawdown_kg=362.56),
            ENGINEER), 200)
        # round_half_up((362.56 - 352) / 352 * 100, 2) = 3.0 — exactly at the
        # tolerance, strictly-greater rule → no alert
        assert run1["consumption_variance_pct"] == 3.0
        assert run1["variance_alert"] is False

        run2 = start_run(ctx["order"]["id"], ctx["line"]["id"],
                         ctx["mold"]["id"], ctx["lot"]["id"])
        run2 = validate_success(api.close_production_run(
            run2["id"],
            close_production_run_payload(actual_drawdown_kg=362.6),
            ENGINEER), 200)
        # round_half_up(10.6 / 352 * 100, 2) = 3.01 > 3.0 → alert
        assert run2["consumption_variance_pct"] == 3.01
        assert run2["variance_alert"] is True

        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["consumed_kg"] == pytest.approx(725.16, abs=1e-6)
        assert lot["available_kg"] == pytest.approx(274.84, abs=1e-6)


class TestPurgeOnColorChange:
    def test_dark_to_clear_purge_debits_lot(self, api):
        """PRD §3.6: "from `DARK`, moving to `CLEAR` costs 3.0". "The `purge_kg` charged to the run is the line's `resident_volume_kg` multiplied by that multiplier, rounded half-up to two decimals." "With the debits settled, the close writes the spec's `color_contrast_class` into the line's `last_color_class`".

Design: Corner/calculations/purge_matrix_dark_to_clear_debits_lot"""
        customer = create_customer()
        line = create_line(line_code="L2")
        mold = create_mold()
        spec_dark = qualify_spec(create_spec(
            customer["id"], spec_code="D500", color_contrast_class="DARK")["id"])
        spec_clear = qualify_spec(create_spec(
            customer["id"], spec_code="C500", color_contrast_class="CLEAR")["id"])
        lot = create_lot(release=True, received_kg=500)
        colorant = create_lot(release=True, material_type="COLORANT",
                              color_code="BLK", lot_code="C-BLK", received_kg=50)
        install_mold(mold["id"], line["id"])

        order_dark = schedule_order(
            create_draft_order(spec_dark["id"], quantity_ordered=2000),
            line["id"], planned_start="2026-08-02T10:00:00Z",
            planned_end="2026-08-02T12:00:00Z")
        order_clear = schedule_order(
            create_draft_order(spec_clear["id"], quantity_ordered=2000),
            line["id"], planned_start="2026-08-02T12:00:00Z",
            planned_end="2026-08-02T14:00:00Z")

        release_order(order_dark["id"])
        set_clock("2026-08-02T11:00:00Z")
        run_dark = start_run(order_dark["id"], line["id"], mold["id"],
                             lot["id"], colorant_lot_id=colorant["id"])
        close_run(run_dark["id"], cycles_completed=100, good_count=700,
                  scrap_count=10, actual_drawdown_kg=17.6)
        qtl_dark = get_qtl_id_for_run(run_dark["id"])
        sample_lot(qtl_dark)
        record_results(qtl_dark, 0, 0)
        validate_success(api.complete_production_order(order_dark["id"],
                                                       SCHEDULER), 200)

        release_order(order_clear["id"])
        set_clock("2026-08-02T12:30:00Z")
        run_clear = start_run(order_clear["id"], line["id"], mold["id"],
                              lot["id"])
        run_clear = validate_success(api.close_production_run(
            run_clear["id"],
            close_production_run_payload(cycles_completed=100, good_count=700,
                                         scrap_count=10, actual_drawdown_kg=17.6),
            ENGINEER), 200)

        # purge: resident 50 kg x DARK->CLEAR multiplier 3.0
        assert run_clear["purge_kg"] == 150.0
        lot_after = get_success_data(api.get_material_lot(lot["id"], TECH))
        assert lot_after["consumed_kg"] == pytest.approx(35.2, abs=1e-6)   # 17.6 + 17.6
        assert lot_after["purge_wasted_kg"] == pytest.approx(150.0, abs=1e-6)
        assert lot_after["available_kg"] == pytest.approx(314.8, abs=1e-6)  # 500 - 35.2 - 150.0
        assert_material_lot_conservation(lot_after)
        line_after = get_success_data(api.get_machine_line(line["id"], ENGINEER))
        assert line_after["last_color_class"] == "CLEAR"


class TestWaterfallFifo:
    def test_fifo_drains_older_lot_first(self, api):
        """PRD §3.6: "the candidate pool is every resin lot matching the spec's `resin_type` in `RELEASED` or `IN_USE`, ordered by `created_at` ascending with `lot_code` ascending breaking ties. Each lot in turn first absorbs purge waste into its `purge_wasted_kg` and then consumption into its `consumed_kg`, filling its `available_kg` completely before the next lot is touched. A lot debited for the first time moves `RELEASED` → `IN_USE`; a lot whose `available_kg` reaches exactly zero becomes `DEPLETED`."

Design: Corner/calculations/waterfall_fifo_across_two_lots"""
        ctx = setup_qualified_plant()
        order = create_draft_order(ctx["spec"]["id"], quantity_ordered=2000)
        order = schedule_order(order, ctx["line"]["id"])
        lot1 = create_lot(lot_code="R-1", received_kg=100)   # created first
        lot2 = create_lot(lot_code="R-2", received_kg=200)
        get_success_data(api.release_material_lot(lot1["id"], TECH))
        get_success_data(api.release_material_lot(lot2["id"], TECH))
        install_mold(ctx["mold"]["id"], ctx["line"]["id"])
        release_order(order["id"])
        set_clock()
        run = start_run(order["id"], ctx["line"]["id"], ctx["mold"]["id"],
                        lot1["id"])
        close_run(run["id"], cycles_completed=600, good_count=4000,
                  scrap_count=100, actual_drawdown_kg=150.0)

        lot1_after = get_success_data(api.get_material_lot(lot1["id"], TECH))
        assert lot1_after["consumed_kg"] == 100.0
        assert lot1_after["available_kg"] == 0.0
        assert lot1_after["status"] == "DEPLETED"

        lot2_after = get_success_data(api.get_material_lot(lot2["id"], TECH))
        assert lot2_after["consumed_kg"] == 50.0
        assert lot2_after["available_kg"] == 150.0
        assert lot2_after["status"] == "IN_USE"


class TestImmediateConsistency:
    def test_close_response_and_get_reflect_debit_immediately(self, api):
        """PRD §2.10: "The aggregate graph is reconciled immediately, never eventually." PRD §3.6: the close "reconciles consumption in two variants" and stores `provisional_consumption_kg`; the debits settle in the same gesture.

Design: Corner/consistency_model/close_response_reflects_debit_immediately"""
        ctx = setup_running_scenario()
        run = validate_success(api.close_production_run(
            ctx["run"]["id"], close_production_run_payload(), ENGINEER), 200)
        # same-request visibility of the computed reconciliation
        assert run["status"] == "CLOSED"
        assert run["provisional_consumption_kg"] == 352.0
        # plain GET in the same test (no clock ops, no batch) shows the debit
        lot = get_success_data(api.get_material_lot(ctx["lot"]["id"], TECH))
        assert lot["available_kg"] == 140.0
        assert lot["status"] == "IN_USE"
