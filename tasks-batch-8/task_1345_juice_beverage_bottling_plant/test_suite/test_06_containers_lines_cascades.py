"""Container lots, bottling lines, changeover windows, and condemn cascades."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, create_line,
    create_container_lot, create_zone, create_released_batch, quote_run,
    confirm_run, schedule_run, set_clock,
)

PM = TEST_USERS["plant_manager_headers"]
QA = TEST_USERS["qa_inspector_headers"]
WH = TEST_USERS["warehouse_lead_headers"]
PLAN = TEST_USERS["production_planner_headers"]


class TestCreateDefaults:
    def test_container_lot_line_zone_defaults(self, api):
        """PRD §3.6: "The lot is born in `RECEIVED` with its full count available:
        `quantity_available` equals `quantity_received`, and `quantity_reserved`
        and `quantity_consumed` are zero." and §3.7: "a new line stands in
        `ACTIVE`." and §3.9: "a new zone starts with `pallets_stored` at zero."

        Design: Corner/entities/container_lot_line_zone_create_defaults
        """
        lot = get_success_data(api.create_container_lot(
            factories.create_container_lot_payload(
                container_type="CAN_330", quantity_received=8000,
                supplier_lot_code="SUP-E4"), WH))
        assert lot["status"] == "RECEIVED"
        assert lot["quantity_available"] == 8000
        assert lot["quantity_reserved"] == 0
        assert lot["quantity_consumed"] == 0
        line = get_success_data(api.create_line(
            factories.create_line_payload(
                line_code="L-E4", supported_container_types=["CAN_330", "PET_473"],
                nominal_cpm=300), PM))
        assert line["status"] == "ACTIVE"
        zone = get_success_data(api.create_zone(
            factories.create_zone_payload(
                zone_code="Z-E4", temperature_class="FROZEN", pallet_capacity=40), PM))
        assert zone["pallets_stored"] == 0


class TestContainerLotLifecycle:
    def test_qc_verdict_only_from_received(self, api):
        """PRD §3.6: "A `QAInspector` then renders a `verdict` on a `RECEIVED` lot
        — any other state draws `ERR_CONTAINER_LOT_STATE_INVALID` — moving it to
        `QC_PASSED` or `QC_FAILED`."

        Design: Corner/state_machines/container_lot_qc_and_return_guards
        """
        lot = get_success_data(api.create_container_lot(
            factories.create_container_lot_payload(
                container_type="GLASS_355", quantity_received=3000,
                supplier_lot_code="SUP-Q1"), WH))
        passed = get_success_data(api.container_qc_verdict(lot["id"], {"verdict": "PASS"}, QA))
        assert passed["status"] == "QC_PASSED"
        # a decided lot accepts no further verdict
        resp = api.container_qc_verdict(lot["id"], {"verdict": "FAIL"}, QA)
        validate_error(resp, ApiErrorId.ERR_CONTAINER_LOT_STATE_INVALID)

    def test_return_requires_qc_failed_and_is_terminal(self, api):
        """PRD §3.6: "A failed lot may be sent back to its supplier by a
        `WarehouseLead`, but only as a whole: the lot must stand in `QC_FAILED`
        with `quantity_reserved` and `quantity_consumed` both at zero, else
        `ERR_CONTAINER_LOT_STATE_INVALID`, whereupon it moves to `RETURNED`."

        Design: Corner/state_machines/container_lot_qc_and_return_guards
        """
        lot = get_success_data(api.create_container_lot(
            factories.create_container_lot_payload(
                container_type="GLASS_355", quantity_received=3000,
                supplier_lot_code="SUP-Q2"), WH))
        # return from RECEIVED refused
        validate_error(api.return_container_lot(lot["id"], WH),
                       ApiErrorId.ERR_CONTAINER_LOT_STATE_INVALID)
        failed = get_success_data(api.container_qc_verdict(lot["id"], {"verdict": "FAIL"}, QA))
        assert failed["status"] == "QC_FAILED"
        returned = get_success_data(api.return_container_lot(lot["id"], WH))
        assert returned["status"] == "RETURNED"
        # RETURNED is terminal
        validate_error(api.return_container_lot(lot["id"], WH),
                       ApiErrorId.ERR_CONTAINER_LOT_STATE_INVALID)
        validate_error(api.container_qc_verdict(lot["id"], {"verdict": "PASS"}, QA),
                       ApiErrorId.ERR_CONTAINER_LOT_STATE_INVALID)

    def test_return_from_qc_passed_refused(self, api):
        """PRD §3.6: "A failed lot may be sent back to its supplier by a
        `WarehouseLead`, but only as a whole: the lot must stand in `QC_FAILED`
        with `quantity_reserved` and `quantity_consumed` both at zero, else
        `ERR_CONTAINER_LOT_STATE_INVALID`"

        Design: Corner/state_machines/container_lot_qc_and_return_guards
        """
        lot = create_container_lot(container_type="GLASS_355", quantity_received=3000)
        assert lot["status"] == "QC_PASSED"
        validate_error(api.return_container_lot(lot["id"], WH),
                       ApiErrorId.ERR_CONTAINER_LOT_STATE_INVALID)


class TestDirectionalChangeover:
    def _directional_setup(self):
        """Four RELEASED batches: B1/B4 of a TREE_NUT formula, B2/B3 of a NONE
        formula; line supporting PET_473; four CONFIRMED runs RA(N) RB(P) RC(P)
        RD(N)."""
        customer = create_customer()
        formula_n = create_formula(customer["id"], allergen_group="TREE_NUT",
                                   formula_code="FN-1", claims=["NON_GMO"])
        formula_p = create_formula(customer["id"], allergen_group="NONE",
                                   formula_code="FP-1", target_brix=10.0)
        batches = {}
        for key, formula in (("b1", formula_n), ("b2", formula_p),
                             ("b3", formula_p), ("b4", formula_n)):
            tank = create_tank()
            batches[key] = create_released_batch(formula, tank)
        line = create_line(supported_container_types=("PET_473",))
        clot = create_container_lot(quantity_received=20000)
        runs = {}
        for key, formula in (("ra", formula_n), ("rb", formula_p),
                             ("rc", formula_p), ("rd", formula_n)):
            run = quote_run(customer["id"], formula["id"], planned_units=1000)
            runs[key] = confirm_run(run["id"])
        return batches, line, runs

    def test_washing_out_of_allergen_needs_75_minutes(self, api):
        """PRD §3.7: "The buffer between two consecutive runs is fifteen minutes
        when both fill the same container type and ninety minutes when they
        differ, plus a further sixty minutes when the outgoing run's formula
        carries an allergen group other than `NONE` that differs from the incoming
        run's allergen group." and "A clash is rejected with
        `ERR_LINE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/line_half_open_directional_changeover
        """
        batches, line, runs = self._directional_setup()
        schedule_run(runs["ra"]["id"], batches["b1"]["id"], line["id"],
                     "2026-08-12T08:00:00Z", "2026-08-12T12:00:00Z")
        # TREE_NUT -> NONE needs 15 + 60 == 75 min: 12:00 + 75 == 13:15
        resp = api.schedule_run(
            runs["rb"]["id"],
            factories.schedule_run_payload(
                batches["b2"]["id"], line["id"], runs["rb"]["version"],
                scheduled_start_at="2026-08-12T13:14:00Z",
                scheduled_end_at="2026-08-12T17:14:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)
        scheduled = schedule_run(runs["rb"]["id"], batches["b2"]["id"], line["id"],
                                 "2026-08-12T13:15:00Z", "2026-08-12T17:15:00Z")
        assert scheduled["production_status"] == "SCHEDULED"

    def test_none_to_allergen_needs_only_15_minutes(self, api):
        """PRD §3.7: "The surcharge is directional on purpose: washing out of an
        allergen run costs the hour, but starting an allergen run behind a `NONE`
        run costs nothing." and "equality is permitted — the final buffer minute
        itself is free."

        Design: Difficulty/resource_temporal_overlap/line_half_open_directional_changeover
        """
        batches, line, runs = self._directional_setup()
        schedule_run(runs["ra"]["id"], batches["b1"]["id"], line["id"],
                     "2026-08-12T08:00:00Z", "2026-08-12T12:00:00Z")
        schedule_run(runs["rb"]["id"], batches["b2"]["id"], line["id"],
                     "2026-08-12T13:15:00Z", "2026-08-12T17:15:00Z")
        # NONE -> NONE: 15 min; 17:15 + 15 == 17:30 exactly
        scheduled_c = schedule_run(runs["rc"]["id"], batches["b3"]["id"], line["id"],
                                   "2026-08-12T17:30:00Z", "2026-08-12T20:30:00Z")
        assert scheduled_c["production_status"] == "SCHEDULED"
        # NONE -> TREE_NUT: still only 15 min (no washout out of NONE)
        resp = api.schedule_run(
            runs["rd"]["id"],
            factories.schedule_run_payload(
                batches["b4"]["id"], line["id"], runs["rd"]["version"],
                scheduled_start_at="2026-08-12T20:44:00Z",
                scheduled_end_at="2026-08-12T23:44:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)
        scheduled_d = schedule_run(runs["rd"]["id"], batches["b4"]["id"], line["id"],
                                   "2026-08-12T20:45:00Z", "2026-08-12T23:45:00Z")
        assert scheduled_d["production_status"] == "SCHEDULED"


class TestDiffContainerChangeover:
    def test_ninety_minute_changeover_boundary(self, api):
        """PRD §3.7: "The buffer between two consecutive runs is fifteen minutes
        when both fill the same container type and ninety minutes when they
        differ" and "equality is permitted — the final buffer minute itself is
        free. A clash is rejected with `ERR_LINE_WINDOW_CONFLICT`."

        Design: Corner/calculations/changeover_diff_container_90min_boundary
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line = create_line(supported_container_types=("PET_473", "CAN_330"))
        create_container_lot(container_type="PET_473", quantity_received=5000)
        create_container_lot(container_type="CAN_330", quantity_received=5000)
        run_a = confirm_run(quote_run(customer["id"], formula["id"], planned_units=500,
                                      container_type="PET_473")["id"])
        run_b = confirm_run(quote_run(customer["id"], formula["id"], planned_units=500,
                                      container_type="CAN_330")["id"])
        schedule_run(run_a["id"], batch1["id"], line["id"],
                     "2026-08-12T08:00:00Z", "2026-08-12T12:00:00Z")
        # different container: 90 min; 12:00 + 90 == 13:30 > 13:29
        resp = api.schedule_run(
            run_b["id"],
            factories.schedule_run_payload(
                batch2["id"], line["id"], run_b["version"],
                scheduled_start_at="2026-08-12T13:29:00Z",
                scheduled_end_at="2026-08-12T17:29:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)
        assert resp.status_code == 409
        scheduled_b = schedule_run(run_b["id"], batch2["id"], line["id"],
                                   "2026-08-12T13:30:00Z", "2026-08-12T17:30:00Z")
        assert scheduled_b["production_status"] == "SCHEDULED"


class TestLineMaintenance:
    def test_maintenance_cycle_and_schedule_guard(self, api):
        """PRD §3.7: "Taking a line down (`ACTIVE` → `MAINTENANCE`) is refused
        with `ERR_LINE_STATE_INVALID` while any run on that line stands in
        `SCHEDULED` or `IN_PRODUCTION`, and only a line in `MAINTENANCE` can be
        returned to service — any other source state for either transition draws
        the same `ERR_LINE_STATE_INVALID`."

        Design: Corner/state_machines/line_maintenance_cycle_and_schedule_guard
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line = create_line()
        create_container_lot()
        run1 = confirm_run(quote_run(customer["id"], formula["id"], planned_units=1000)["id"])
        run1 = schedule_run(run1["id"], batch1["id"], line["id"])
        run2 = confirm_run(quote_run(customer["id"], formula["id"], planned_units=500)["id"])
        # a SCHEDULED run blocks maintenance
        resp = api.set_line_maintenance(line["id"], PM)
        validate_error(resp, ApiErrorId.ERR_LINE_STATE_INVALID)
        get_success_data(api.cancel_run(run1["id"], PLAN))
        down = get_success_data(api.set_line_maintenance(line["id"], PM))
        assert down["status"] == "MAINTENANCE"
        # a MAINTENANCE line takes no bookings
        resp = api.schedule_run(
            run2["id"],
            factories.schedule_run_payload(
                batch2["id"], line["id"], run2["version"],
                scheduled_start_at="2026-08-11T13:00:00Z",
                scheduled_end_at="2026-08-11T17:00:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_LINE_STATE_INVALID)
        up = get_success_data(api.set_line_active(line["id"], PM))
        assert up["status"] == "ACTIVE"
        # the failed schedule applied nothing: the same version still works
        scheduled = schedule_run(run2["id"], batch2["id"], line["id"],
                                 "2026-08-11T13:00:00Z", "2026-08-11T17:00:00Z",
                                 expected_version=run2["version"])
        assert scheduled["production_status"] == "SCHEDULED"


class TestCondemnCascadeDepth4:
    def _cascade_setup(self):
        """R1 SCHEDULED on the only line with batch1; batch2 RELEASED for the
        follow-up run."""
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line = create_line()
        clot = create_container_lot(quantity_received=5000)
        run1 = confirm_run(quote_run(customer["id"], formula["id"], planned_units=1000)["id"])
        run1 = schedule_run(run1["id"], batch1["id"], line["id"],
                            "2026-08-11T08:00:00Z", "2026-08-11T12:00:00Z")
        return {"customer": customer, "formula": formula, "batch1": batch1,
                "batch2": batch2, "line": line, "clot": clot, "run1": run1}

    def test_condemn_blocks_run_and_releases_reservation(self, api):
        """PRD §3.4: "the production run currently reserving the batch through its
        `linked_run_id`, if that run sits in `SCHEDULED`, is demoted to
        `BLOCKED_SUPPLY`; that run's container reservations are released back to
        their lots; and its bottling-line window is freed."

        Design: Difficulty/transitive_cascade/condemn_batch_cascade_depth4
        """
        ctx = self._cascade_setup()
        lot_before = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert lot_before["quantity_reserved"] == 1050  # ceil(1000 * 1.05)
        condemned = get_success_data(api.condemn_batch(ctx["batch1"]["id"], QA))
        assert condemned["status"] == "CONDEMNED"
        run1_after = get_success_data(api.get_production_run(ctx["run1"]["id"], PM))
        assert run1_after["production_status"] == "BLOCKED_SUPPLY"
        lot_after = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert lot_after["quantity_reserved"] == 0
        assert lot_after["quantity_available"] == 5000

    def test_freed_line_window_is_rebookable(self, api):
        """PRD §3.4: "its bottling-line window is freed." and §3.7: "Re-scheduling
        out of `BLOCKED_SUPPLY` follows the identical path with a fresh batch."

        Design: Difficulty/transitive_cascade/condemn_batch_cascade_depth4
        """
        ctx = self._cascade_setup()
        get_success_data(api.condemn_batch(ctx["batch1"]["id"], QA))
        run2 = confirm_run(quote_run(ctx["customer"]["id"], ctx["formula"]["id"],
                                     planned_units=800)["id"])
        # the exact window just freed is bookable again — no line-window conflict
        scheduled = schedule_run(run2["id"], ctx["batch2"]["id"], ctx["line"]["id"],
                                 "2026-08-11T08:00:00Z", "2026-08-11T12:00:00Z")
        assert scheduled["production_status"] == "SCHEDULED"


class TestContainerLotConservation:
    def _conservation_setup(self):
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line = create_line()
        clot = create_container_lot(quantity_received=5000)
        zone = create_zone()
        run1 = confirm_run(quote_run(customer["id"], formula["id"], planned_units=1000)["id"])
        return {"customer": customer, "formula": formula, "batch1": batch1,
                "batch2": batch2, "line": line, "clot": clot, "zone": zone,
                "run1": run1}

    def test_reserve_then_consume_releases_overage(self, api):
        """PRD §2.9: "On a container lot, `quantity_received` always equals
        `quantity_available` plus `quantity_reserved` plus `quantity_consumed`."
        and §3.8: "consumes containers off the run's reserved lots in the same
        oldest-first order in which they were reserved — `actual_units_filled`
        consumed in total, with the unconsumed reserved balance released back to
        availability in the same request"

        Design: Difficulty/compensating_invariant/container_lot_conservation
        """
        ctx = self._conservation_setup()
        schedule_run(ctx["run1"]["id"], ctx["batch1"]["id"], ctx["line"]["id"])
        lot = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert (lot["quantity_reserved"], lot["quantity_available"],
                lot["quantity_consumed"]) == (1050, 3950, 0)
        # run the schedule window
        set_clock("2026-08-11T09:00:00Z")
        get_success_data(api.start_run(ctx["run1"]["id"], PLAN))
        get_success_data(api.complete_run(
            ctx["run1"]["id"],
            factories.complete_run_payload(
                ctx["zone"]["id"], actual_units_filled=900, avg_fill_ml=476), PLAN))
        lot = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        # 900 consumed FIFO; the 150-unit overage released
        assert (lot["quantity_reserved"], lot["quantity_available"],
                lot["quantity_consumed"]) == (0, 4100, 900)
        assert lot["quantity_received"] == (lot["quantity_available"]
                                            + lot["quantity_reserved"]
                                            + lot["quantity_consumed"])

    def test_cancel_releases_reservation_without_drift(self, api):
        """PRD §3.7: "Cancellation compensates in full: container reservations are
        released, the line window is freed, the batch link is cleared while the
        batch itself remains `RELEASED`" and §2.9: "On a container lot,
        `quantity_received` always equals `quantity_available` plus
        `quantity_reserved` plus `quantity_consumed`."

        Design: Difficulty/compensating_invariant/container_lot_conservation
        """
        ctx = self._conservation_setup()
        schedule_run(ctx["run1"]["id"], ctx["batch1"]["id"], ctx["line"]["id"])
        set_clock("2026-08-11T09:00:00Z")
        get_success_data(api.start_run(ctx["run1"]["id"], PLAN))
        get_success_data(api.complete_run(
            ctx["run1"]["id"],
            factories.complete_run_payload(
                ctx["zone"]["id"], actual_units_filled=900, avg_fill_ml=476), PLAN))
        # second run reserves ceil(800 * 1.05) == 840, then cancels
        run2 = confirm_run(quote_run(ctx["customer"]["id"], ctx["formula"]["id"],
                                     planned_units=800)["id"])
        schedule_run(run2["id"], ctx["batch2"]["id"], ctx["line"]["id"],
                     "2026-08-11T13:00:00Z", "2026-08-11T17:00:00Z")
        lot = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert (lot["quantity_reserved"], lot["quantity_available"],
                lot["quantity_consumed"]) == (840, 3260, 900)
        get_success_data(api.cancel_run(run2["id"], PLAN))
        lot = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert (lot["quantity_reserved"], lot["quantity_available"],
                lot["quantity_consumed"]) == (0, 4100, 900)
        assert lot["quantity_received"] == (lot["quantity_available"]
                                            + lot["quantity_reserved"]
                                            + lot["quantity_consumed"])
        batch2 = get_success_data(api.get_batch(ctx["batch2"]["id"], PM))
        assert batch2["status"] == "RELEASED"
