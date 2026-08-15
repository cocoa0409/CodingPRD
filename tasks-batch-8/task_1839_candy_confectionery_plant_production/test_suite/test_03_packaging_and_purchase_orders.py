"""Packaging reservation math, purchase-order lead times, and the
reserve/cancel conservation invariant."""
from test_helpers import (
    PLANNER,
    ApiErrorId,
    assert_packaging_invariants,
    cancel_run,
    create_packaging_component,
    create_purchase_order_payload,
    create_run,
    get_component,
    get_run,
    get_success_data,
    hold_run,
    parse_instant,
    set_clock,
    setup_runnable_plant,
    start_run,
    validate_error,
    validate_success,
)


class TestRunCreationReservation:
    def test_run_born_planned_with_packaging_reserved(self, api):
        """PRD §3.5: "However the run is shaped, it is born `PLANNED` with
        `output_units` and `created_lot_id` still null"
        PRD §3.5: "On acceptance, the component's `qty_reserved` increases by the
        requirement, the exact reserved amount is recorded on the run as
        `packaging_reserved_qty`, the component's `version` increments, and
        `qty_available` is recomputed"
        PRD §3.5: "for non-rework runs `expected_output_units` stays null."

        Design: Corner/state_machines/run_created_initial_state_planned
        """
        plant = setup_runnable_plant()
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        assert run["status"] == "PLANNED"
        assert run["packaging_reserved_qty"] == 50, "ceil(500 / 10)"
        assert run["output_units"] is None
        assert run["created_lot_id"] is None
        assert run["expected_output_units"] is None, "stays null for non-rework runs"

        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 50
        assert_packaging_invariants(component)


class TestPackagingCeilBoundary:
    def test_exact_multiple_and_partial_component_round_up(self, api):
        """PRD §3.5: "The requirement is the run's `planned_units` divided by the
        product's packaging component's `units_per_component`, rounded up to a
        whole component"
        PRD §2.9: "Packaging requirements use ceiling division — any fractional
        component rounds up to a whole component"

        Design: Corner/calculations/packaging_requirement_ceil_boundary
        """
        plant = setup_runnable_plant()
        create_run(plant["window"]["id"], plant["product"]["id"],
                   plant["recipe"]["id"], plant["line"]["id"], planned_units=5000,
                   scheduled_start="2026-09-05T08:00:00Z",
                   scheduled_end="2026-09-05T16:00:00Z")
        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 500, "5000 / 10 is exact — no round-up"

        create_run(plant["window"]["id"], plant["product"]["id"],
                   plant["recipe"]["id"], plant["line"]["id"], planned_units=5001,
                   scheduled_start="2026-09-06T08:00:00Z",
                   scheduled_end="2026-09-06T16:00:00Z")
        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 1001, "ceil(5001 / 10) = 501 added"


class TestPackagingShortage:
    def test_requirement_exceeding_available_rejected(self, api):
        """PRD §3.5: "if that requirement exceeds the component's `qty_available`,
        the create is rejected with `ERR_PACKAGING_SHORTAGE`."

        Design: Corner/validations/run_create_packaging_shortage_rejected
        """
        plant = setup_runnable_plant(product_type="SEASONAL", sku_code="TRUFFLE-24",
                                     base_price_cents=1000, shelf_life_days=180,
                                     qty_on_hand=100, target_units=10000)
        resp = api.create_production_run(
            {"window_id": plant["window"]["id"],
             "product_id": plant["product"]["id"],
             "recipe_id": plant["recipe"]["id"],
             "line_id": plant["line"]["id"],
             "run_type": "STANDARD", "planned_units": 5000,
             "scheduled_start": "2026-09-05T08:00:00Z",
             "scheduled_end": "2026-09-05T16:00:00Z",
             "expected_window_version": plant["window"]["version"]},
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_PACKAGING_SHORTAGE)

        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 0, "a rejected create reserves nothing"
        assert_packaging_invariants(component)


