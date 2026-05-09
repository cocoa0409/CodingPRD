"""Packing, carton calculation, and shipping."""
import pytest
import math
from test_helpers import (
    api_client, validate_success, validate_error,
    create_order_payload, create_pack_payload, create_pick_complete_payload,
    create_warehouse, create_bin, create_lot, putaway_lot_units,
    setup_warehouse_with_inventory, create_allocated_order,
    setup_released_wave_for_order, get_pick_tasks_for_order,
    setup_picking_pick_task,
    TEST_USERS, CARTON_VOLUME_CM3, CARTON_WEIGHT_G,
    TRACKING_PREFIX,
)


class TestProvisionalCartonCount:
    def test_provisional_carton_count_set_on_allocate(self, api, staff_headers):
        """PRD §3.4: "A successful allocation generates pick tasks per the
        lot-selector rule, ... and sets the order's provisional_carton_count"
        PRD §3.7: "Both share the same physical constants — a single carton
        holds at most 50000 cubic centimetres of volume and 20000 grams of
        weight — and both compute the count by taking the maximum of three
        values: cartons-by-volume (the order's total volume divided by 50000,
        rounded up to a whole carton), cartons-by-weight (the order's total
        weight divided by 20000, rounded up to a whole carton), and the
        floor of one carton (so that even a tiny order ships in at least
        one carton)."

        Claim: a small allocation has provisional_carton_count >= 1.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        order = create_allocated_order(wh["id"], sku="PEN", qty_units=2,
                                       order_number="ORD-PROV-1")
        assert order["provisional_carton_count"] >= 1

    def test_provisional_carton_sum_then_ceil(self, api, staff_headers, manager_headers):
        """PRD §3.7: "Both share the same physical constants — a single
        carton holds at most 50000 cubic centimetres of volume and 20000
        grams of weight — and both compute the count by taking the maximum
        of three values: cartons-by-volume (the order's total volume divided
        by 50000, rounded up to a whole carton), ..."

        # difficulty: combinatorial_formula/carton_count_sum_then_ceil_mode_b
        Claim: with 2 SKUs each contributing 60000 cm3 (total 120000),
        provisional_carton_count = ceil(120000/50000) = 3
        (sum-then-ceil), not 4 (ceil-then-sum).
        """
        wh = create_warehouse()
        b = create_bin(wh["id"], bin_code="B1", zone="AMBIENT",
                      capacity_volume_cm3=200000, capacity_weight_g=50000)
        lot_pen = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                            unit_volume_cm3=30000, unit_weight_g=100,
                            unit_value_cents=100,
                            lot_code="LP")
        lot_wid = create_lot(wh["id"], sku="WIDGET", category="AMBIENT",
                            unit_volume_cm3=30000, unit_weight_g=100,
                            unit_value_cents=100,
                            lot_code="LW")
        putaway_lot_units(wh["id"], lot_pen["id"], 2)
        # Need a second bin since the first one will fill up
        b2 = create_bin(wh["id"], bin_code="B2", zone="AMBIENT",
                       capacity_volume_cm3=200000, capacity_weight_g=50000)
        putaway_lot_units(wh["id"], lot_wid["id"], 2, asn_number="ASN-WID")
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[
                    {"sku": "PEN", "qty_units": 2},
                    {"sku": "WIDGET", "qty_units": 2},
                ],
                order_number="ORD-CARTON", carrier="UPS",
                pick_strategy="FEFO"),
            staff_headers), 201)
        allocated = validate_success(api.allocate_order(
            wh["id"], order["id"], staff_headers), 200)
        # 2*30000 + 2*30000 = 120000; ceil(120000/50000) = 3
        # weight: 2*100 + 2*100 = 400; ceil(400/20000) = 1
        # max(3, 1, 1) = 3
        assert allocated["provisional_carton_count"] == 3, \
            f"sum-then-ceil should give 3, got {allocated['provisional_carton_count']}"


class TestPack:
    def test_pack_picked_order(self, api, staff_headers):
        """PRD §3.7: "Packing an order moves it from PICKED to PACKED ...
        On a successful pack the system writes final_carton_count onto the
        order."

        Claim: pack on PICKED order → PACKED with final_carton_count set.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=5)
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(5), staff_headers), 200)
        order_picked = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_picked["status"] == "PICKED"
        packed = validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff_headers), 200)
        assert packed["status"] == "PACKED"
        assert packed["final_carton_count"] is not None
        assert packed["final_carton_count"] >= 1

    def test_pack_short_picked_without_allow_partial_rejected(self, api, staff_headers):
        """PRD §2.6 rule 17: "A PICKED order may pack to PACKED only when
        none of its pick tasks is in SHORT_PICKED or FAILED; a SHORT_PICKED
        order may pack to PACKED only when the request body field
        allow_partial is exactly true and at least one pick task is PICKED.
        Otherwise the response is ERR_INVALID_STATE."

        Claim: packing a SHORT_PICKED order without allow_partial=true →
        ERR_INVALID_STATE.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=10)
        # Short pick
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(7), staff_headers), 200)
        order_short = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_short["status"] == "SHORT_PICKED"
        validate_error(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff_headers),
            "ERR_INVALID_STATE")
        validate_error(api.pack_order(
            wh["id"], order["id"], create_pack_payload(allow_partial=False), staff_headers),
            "ERR_INVALID_STATE")

    def test_pack_short_picked_with_allow_partial(self, api, staff_headers):
        """PRD §3.7: "Packing also accepts SHORT_PICKED orders, but only
        when the request body's allow_partial field is exactly the boolean
        true and at least one pick task has reached PICKED; otherwise the
        response is ERR_INVALID_STATE."
        Note: PRD §3.7 requires "at least one pick task has reached PICKED"
        for SHORT_PICKED→PACKED via allow_partial. So we engineer two pick
        tasks: one fully PICKED, one SHORT_PICKED.

        Claim: pack on SHORT_PICKED with allow_partial=true and at least
        one PICKED pick task → PACKED.
        """
        # Need an order with two pick tasks: split inventory across two lots.
        wh = create_warehouse(advance_clock_to="2025-01-01T00:00:00.000Z")
        b = create_bin(wh["id"], bin_code="BPP", zone="AMBIENT",
                      capacity_volume_cm3=100000, capacity_weight_g=100000)
        lot_a = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                          unit_volume_cm3=20, unit_weight_g=10,
                          unit_value_cents=100,
                          lot_code="LA1", expiry_date="2025-12-31T00:00:00.000Z")
        putaway_lot_units(wh["id"], lot_a["id"], 5)
        # Advance clock so lot_b is later-received
        from test_helpers import create_clock_advance_payload
        validate_success(api.advance_clock(
            create_clock_advance_payload(wh["id"], "2025-02-01T00:00:00.000Z"),
            TEST_USERS["manager_headers"]), 200)
        lot_b = create_lot(wh["id"], sku="PEN", category="AMBIENT",
                          unit_volume_cm3=20, unit_weight_g=10,
                          unit_value_cents=100,
                          lot_code="LB1", expiry_date="2026-12-31T00:00:00.000Z")
        putaway_lot_units(wh["id"], lot_b["id"], 5, asn_number="ASN-PP-B")
        # Order requests 10 → FEFO picks lot_a first (5 units), then lot_b (5 units)
        order = validate_success(api.create_order(
            wh["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 10}],
                order_number="ORD-PP", carrier="UPS"),
            staff_headers), 201)
        validate_success(api.allocate_order(wh["id"], order["id"], staff_headers), 200)
        wave = setup_released_wave_for_order(wh["id"], order["id"], wave_code="WV-PP")
        pts = get_pick_tasks_for_order(wh["id"], order["id"])
        assert len(pts) == 2
        # Sort by lot_id (lot_a expires first → first pick task is lot_a)
        pt_a = next(pt for pt in pts if pt["lot_id"] == lot_a["id"])
        pt_b = next(pt for pt in pts if pt["lot_id"] == lot_b["id"])
        # Start and complete pt_a fully (PICKED), short-pick pt_b
        validate_success(api.start_pick_task(wh["id"], pt_a["id"], staff_headers), 200)
        validate_success(api.complete_pick_task(
            wh["id"], pt_a["id"], create_pick_complete_payload(5), staff_headers), 200)
        validate_success(api.start_pick_task(wh["id"], pt_b["id"], staff_headers), 200)
        validate_success(api.complete_pick_task(
            wh["id"], pt_b["id"], create_pick_complete_payload(2), staff_headers), 200)
        order_short = validate_success(api.get_order(wh["id"], order["id"], staff_headers), 200)
        assert order_short["status"] == "SHORT_PICKED"
        # Pack with allow_partial=true
        packed = validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(allow_partial=True),
            staff_headers), 200)
        assert packed["status"] == "PACKED"
        assert packed["final_carton_count"] is not None


class TestShip:
    def test_ship_packed_order_mints_label_and_tracking(self, api, staff_headers):
        """PRD §3.7: "On a successful ship the system mints a shipping_label_id
        (formatted as lbl_<uuid>) and a tracking_number whose prefix is
        taken from the order's carrier: a UPS order gets a 1Z-prefixed
        tracking number, a FEDEX order gets an FX-prefixed tracking number,
        and a USPS order gets a US-prefixed tracking number, each followed
        by a sequence string."

        Claim: ship on PACKED order → SHIPPED with shipping_label_id
        starting "lbl_" and tracking_number with carrier-specific prefix.
        """
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=5)
        validate_success(api.complete_pick_task(
            wh["id"], pt["id"], create_pick_complete_payload(5), staff_headers), 200)
        validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff_headers), 200)
        shipped = validate_success(api.ship_order(
            wh["id"], order["id"], staff_headers), 200)
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipping_label_id"].startswith("lbl_")
        assert shipped["tracking_number"].startswith("1Z")  # UPS

    @pytest.mark.parametrize("carrier,prefix", [
        ("UPS", "1Z"),
        ("FEDEX", "FX"),
        ("USPS", "US"),
    ])
    def test_tracking_prefix_per_carrier(self, api, staff_headers, carrier, prefix):
        """PRD §3.7: "a UPS order gets a 1Z-prefixed tracking number, a
        FEDEX order gets an FX-prefixed tracking number, and a USPS order
        gets a US-prefixed tracking number"

        Claim: tracking_number prefix matches the order's carrier.
        """
        from test_helpers import setup_picking_pick_task
        wh, b, lot, order, wave, pt = setup_picking_pick_task(order_qty=3)
        # The default order carrier is UPS in setup_picking_pick_task — we need an
        # order with explicit carrier. Reset:
        wh2, b2, lot2 = setup_warehouse_with_inventory(units=10, sku="PEN")
        order2 = validate_success(api.create_order(
            wh2["id"],
            create_order_payload(
                requested_lines=[{"sku": "PEN", "qty_units": 3}],
                order_number=f"ORD-{carrier}", carrier=carrier),
            staff_headers), 201)
        validate_success(api.allocate_order(wh2["id"], order2["id"], staff_headers), 200)
        wave2 = setup_released_wave_for_order(wh2["id"], order2["id"], wave_code=f"WV-{carrier}")
        pts2 = get_pick_tasks_for_order(wh2["id"], order2["id"])
        validate_success(api.start_pick_task(wh2["id"], pts2[0]["id"], staff_headers), 200)
        validate_success(api.complete_pick_task(
            wh2["id"], pts2[0]["id"], create_pick_complete_payload(3),
            staff_headers), 200)
        validate_success(api.pack_order(
            wh2["id"], order2["id"], create_pack_payload(), staff_headers), 200)
        shipped = validate_success(api.ship_order(
            wh2["id"], order2["id"], staff_headers), 200)
        assert shipped["tracking_number"].startswith(prefix), \
            f"Carrier {carrier} should produce {prefix}-prefixed tracking, got {shipped['tracking_number']}"

    def test_ship_debits_inventory(self, api, staff_headers):
        """PRD §3.7: "Shipping also debits the warehouse's inventory: for
        each PICKED pick task of the order, the source inventory row's
        qty_units is decreased by picked_units and the same row's
        reserved_units is decreased by the same picked_units, atomically"

        Claim: after ship, the source inventory row's qty_units has
        decreased by the picked amount.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        from test_helpers import get_inventory_row
        inv_initial = get_inventory_row(wh["id"], b["id"], lot["id"])
        order = create_allocated_order(wh["id"], sku="PEN", qty_units=10,
                                       order_number="ORD-SHIP")
        wave = setup_released_wave_for_order(wh["id"], order["id"], wave_code="WV-SHIP")
        pts = get_pick_tasks_for_order(wh["id"], order["id"])
        validate_success(api.start_pick_task(wh["id"], pts[0]["id"], staff_headers), 200)
        validate_success(api.complete_pick_task(
            wh["id"], pts[0]["id"], create_pick_complete_payload(10), staff_headers), 200)
        validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff_headers), 200)
        validate_success(api.ship_order(
            wh["id"], order["id"], staff_headers), 200)
        inv_final = get_inventory_row(wh["id"], b["id"], lot["id"])
        assert inv_final["qty_units"] == inv_initial["qty_units"] - 10
        assert inv_final["reserved_units"] == 0


