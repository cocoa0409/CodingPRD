"""Warehousing: zone receiving budgets, pallet ceilings, damage write-offs,
the physical-unit conservation invariant, FIFO allocation, backorder sweeps,
and shipment state rules."""
from test_helpers import (
    ApiErrorId,
    assert_lot_invariants,
    assert_shipment,
    create_customer,
    create_inventory_lot,
    create_shipment_payload,
    receive_stock,
    set_clock,
    setup_world,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BILLING, CSR, WH


class TestZoneReceivingCapacity:
    def test_zone_daily_pallet_aggregate_overflow(self, api):
        """PRD §3.8: "the event's pallet count — its quantity divided by the
        release format's units-per-pallet, rounded up — plus the pallets of
        every other `RECEIVE` into the same zone on the same date may not
        exceed the zone's daily budget of 40 pallets for zone `A`, 25 for `B`,
        and 15 for `C`, or the event is rejected with
        `ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/zone_daily_pallet_aggregate_capacity
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="C")

        # 1000 LP units = 10 pallets <= 15.
        after1 = receive_stock(lot["id"], 1000, event_date="2026-08-01")
        assert after1["on_hand_units"] == 1000

        # +600 units = +6 pallets -> 16 > 15 on the same date.
        resp = api.post_stock_event(
            lot["id"],
            {"event": "RECEIVE", "quantity": 600, "event_date": "2026-08-01"},
            WH,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED)

    def test_zone_daily_pallet_next_day_passes(self, api):
        """PRD §3.8: "the event's pallet count — its quantity divided by the
        release format's units-per-pallet, rounded up — plus the pallets of
        every other `RECEIVE` into the same zone on the same date may not
        exceed the zone's daily budget of 40 pallets for zone `A`, 25 for `B`,
        and 15 for `C`, or the event is rejected with
        `ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/zone_daily_pallet_aggregate_capacity
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="C")
        receive_stock(lot["id"], 1000, event_date="2026-08-01")

        # A fresh date has a fresh daily budget.
        after2 = receive_stock(lot["id"], 600, event_date="2026-08-02")
        assert after2["on_hand_units"] == 1600

    def test_pallet_ceil_and_zone_inclusive_boundary(self, api):
        """PRD §3.8: "the event's pallet count — its quantity divided by the
        release format's units-per-pallet, rounded up — plus the pallets of
        every other `RECEIVE` into the same zone on the same date may not
        exceed the zone's daily budget of 40 pallets for zone `A`, 25 for `B`,
        and 15 for `C`, or the event is rejected with
        `ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED`."

        Design: Corner/calculations/pallet_ceil_and_zone_inclusive_boundary
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="C")

        receive_stock(lot["id"], 1400, event_date="2026-08-01")  # 14 pallets
        # +100 units = ceil(100/100) = 1 pallet -> exactly 15 == cap.
        after = receive_stock(lot["id"], 100, event_date="2026-08-01")
        assert after["on_hand_units"] == 1500, (
            "15 pallets at the 15-pallet cap must be allowed (inclusive boundary)"
        )

        # +1 unit still costs a full pallet (ceil) -> 16 > 15.
        resp = api.post_stock_event(
            lot["id"],
            {"event": "RECEIVE", "quantity": 1, "event_date": "2026-08-01"},
            WH,
        )
        validate_error(resp, ApiErrorId.ERR_ZONE_RECEIVING_CAPACITY_EXCEEDED)


class TestDamageWriteOff:
    def test_damage_writeoff_exceeds_on_hand(self, api):
        """PRD §3.8: "A `DAMAGE_WRITE_OFF` event removes `quantity` units from
        `on_hand_units` into `damaged_units_cum` and may not exceed the units
        on hand (`ERR_INVALID_REQUEST`)."
        PRD §3.8: "One invariant anchors the lot forever: units received always
        equal units on hand plus units allocated plus units shipped plus units
        damaged."

        Design: Corner/validations/damage_writeoff_exceeds_on_hand
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="A")
        receive_stock(lot["id"], 300, event_date="2026-08-01")

        resp = api.post_stock_event(
            lot["id"],
            {"event": "DAMAGE_WRITE_OFF", "quantity": 301,
             "event_date": "2026-08-01"},
            WH,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        after = validate_success(
            api.post_stock_event(
                lot["id"],
                {"event": "DAMAGE_WRITE_OFF", "quantity": 300,
                 "event_date": "2026-08-01"},
                WH,
            ),
            200,
        )
        assert after["on_hand_units"] == 0
        assert after["damaged_units_cum"] == 300
        assert_lot_invariants(after)


class TestInventoryConservation:
    def _lot_with_1000(self, world):
        lot = create_inventory_lot(world["release"]["id"], zone="A")
        return receive_stock(lot["id"], 1000, event_date="2026-08-01")

    def test_inventory_conservation_allocate_deallocate(self, api):
        """PRD §3.8: "One invariant anchors the lot forever: units received
        always equal units on hand plus units allocated plus units shipped
        plus units damaged."
        PRD §3.8: "cancelling an allocated shipment deallocates its quantities
        back to `on_hand_units` and runs the sweep again"

        Design: Difficulty/compensating_invariant/inventory_units_roundtrip_conservation
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = self._lot_with_1000(world)
        dist = create_customer(name="CI2 Dist", contact_email="ci2d@x.com",
                               credit_limit_cents=100000000)

        ship = validate_success(
            api.create_shipment(
                create_shipment_payload(world["release"]["id"], dist["id"],
                                        quantity=300),
                CSR,
            ),
            201,
        )
        assert ship["status"] == "ALLOCATED"
        mid = validate_success(api.get_inventory_lot(lot["id"], CSR), 200)
        assert mid["on_hand_units"] == 700
        assert mid["allocated_units"] == 300
        assert_lot_invariants(mid)

        validate_success(
            api.cancel_shipment(ship["id"], {"reason": "changed mind"}, CSR), 200
        )
        restored = validate_success(api.get_inventory_lot(lot["id"], CSR), 200)
        assert restored["on_hand_units"] == 1000, (
            "cancellation must fully reverse the allocation"
        )
        assert restored["allocated_units"] == 0
        assert_lot_invariants(restored)

    def test_inventory_conservation_ship_and_damage(self, api):
        """PRD §3.8: "One invariant anchors the lot forever: units received
        always equal units on hand plus units allocated plus units shipped
        plus units damaged."
        PRD §3.8: "shipping settles the lots: each allocated quantity leaves
        `allocated_units` and accrues into `shipped_units_cum`"

        Design: Difficulty/compensating_invariant/inventory_units_roundtrip_conservation
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = self._lot_with_1000(world)
        dist = create_customer(name="CI2 Dist", contact_email="ci2d@x.com",
                               credit_limit_cents=100000000)

        ship = validate_success(
            api.create_shipment(
                create_shipment_payload(world["release"]["id"], dist["id"],
                                        quantity=200),
                CSR,
            ),
            201,
        )
        picked = validate_success(api.advance_shipment(ship["id"], WH), 200)
        assert picked["status"] == "PICKED"
        shipped = validate_success(api.advance_shipment(ship["id"], WH), 200)
        assert shipped["status"] == "SHIPPED"

        validate_success(
            api.post_stock_event(
                lot["id"],
                {"event": "DAMAGE_WRITE_OFF", "quantity": 50,
                 "event_date": "2026-08-02"},
                WH,
            ),
            200,
        )
        final = validate_success(api.get_inventory_lot(lot["id"], CSR), 200)
        assert final["on_hand_units"] == 750
        assert final["allocated_units"] == 0
        assert final["shipped_units_cum"] == 200
        assert final["damaged_units_cum"] == 50
        assert final["received_units_cum"] == 1000
        assert_lot_invariants(final)


class TestShipmentAllocationGate:
    def _release_with_stock(self, units: int):
        world = setup_world(with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="A")
        receive_stock(lot["id"], units, event_date="2026-08-01")
        dist = create_customer(name="XS3 Dist", contact_email="dist@x.com",
                               credit_limit_cents=100000000)
        return world, lot, dist

    def test_shipment_planned_when_stock_short(self, api):
        """PRD §3.8: "Allocation is FIFO and all-or-nothing at creation: the
        candidate lots are the release's lots with positive `on_hand_units`,
        ordered by `created_at` ascending and then `receipt_seq` ascending —
        never by identifier — and if the total on hand across those lots is
        less than the shipment's quantity, the shipment stays `PLANNED` with
        empty `allocations`"

        Design: Difficulty/cross_entity_state_dependency/shipment_allocation_gated_by_inventory
        """
        world, _lot, dist = self._release_with_stock(300)
        resp = api.create_shipment(
            create_shipment_payload(world["release"]["id"], dist["id"],
                                    quantity=500),
            CSR,
        )
        ship = validate_success(resp, 201)
        assert_shipment(ship)
        assert ship["status"] == "PLANNED", (
            "300 available < 500 requested must stay PLANNED (all-or-nothing)"
        )
        assert ship["allocations"] == []

    def test_shipment_swept_to_allocated_on_receipt(self, api):
        """PRD §3.8: "The same allocator runs as a sweep whenever stock arrives
        or is freed: the release's `PLANNED` shipments are walked in
        `created_at` ascending, each is allocated in full while it fits, and
        shipments that do not fit are skipped without blocking later ones."
        PRD §3.8: "otherwise the system builds the `allocations` array of
        lot-and-quantity pairs (splitting across lots as needed), moves the
        shipment straight to `ALLOCATED`, and shifts each allocated quantity
        from `on_hand_units` to `allocated_units` on its lot."

        Design: Difficulty/cross_entity_state_dependency/shipment_allocation_gated_by_inventory
        """
        world, lot, dist = self._release_with_stock(300)
        ship = validate_success(
            api.create_shipment(
                create_shipment_payload(world["release"]["id"], dist["id"],
                                        quantity=500),
                CSR,
            ),
            201,
        )
        assert ship["status"] == "PLANNED"

        # Receipt lifts availability to 600 >= 500; the sweep promotes it.
        receive_stock(lot["id"], 300, event_date="2026-08-01")
        after = validate_success(api.get_shipment(ship["id"], CSR), 200)
        assert after["status"] == "ALLOCATED"
        assert after["allocations"] == [{"lot_id": lot["id"], "quantity": 500}]

        lot_after = validate_success(api.get_inventory_lot(lot["id"], CSR), 200)
        assert lot_after["on_hand_units"] == 100
        assert lot_after["allocated_units"] == 500
        assert_lot_invariants(lot_after)


class TestShipmentStates:
    def test_shipment_cancel_then_advance_rejected(self, api):
        """PRD §3.8: "Cancellation is possible from `PLANNED` or `ALLOCATED`"
        PRD §3.8: "Wrong-state advances or cancellations are
        `ERR_SHIPMENT_INVALID_STATE`."

        Design: Corner/state_machines/shipment_cancel_then_advance_rejected
        """
        world = setup_world(with_line=False, with_bath=False)
        # No stock: the shipment is created PLANNED.
        ship = validate_success(
            api.create_shipment(
                create_shipment_payload(world["release"]["id"],
                                        world["customer"]["id"], quantity=500),
                CSR,
            ),
            201,
        )
        assert ship["status"] == "PLANNED"

        cancelled = validate_success(
            api.cancel_shipment(ship["id"], {"reason": "x"}, CSR), 200
        )
        assert cancelled["status"] == "CANCELLED"

        r1 = api.advance_shipment(ship["id"], WH)
        validate_error(r1, ApiErrorId.ERR_SHIPMENT_INVALID_STATE)
        r2 = api.cancel_shipment(ship["id"], {"reason": "again"}, CSR)
        validate_error(r2, ApiErrorId.ERR_SHIPMENT_INVALID_STATE)

    def test_suspended_distributor_blocks_shipment(self, api):
        """PRD §3.8: "the distributor must be `ACTIVE`
        (`ERR_CUSTOMER_SUSPENDED`)"

        Design: Corner/validations/suspended_distributor_blocks_shipment
        """
        world = setup_world(with_line=False, with_bath=False)
        lot = create_inventory_lot(world["release"]["id"], zone="A")
        receive_stock(lot["id"], 500, event_date="2026-08-01")
        dist = create_customer(name="V9 Dist", contact_email="v9d@x.com",
                               credit_limit_cents=100000000)
        validate_success(
            api.set_credit_status(dist["id"], {"action": "SUSPEND"}, BILLING), 200
        )

        resp = api.create_shipment(
            create_shipment_payload(world["release"]["id"], dist["id"],
                                    quantity=100),
            CSR,
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_SUSPENDED)

        shipments = validate_success(api.list_shipments(CSR), 200)
        assert shipments == [], "a rejected shipment must not be created"