class TestReserveCancelConservation:
    def test_cancel_from_planned_restores_availability(self, api):
        """PRD §3.6: "Cancellation releases the packaging reservation: the
        component's `qty_reserved` decreases by `packaging_reserved_qty` and
        `qty_available` is recomputed, with no consumption of `qty_on_hand`."
        PRD §2.11: "`qty_available` is always exactly `qty_on_hand` minus
        `qty_reserved`, recomputed on every mutation of either operand."

        Design: Difficulty/compensating_invariant/packaging_reserve_cancel_conservation
        """
        plant = setup_runnable_plant(qty_on_hand=1000)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=5000)
        assert run["packaging_reserved_qty"] == 500

        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 500
        assert component["qty_available"] == 500
        assert component["qty_on_hand"] == 1000

        cancel_run(run["id"])
        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 0
        assert component["qty_available"] == 1000
        assert component["qty_on_hand"] == 1000, "reservation is never consumption"
        assert_packaging_invariants(component)

    def test_cancel_from_on_hold_restores_availability(self, api):
        """PRD §3.6: "The `ProductionPlanner` may cancel a run from `PLANNED` or
        `ON_HOLD` — from any other state, `ERR_INVALID_STATE` — landing it in the
        terminal `CANCELLED`."
        PRD §3.6: "Cancellation releases the packaging reservation: the
        component's `qty_reserved` decreases by `packaging_reserved_qty` and
        `qty_available` is recomputed, with no consumption of `qty_on_hand`."

        Design: Difficulty/compensating_invariant/packaging_reserve_cancel_conservation
        """
        plant = setup_runnable_plant(qty_on_hand=1000)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=5000)
        start_run(run["id"])
        hold_run(run["id"])
        cancel_run(run["id"])

        run = get_run(run["id"])
        assert run["status"] == "CANCELLED"
        component = get_component(plant["component"]["id"])
        assert component["qty_on_hand"] == 1000
        assert component["qty_reserved"] == 0
        assert component["qty_available"] == 1000
        assert_packaging_invariants(component)


class TestPurchaseOrderLeadTime:
    def test_receive_before_due_rejected_then_succeeds(self, api):
        """PRD §3.2: "Its `due_at` is computed as `ordered_at` plus the
        component's `lead_time_days`, and `received_at` stays null until the goods
        land."
        PRD §3.2: "it requires the logical clock to have reached `due_at` — an
        earlier receipt attempt is rejected with `ERR_PO_NOT_DUE`."
        PRD §3.2: "On receipt the order transitions from `ORDERED` to `RECEIVED`,
        its terminal state, `received_at` is set to the current clock, and the
        ledger syncs: the component's `qty_on_hand` increases by the order's
        `order_qty`, `qty_available` is recomputed, and the component's `version`
        increments."

        Design: Corner/state_machines/po_receive_before_due_rejected_then_succeeds
        """
        set_clock("2026-09-01T00:00:00Z")
        component = create_packaging_component(
            sku_code="FILM-X", name="Flow-wrap film", lead_time_days=14,
            qty_on_hand=1000)
        po = get_success_data(api.create_purchase_order(
            component["id"], create_purchase_order_payload(500), PLANNER))
        assert po["status"] == "ORDERED"
        assert po["received_at"] is None
        assert parse_instant(po["ordered_at"]) == parse_instant("2026-09-01T00:00:00Z")
        assert parse_instant(po["due_at"]) == parse_instant("2026-09-15T00:00:00Z"), (
            "ordered_at + lead_time_days")

        set_clock("2026-09-14T12:00:00Z")
        validate_error(api.receive_purchase_order(po["id"], PLANNER),
                       ApiErrorId.ERR_PO_NOT_DUE)

        set_clock("2026-09-15T00:00:00Z")
        received = validate_success(api.receive_purchase_order(po["id"], PLANNER))
        assert received["status"] == "RECEIVED"
        assert parse_instant(received["received_at"]) == parse_instant(
            "2026-09-15T00:00:00Z"), "received_at is set to the current clock"

        component = get_component(component["id"])
        assert component["qty_on_hand"] == 1500, "ledger sync adds order_qty"
        assert_packaging_invariants(component)


class TestImmediateConsistency:
    def test_reservation_visible_immediately(self, api):
        """PRD §3.5: "On acceptance, the component's `qty_reserved` increases by
        the requirement, the exact reserved amount is recorded on the run as
        `packaging_reserved_qty`, the component's `version` increments, and
        `qty_available` is recomputed"
        PRD §2.11: "`qty_available` is always exactly `qty_on_hand` minus
        `qty_reserved`, recomputed on every mutation of either operand."

        Design: Corner/consistency_model/immediate_consistency_reservation_visible
        """
        plant = setup_runnable_plant(qty_on_hand=1000)
        run = create_run(plant["window"]["id"], plant["product"]["id"],
                         plant["recipe"]["id"], plant["line"]["id"],
                         planned_units=500)
        assert run["packaging_reserved_qty"] == 50

        component = get_component(plant["component"]["id"])
        assert component["qty_reserved"] == 50
        assert component["qty_available"] == 950
        assert_packaging_invariants(component)