class TestShipLotStatusCheck:
    def test_ship_blocked_when_picked_lot_recalled(self, api, staff_headers, manager_headers):
        """PRD §3.7: "Shipping the order moves it from PACKED to SHIPPED
        and enforces one further safety check: no lot referenced by any
        PICKED pick task on this order may be in RECALLED, EXPIRED, or
        QUARANTINED (otherwise ERR_LOT_NOT_SHIPPABLE)."

        Claim: with order PACKED, recalling the picked lot then attempting
        ship → ERR_LOT_NOT_SHIPPABLE.
        """
        wh, b, lot = setup_warehouse_with_inventory(units=50, sku="PEN")
        order = create_allocated_order(wh["id"], sku="PEN", qty_units=10,
                                       order_number="ORD-SHIP-RC")
        wave = setup_released_wave_for_order(wh["id"], order["id"], wave_code="WV-SR")
        pts = get_pick_tasks_for_order(wh["id"], order["id"])
        validate_success(api.start_pick_task(wh["id"], pts[0]["id"], staff_headers), 200)
        validate_success(api.complete_pick_task(
            wh["id"], pts[0]["id"], create_pick_complete_payload(10), staff_headers), 200)
        validate_success(api.pack_order(
            wh["id"], order["id"], create_pack_payload(), staff_headers), 200)
        # Now recall the lot
        from test_helpers import create_recall_payload
        validate_success(api.recall_lot(
            wh["id"], lot["id"], create_recall_payload("SAFETY_ISSUE"),
            TEST_USERS["manager_headers"]), 200)
        validate_error(api.ship_order(
            wh["id"], order["id"], staff_headers), "ERR_LOT_NOT_SHIPPABLE")
