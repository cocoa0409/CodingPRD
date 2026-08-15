"""Shipments, cold-chain temperature control, and quarantine disposition
(PRD §3.7, §2.10)."""
from test_helpers import (
    ACCOUNT_MANAGER,
    OFFICER,
    PLANNER,
    ApiErrorId,
    assert_lot_conservation,
    create_active_clinic,
    create_approved_order,
    create_product,
    create_shipment,
    create_stocked_product,
    create_submitted_order,
    deliver_shipment,
    dispatch_shipment,
    get_clinic,
    get_lot,
    get_order,
    get_shipment,
    get_success_data,
    order_line_spec,
    post_temperature_reading,
    sole_backorder,
    sole_line,
    validate_error,
    validate_success,
)


def _approved_vaccine_order(api, *, clinic_name, license_number, ship_to,
                            qty=2, lot_qty=10, price=5000):
    """ACTIVE clinic + VACCINE product + lot + APPROVED order (cold chain)."""
    clinic = create_active_clinic(clinic_name=clinic_name,
                                  license_number=license_number,
                                  ship_to_address=ship_to,
                                  free_freight_threshold_cents=75000)
    product, lot = create_stocked_product(
        lot_qty=lot_qty,
        product_overrides={"product_type": "VACCINE", "unit_price_cents": price})
    order = create_approved_order(clinic["id"], product["id"], qty)
    assert order["status"] == "APPROVED"
    return clinic, product, lot, order


def _in_transit_cold_shipment(api, *, clinic_name, license_number, ship_to,
                              qty=2, lot_qty=10, price=5000):
    """Approved vaccine order + certified shipment dispatched (IN_TRANSIT)."""
    clinic, product, lot, order = _approved_vaccine_order(
        api, clinic_name=clinic_name, license_number=license_number,
        ship_to=ship_to, qty=qty, lot_qty=lot_qty, price=price)
    shipment = create_shipment(order["id"], carrier_name="CHILLCARE",
                               certified=True)
    assert shipment["requires_cold_chain"] is True
    dispatch_shipment(shipment["id"])
    return clinic, product, lot, order, get_shipment(shipment["id"])


