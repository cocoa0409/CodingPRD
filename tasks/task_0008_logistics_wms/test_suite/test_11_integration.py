"""End-to-end integration: full lifecycle from warehouse creation to ship."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_warehouse_payload, create_bin_payload, create_lot_payload,
    create_order_payload, create_pack_payload, create_pick_complete_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    create_allocated_order, setup_released_wave_for_order,
    get_pick_tasks_for_order, get_inventory_row,
    TEST_USERS,
)


class TestEndToEnd:
    def test_full_lifecycle_create_through_ship(self, api):
        """PRD §3.4–§3.7: full happy-path end to end.

        Claim: a warehouse → bin → lot → inbound shipment → inspection →
        putaway → order → allocate → wave → release → pick start → pick
        complete → pack → ship sequence completes successfully and the
        final order is SHIPPED with the expected label/tracking and the
        inventory has been debited.
        """
        manager = TEST_USERS["manager_headers"]
        staff = TEST_USERS["staff_headers"]

        wh = validate_success(api.create_warehouse(
            create_warehouse_payload(name="E2E-WH", dock_position_x=0, dock_position_y=0),
            manager), 201)
        b = validate_success(api.create_bin(
            wh["id"],
            create_bin_payload(bin_code="E2E-B", zone="AMBIENT",
                              position_x=3, position_y=4,
                              capacity_volume_cm3=10000, capacity_weight_g=10000),
            manager), 201)
        lot = validate_success(api.create_lot(
            wh["id"],
            create_lot_payload(lot_code="E2E-L", sku="PEN", category="AMBIENT",
                              unit_volume_cm3=20, unit_weight_g=10,
                              unit_value_cents=100),
            manager), 201)
        # Inbound cycle
        from test_helpers import (
            create_inbound_shipment_payload,
            create_complete_inspection_payload,
        )
        sh = validate_success(api.create_inbound_shipment(
            wh["id"], create_inbound_shipment_payload(lot["id"], 50),
            staff), 201)
        validate_success(api.start_inspection(wh["id"], sh["id"], staff), 200)
        validate_success(api.complete_inspection(
            wh["id"], sh["id"],
            create_complete_inspection_payload(lot["id"], 50, 0),
            staff), 200)
        validate_success(api.putaway_inbound_shipment(wh["id"], sh["id"], staff), 200)
        # Order pipeline
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 10}],
                order_number="E2E-ORD", carrier="FEDEX"),
            staff), 201)
        allocated = validate_success(api.allocate_order(wh["id"], order["id"], staff), 200)
        assert allocated["status"] == "ALLOCATED"
        from test_helpers import create_wave_payload
        wave = validate_success(api.create_wave(
            wh["id"], create_wave_payload([order["id"]], wave_code="E2E-WV"),
            staff), 201)
        validate_success(api.release_wave(wh["id"], wave["id"], staff), 200)
        pts = get_pick_tasks_for_order(wh["id"], order["id"])
        assert len(pts) == 1
        pt = pts[0]
        validate_success(api.start_pick_task(wh["id"], pt["id"], staff), 200)
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(10), staff), 200)
        # The order should now be PICKED
        order_picked = validate_success(api.get_order(wh["id"], order["id"], staff), 200)
        assert order_picked["status"] == "PICKED"
        # Pack
        validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff), 200)
        # Ship
        shipped = validate_success(api.ship_order(wh["id"], order["id"], staff), 200)
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipping_label_id"].startswith("lbl_")
        assert shipped["tracking_number"].startswith("FX")  # FEDEX
        # Wave auto-completed
        wave_after = validate_success(api.get_wave(wh["id"], wave["id"], staff), 200)
        assert wave_after["status"] == "COMPLETED"
        # Inventory debited
        inv = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv["qty_units"] == 40
        assert inv["reserved_units"] == 0