class TestShipmentCreate:
    def test_shipment_create_requires_approved_order(self, api):
        """PRD §3.7: "A `SupplyChainPlanner` creates a shipment against an
        `APPROVED` order — any other order state fails with
        `ERR_ORDER_INVALID_STATE`..."
        PRD §3.5: "when at least one line went to backorder, it moves
        `SUBMITTED` → `BACKORDERED` instead"

        Design: Corner/state_machines/shipment_create_requires_approved_order
        """
        clinic = create_active_clinic(clinic_name="Clinic SC",
                                      license_number="LIC-SC")
        product = create_product(sku="CONS-SC", product_name="Syringe 1ml")
        # qty 2: net 2*2500 = 5000 meets the default minimum exactly, so the
        # submit gate passes and the order can be approved into shortage.
        # No stock: approval lands BACKORDERED.
        order = create_approved_order(clinic["id"], product["id"], 2)
        assert order["status"] == "BACKORDERED"

        resp = api.create_shipment(
            {"order_id": order["id"], "carrier_name": "VETEXPRESS"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)

    def test_cold_chain_carrier_required(self, api):
        """PRD §3.7: "The shipment's `requires_cold_chain` is computed per
        §2.10, and when it is true the carrier must be declared certified: a
        cold-chain shipment without `carrier_cold_chain_certified` set is
        rejected with `ERR_COLD_CHAIN_CARRIER_REQUIRED`."
        PRD §3.7: "...optionally `carrier_cold_chain_certified`, which defaults
        to false."

        Design: Corner/validations/cold_chain_carrier_required
        """
        clinic, _product, _lot, order = _approved_vaccine_order(
            api, clinic_name="Clinic CC", license_number="LIC-CC",
            ship_to="53 Cold Ct", qty=1, lot_qty=5)

        resp = api.create_shipment(
            {"order_id": order["id"], "carrier_name": "CHEAPHAUL"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_CARRIER_REQUIRED)


class TestDispatchAndDeliver:
    def test_shipment_dispatch_side_effects_debit_lot(self, api):
        """PRD §3.7: "Dispatch moves a `PREPARING` shipment to `IN_TRANSIT`
        (from any other state, `ERR_SHIPMENT_INVALID_STATE`) and settles the
        warehouse books in the same breath: every `ALLOCATED` line of the order
        moves to `SHIPPED`, and for each line the covering lot's `qty_on_hand`
        and `qty_allocated` are both decremented by the line's `qty_requested`,
        preserving the conservation invariant of §3.2. The order itself moves
        from `APPROVED` to `SHIPPED`."

        Design: Corner/endpoints/shipment_dispatch_side_effects_debit_lot
        """
        clinic = create_active_clinic(clinic_name="Clinic SD",
                                      license_number="LIC-SD")
        product, lot = create_stocked_product(
            product_overrides={"sku": "CONS-SD", "product_name": "Ear Cleaner"})
        order = create_approved_order(clinic["id"], product["id"], 2)
        shipment = create_shipment(order["id"])

        dispatched = validate_success(api.dispatch_shipment(shipment["id"], PLANNER))
        assert dispatched["status"] == "IN_TRANSIT"

        line = sole_line(order["id"])
        assert line["status"] == "SHIPPED"
        assert get_order(order["id"])["status"] == "SHIPPED"

        lot_after = get_lot(lot["id"])
        assert (lot_after["qty_on_hand"], lot_after["qty_allocated"],
                lot_after["qty_available"]) == (8, 0, 8), (
            "Dispatch converts reservation into outbound stock: 10 - 2 shipped")
        assert_lot_conservation(lot_after)

    def test_shipment_deliver_from_preparing_rejected(self, api):
        """PRD §3.7: "a `SupplyChainPlanner` delivers an `IN_TRANSIT` shipment
        (otherwise `ERR_SHIPMENT_INVALID_STATE`)..."
        PRD §3.7: "A new shipment starts `PREPARING`..."

        Design: Corner/state_machines/shipment_deliver_from_preparing_rejected
        """
        clinic = create_active_clinic(clinic_name="Clinic SH",
                                      license_number="LIC-SH")
        product, _lot = create_stocked_product(
            product_overrides={"sku": "CONS-SH", "product_name": "Swab Box"})
        # qty 2: net 2*2500 = 5000 meets the default minimum exactly.
        order = create_approved_order(clinic["id"], product["id"], 2)
        shipment = create_shipment(order["id"])
        assert shipment["status"] == "PREPARING"
        assert shipment["requires_cold_chain"] is False, (
            "No VACCINE lines -> ambient shipment")

        resp = api.deliver_shipment(shipment["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_INVALID_STATE)
        assert get_shipment(shipment["id"])["status"] == "PREPARING"


class TestTemperatureLog:
    def test_temperature_log_not_applicable_for_ambient_shipment(self, api):
        """PRD §3.7: "Readings are accepted only for a shipment whose
        `requires_cold_chain` is true — posting to a non-cold-chain shipment
        fails with `ERR_TEMPERATURE_LOG_NOT_APPLICABLE` — and only while
        `IN_TRANSIT`, otherwise `ERR_SHIPMENT_INVALID_STATE`."

        Design: Corner/validations/temperature_log_not_applicable_for_ambient_shipment
        """
        clinic = create_active_clinic(clinic_name="Clinic TA",
                                      license_number="LIC-TA")
        product, _lot = create_stocked_product(
            lot_qty=5,
            product_overrides={"sku": "CONS-TA", "product_name": "Pellet Bag"})
        # qty 2: net 2*2500 = 5000 meets the default minimum exactly.
        order = create_approved_order(clinic["id"], product["id"], 2)
        shipment = create_shipment(order["id"])
        assert shipment["requires_cold_chain"] is False
        dispatch_shipment(shipment["id"])

        resp = api.add_temperature_reading(
            shipment["id"],
            {"recorded_at": "2026-08-03T14:00:00Z", "temperature_celsius": 5.0},
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_TEMPERATURE_LOG_NOT_APPLICABLE)
        after = get_shipment(shipment["id"])
        assert after["status"] == "IN_TRANSIT"
        assert after["temperature_log"] == []

    def test_temperature_inclusive_bounds_accepted(self, api):
        """PRD §2.10: "A reading is in range exactly when it lies between 2.0
        and 8.0 degrees Celsius inclusive — a reading of exactly 2.0 or exactly
        8.0 is acceptable, and anything strictly outside that band is an
        excursion that automatically quarantines the shipment."

        Design: Difficulty/boundary_precision_check/temperature_inclusive_range_boundary
        """
        (_clinic, _product, _lot, _order,
         shipment) = _in_transit_cold_shipment(
            api, clinic_name="Clinic V", license_number="LIC-V1",
            ship_to="14 Bit Blvd")
        assert shipment["requires_cold_chain"] is True, (
            "Computed from the VACCINE line per PRD §2.10")

        low = validate_success(api.add_temperature_reading(
            shipment["id"],
            {"recorded_at": "2026-08-03T14:00:00Z", "temperature_celsius": 2.0},
            PLANNER), 201)
        assert low["status"] == "IN_TRANSIT", (
            "2.0 is the inclusive lower bound")
        assert low["has_unresolved_excursion"] is False

        high = validate_success(api.add_temperature_reading(
            shipment["id"],
            {"recorded_at": "2026-08-03T15:00:00Z", "temperature_celsius": 8.0},
            PLANNER), 201)
        assert high["status"] == "IN_TRANSIT", (
            "8.0 is the inclusive upper bound")
        assert high["has_unresolved_excursion"] is False

    def test_temperature_above_bound_quarantines_and_log_appends(self, api):
        """PRD §2.10: "A reading is in range exactly when it lies between 2.0
        and 8.0 degrees Celsius inclusive — a reading of exactly 2.0 or exactly
        8.0 is acceptable, and anything strictly outside that band is an
        excursion that automatically quarantines the shipment."
        PRD §3.7: "each reading supplies a `recorded_at` instant and a
        `temperature_celsius` value and is appended to the shipment's
        `temperature_log`, an append-only embedded record returned with the
        shipment."

        Design: Difficulty/boundary_precision_check/temperature_inclusive_range_boundary
        """
        (_clinic, _product, _lot, _order,
         shipment) = _in_transit_cold_shipment(
            api, clinic_name="Clinic V2", license_number="LIC-V2",
            ship_to="14 Bit Blvd")
        sid = shipment["id"]

        post_temperature_reading(sid, 2.0, recorded_at="2026-08-03T14:00:00Z")
        post_temperature_reading(sid, 8.0, recorded_at="2026-08-03T15:00:00Z")
        over = validate_success(api.add_temperature_reading(
            sid,
            {"recorded_at": "2026-08-03T16:00:00Z", "temperature_celsius": 8.1},
            PLANNER), 201)
        assert over["status"] == "QUARANTINED", (
            "8.1 is strictly outside the band -> excursion")
        assert over["has_unresolved_excursion"] is True

        log = over["temperature_log"]
        assert [r["temperature_celsius"] for r in log] == [2.0, 8.0, 8.1], (
            "Readings append in posted order")


class TestQuarantineDisposition:
    def test_quarantine_release_then_deliver_happy_path(self, api):
        """PRD §3.7: "`RELEASED` returns the shipment to `IN_TRANSIT` and clears
        `has_unresolved_excursion` — it is the only way that flag clears."
        PRD §3.7: "a `SupplyChainPlanner` delivers an `IN_TRANSIT` shipment
        (otherwise `ERR_SHIPMENT_INVALID_STATE`), moving it to `DELIVERED`,
        moving every `SHIPPED` line to `DELIVERED`, moving the order from
        `SHIPPED` to `DELIVERED`, and recomputing the clinic's credit exposure
        as the order leaves the counted set."
        PRD §2.9: "`credit_used_cents` is the sum of `total_cents` over the
        clinic's orders in `APPROVED`, `BACKORDERED`, or `SHIPPED` status."

        Design: Corner/state_machines/quarantine_release_then_deliver_happy_path
        """
        (clinic, _product, _lot, order,
         shipment) = _in_transit_cold_shipment(
            api, clinic_name="Clinic QR", license_number="LIC-QR",
            ship_to="32 Quar Quay", qty=2)
        quarantined = post_temperature_reading(shipment["id"], 9.5)
        assert quarantined["status"] == "QUARANTINED", "excursion sanity"

        released = validate_success(
            api.resolve_quarantine(shipment["id"], "RELEASED", OFFICER))
        assert released["status"] == "IN_TRANSIT"
        assert released["has_unresolved_excursion"] is False

        delivered = validate_success(api.deliver_shipment(shipment["id"], PLANNER))
        assert delivered["status"] == "DELIVERED"
        assert get_order(order["id"])["status"] == "DELIVERED"
        assert get_clinic(clinic["id"])["credit_used_cents"] == 0, (
            "The order left the counted set at delivery")

    def test_quarantine_destroy_reorders_and_backorders(self, api):
        """PRD §3.7: "`DESTROYED` is terminal and fires a two-level cascade:
        every `SHIPPED` line of the order moves back to `BACKORDERED`, the
        destroyed goods are not returned to stock — `qty_on_hand` is not
        restored — a fresh BackorderLine is minted per line for the full
        `qty_requested` with a fresh `allocation_sequence`, the order moves from
        `SHIPPED` back to `BACKORDERED`, and the clinic's `credit_used_cents` is
        recomputed as the order re-enters the counted set."

        Design: Corner/state_machines/quarantine_destroy_reorders_and_backorders
        """
        (clinic, _product, lot, order,
         shipment) = _in_transit_cold_shipment(
            api, clinic_name="Clinic QD", license_number="LIC-QD",
            ship_to="33 Destroy Dr", qty=2, lot_qty=10)
        post_temperature_reading(shipment["id"], 1.0)

        destroyed = validate_success(
            api.resolve_quarantine(shipment["id"], "DESTROYED", OFFICER))
        assert destroyed["status"] == "DESTROYED"

        line = sole_line(order["id"])
        assert line["status"] == "BACKORDERED"
        backorder = sole_backorder(line["id"])
        assert backorder["status"] == "OPEN"
        assert backorder["qty_open"] == 2

        assert get_order(order["id"])["status"] == "BACKORDERED"

        lot_after = get_lot(lot["id"])
        assert lot_after["qty_on_hand"] == 8, (
            "The 2 destroyed units are not returned to stock")
        assert lot_after["qty_allocated"] == 0
        assert lot_after["qty_available"] == 8
        assert_lot_conservation(lot_after)

        # The order re-entered the counted set as BACKORDERED:
        # net 10000 + freight 2500 = 12500.
        assert get_clinic(clinic["id"])["credit_used_cents"] == 12500

    def test_quarantined_shipment_cannot_deliver(self, api):
        """PRD §3.7: "Quarantine ends only by a `ComplianceOfficer`'s quality
        disposition, which supplies an `outcome` of `RELEASED` or `DESTROYED`;
        disposition from any state other than `QUARANTINED` fails with
        `ERR_SHIPMENT_INVALID_STATE`."
        PRD §3.7: "a `SupplyChainPlanner` delivers an `IN_TRANSIT` shipment
        (otherwise `ERR_SHIPMENT_INVALID_STATE`)..."

        Design: Corner/validations/quarantined_shipment_cannot_deliver
        """
        (_clinic, _product, _lot, _order,
         shipment) = _in_transit_cold_shipment(
            api, clinic_name="Clinic QL", license_number="LIC-QL",
            ship_to="55 Quar Ln", qty=1, lot_qty=5)
        post_temperature_reading(shipment["id"], 12.0)

        resp = api.deliver_shipment(shipment["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_INVALID_STATE)
        assert get_shipment(shipment["id"])["status"] == "QUARANTINED"
