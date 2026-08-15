"""Shipments and the freight tariff: dual-variant pricing, tiered discount,
pooled air capacity, and delivery into the shipped bucket."""
import pytest

from test_helpers import (
    api_client,
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    assert_kg,
    assert_lot_buckets,
    create_species,
    create_and_publish_quote,
    create_customer,
    setup_confirmed_order,
    create_shipment,
    get_shipment,
    setup_committed_allocation,
    get_lot,
    get_order,
)

OM = TEST_USERS["operations_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


def _confirmed_order(credit_limit_cents=1000000, qty_kg=10.00,
                     price_per_kg_cents=1200):
    """Species + published quote + customer + a CONFIRMED one-line order."""
    species = create_species(species_code="COD")
    create_and_publish_quote(species["id"], grade="GRADE_A",
                             price_per_kg_cents=price_per_kg_cents)
    customer = create_customer(credit_limit_cents=credit_limit_cents)
    return setup_confirmed_order(
        customer, [{"species_id": species["id"], "requested_qty_kg": qty_kg}])


class TestFreightDualVariant:
    """Provisional freight at book vs final freight at tender."""

    def test_provisional_booked_vs_final_tendered(self, api):
        """PRD §3.7: "At booking, `chargeable_weight_kg` is set to the `booked_weight_kg` — the dimensional term is zero at this stage — and `provisional_freight_cents` is computed from it under the tariff below. Tendering a `BOOKED` shipment records the tendered `actual_weight_kg` and `volume_m3` and reprices finally: `chargeable_weight_kg` becomes the greater of the actual weight and the dimensional weight, where the dimensional weight is the volume in cubic meters multiplied by 167 and rounded half up to two decimal places, and `final_freight_cents` overwrites the estimate."
        PRD §3.7: "Because the provisional variant prices the booked mass while the final variant prices the greater of actual and dimensional weight, identical mass can price differently once volume is known."

        Design: Difficulty/dual_variant_calc/freight_provisional_vs_final
        """
        order_ctx = _confirmed_order()
        shipment = create_shipment(order_ctx["order"]["id"], mode="AIR",
                                   booked_weight_kg=16.70, temp_zone="CHILLED",
                                   flight_number="FL100", flight_date="2026-08-03")

        booked = validate_success(api_client.book_shipment(shipment["id"], LC))
        # AIR 16.70 kg: 5000 + 5344 = 10344 >= 10000 -> 9827; fuel 1179.
        assert booked["provisional_freight_cents"] == 11006
        assert_kg(booked["chargeable_weight_kg"], 16.70, "chargeable at book")

        tendered = validate_success(api_client.tender_shipment(
            shipment["id"], {"actual_weight_kg": 12.00, "volume_m3": 0.05}, LC))
        # chargeable = max(12.00, round(0.05 x 167, 2) = 8.35) = 12.00;
        # subtotal 8840 (< 10000, no tier); fuel round(8840 x 0.12) = 1061.
        assert_kg(tendered["chargeable_weight_kg"], 12.00, "chargeable at tender")
        assert tendered["final_freight_cents"] == 9901
        assert tendered["final_freight_cents"] != booked["provisional_freight_cents"]

    def test_final_variant_uses_dimensional_weight_when_greater(self, api):
        """PRD §3.7: "Tendering a `BOOKED` shipment records the tendered `actual_weight_kg` and `volume_m3` and reprices finally: `chargeable_weight_kg` becomes the greater of the actual weight and the dimensional weight, where the dimensional weight is the volume in cubic meters multiplied by 167 and rounded half up to two decimal places, and `final_freight_cents` overwrites the estimate."

        Design: Difficulty/dual_variant_calc/freight_provisional_vs_final
        """
        order_ctx = _confirmed_order()
        shipment = create_shipment(order_ctx["order"]["id"], mode="TRUCK",
                                   booked_weight_kg=10.00, temp_zone="FROZEN")
        booked = validate_success(api_client.book_shipment(shipment["id"], LC))
        # TRUCK 10.00 kg: 2500 + 1400 = 3900; fuel 468; total 4368.
        assert booked["provisional_freight_cents"] == 4368

        tendered = validate_success(api_client.tender_shipment(
            shipment["id"], {"actual_weight_kg": 10.00, "volume_m3": 0.20}, LC))
        # chargeable = max(10.00, round(0.20 x 167, 2) = 33.40) = 33.40;
        # subtotal 2500 + 4676 = 7176; fuel round(7176 x 0.12) = 861.
        assert_kg(tendered["chargeable_weight_kg"], 33.40,
                  "dimensional weight exceeds actual")
        assert tendered["final_freight_cents"] == 8037


class TestFreightTierAndFloor:
    """The five-step pinned evaluation order of the freight tariff."""

    def test_discount_tier_keys_on_prediscount_subtotal(self, api):
        """PRD §3.7: "Third, the discount test is keyed on the pre-discount subtotal: when that subtotal is at least 10000 cents, a five percent discount applies, and the tier still counts even when applying the discount would pull the result below the threshold; the discounted amount is the subtotal reduced by five percent, rounded half up to whole cents. Fourth, the fuel surcharge is twelve percent of the discounted amount — keyed on the discounted figure, not the original subtotal — rounded half up to whole cents. Fifth and last, the freight charge is the greater of 4000 cents and the sum of the discounted amount and the fuel surcharge: the minimum charge binds exactly there."

        Design: Difficulty/combinatorial_formula/freight_tier_keyed_on_prediscount_subtotal
        """
        order_ctx = _confirmed_order()
        shipment = create_shipment(order_ctx["order"]["id"], mode="TRUCK",
                                   booked_weight_kg=55.00, temp_zone="FROZEN")
        get_success_data(api_client.book_shipment(shipment["id"], LC))
        tendered = validate_success(api_client.tender_shipment(
            shipment["id"], {"actual_weight_kg": 55.00, "volume_m3": 0.00}, LC))
        # Subtotal 2500 + 7700 = 10200 >= 10000 -> discounted 9690 (< 10000 but
        # the tier still counts); fuel round(9690 x 0.12) = 1163; total 10853.
        assert tendered["final_freight_cents"] == 10853

    def test_tier_boundary_straddling_weights(self, api):
        """PRD §3.7: "Second, the subtotal is the mode's base charge plus the chargeable weight multiplied by the mode's per-kilogram rate, that product rounded half up to whole cents before being added: air freight carries a base of 5000 cents and a rate of 320 cents per kilogram, truck freight a base of 2500 cents and 140 cents per kilogram. Third, the discount test is keyed on the pre-discount subtotal: when that subtotal is at least 10000 cents, a five percent discount applies, and the tier still counts even when applying the discount would pull the result below the threshold; the discounted amount is the subtotal reduced by five percent, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/freight_tier_keyed_on_prediscount_subtotal
        """
        order_ctx = _confirmed_order()
        below = create_shipment(order_ctx["order"]["id"], mode="TRUCK",
                                booked_weight_kg=53.56, temp_zone="FROZEN")
        at = create_shipment(order_ctx["order"]["id"], mode="TRUCK",
                             booked_weight_kg=53.57, temp_zone="FROZEN")
        for shipment in (below, at):
            get_success_data(api_client.book_shipment(shipment["id"], LC))

        below_t = validate_success(api_client.tender_shipment(
            below["id"], {"actual_weight_kg": 53.56, "volume_m3": 0.00}, LC))
        # round(53.56 x 140) = 7498 -> subtotal 9998 < 10000, no tier;
        # fuel round(9998 x 0.12) = 1200; total 11198.
        assert below_t["final_freight_cents"] == 11198

        at_t = validate_success(api_client.tender_shipment(
            at["id"], {"actual_weight_kg": 53.57, "volume_m3": 0.00}, LC))
        # round(53.57 x 140) = 7500 -> subtotal 10000 >= 10000, tier applies;
        # discounted 9500; fuel 1140; total 10640.
        assert at_t["final_freight_cents"] == 10640

    def test_minimum_charge_floors_small_freight(self, api):
        """PRD §3.7: "Fifth and last, the freight charge is the greater of 4000 cents and the sum of the discounted amount and the fuel surcharge: the minimum charge binds exactly there."

        Design: Corner/calculations/calc_freight_min_charge_floor
        """
        order_ctx = _confirmed_order()
        shipment = create_shipment(order_ctx["order"]["id"], mode="TRUCK",
                                   booked_weight_kg=1.00, temp_zone="FROZEN")
        get_success_data(api_client.book_shipment(shipment["id"], LC))
        tendered = validate_success(api_client.tender_shipment(
            shipment["id"], {"actual_weight_kg": 1.00, "volume_m3": 0.00}, LC))
        # subtotal 2640; fuel 317; 2957 is raised to the 4000 floor.
        assert tendered["final_freight_cents"] == 4000
        assert_kg(tendered["chargeable_weight_kg"], 1.00, "chargeable")


class TestAirFlightCapacity:
    """Pooled capacity per (flight_number, flight_date) calendar slot."""

    def test_aggregate_capacity_boundary_and_cancel_frees(self, api):
        """PRD §3.7: "For air freight, capacity is pooled per flight: the sum of `booked_weight_kg` over all shipments in `BOOKED`, `TENDERED`, or `IN_TRANSIT` sharing the same `flight_number` and `flight_date`, plus this booking's weight, must not exceed 1000 kilograms, else `ERR_FLIGHT_CAPACITY_EXCEEDED` (409)."
        PRD §3.7: "Cancellation by a `LogisticsCoordinator` is permitted from `QUOTED` or `BOOKED` — from any later state it draws `ERR_SHIPMENT_INVALID_STATE` — moves the shipment to the terminal `CANCELLED` state, and frees its claim on flight capacity."

        Design: Difficulty/resource_temporal_overlap/air_flight_aggregate_capacity
        """
        order_ctx = _confirmed_order(credit_limit_cents=10000000, qty_kg=1.00)
        order_id = order_ctx["order"]["id"]
        s1 = create_shipment(order_id, mode="AIR", booked_weight_kg=600.00,
                             flight_number="FL100", flight_date="2026-08-03")
        s2 = create_shipment(order_id, mode="AIR", booked_weight_kg=500.00,
                             flight_number="FL100", flight_date="2026-08-03")
        s3 = create_shipment(order_id, mode="AIR", booked_weight_kg=400.00,
                             flight_number="FL100", flight_date="2026-08-03")
        get_success_data(api_client.book_shipment(s1["id"], LC))

        resp = api_client.book_shipment(s2["id"], LC)
        validate_error(resp, ApiErrorId.ERR_FLIGHT_CAPACITY_EXCEEDED)

        booked_s3 = validate_success(api_client.book_shipment(s3["id"], LC))
        assert booked_s3["status"] == "BOOKED", "600 + 400 == 1000 <= 1000"

        get_success_data(api_client.cancel_shipment(s1["id"], LC))
        booked_s2 = validate_success(api_client.book_shipment(s2["id"], LC))
        assert booked_s2["status"] == "BOOKED", (
            "Cancelling the 600 kg booking frees capacity for the 500 kg one")
        assert get_shipment(s3["id"])["status"] == "BOOKED"

    def test_capacity_scoped_per_flight_and_date(self, api):
        """PRD §3.7: "For air freight, capacity is pooled per flight: the sum of `booked_weight_kg` over all shipments in `BOOKED`, `TENDERED`, or `IN_TRANSIT` sharing the same `flight_number` and `flight_date`, plus this booking's weight, must not exceed 1000 kilograms, else `ERR_FLIGHT_CAPACITY_EXCEEDED` (409)."

        Design: Difficulty/resource_temporal_overlap/air_flight_aggregate_capacity
        """
        order_ctx = _confirmed_order(credit_limit_cents=10000000, qty_kg=1.00)
        order_id = order_ctx["order"]["id"]
        base = create_shipment(order_id, mode="AIR", booked_weight_kg=600.00,
                               flight_number="FL100", flight_date="2026-08-03")
        other_flight = create_shipment(order_id, mode="AIR", booked_weight_kg=600.00,
                                       flight_number="FL200", flight_date="2026-08-03")
        other_date = create_shipment(order_id, mode="AIR", booked_weight_kg=600.00,
                                     flight_number="FL100", flight_date="2026-08-04")
        truck = create_shipment(order_id, mode="TRUCK", booked_weight_kg=5000.00)
        get_success_data(api_client.book_shipment(base["id"], LC))

        for shipment in (other_flight, other_date, truck):
            booked = validate_success(api_client.book_shipment(shipment["id"], LC))
            assert booked["status"] == "BOOKED", (
                "Different flight_number, different flight_date, or TRUCK mode "
                "each sit outside the pooled slot")


def test_cancel_after_tender_rejected(api):
    """PRD §3.7: "Cancellation by a `LogisticsCoordinator` is permitted from `QUOTED` or `BOOKED` — from any later state it draws `ERR_SHIPMENT_INVALID_STATE` — moves the shipment to the terminal `CANCELLED` state, and frees its claim on flight capacity."

    Design: Corner/state_machines/sm_shipment_cancel_after_tender_rejected
    """
    order_ctx = _confirmed_order(qty_kg=1.00)
    shipment = create_shipment(order_ctx["order"]["id"], mode="TRUCK",
                               booked_weight_kg=10.00, temp_zone="FROZEN")
    get_success_data(api_client.book_shipment(shipment["id"], LC))
    get_success_data(api_client.tender_shipment(
        shipment["id"], {"actual_weight_kg": 10.00, "volume_m3": 0.10}, LC))

    resp = api_client.cancel_shipment(shipment["id"], LC)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_INVALID_STATE)
    assert get_shipment(shipment["id"])["status"] == "TENDERED"


def test_deliver_moves_committed_weight_to_shipped(api):
    """PRD §3.7: "Delivery moves an `IN_TRANSIT` shipment to the terminal `DELIVERED` state and settles the physical flow: for every `COMMITTED` allocation on the shipment's order lines, the quantity moves from the lot's committed bucket into `shipped_weight_kg`, and lots whose available, reserved, and committed buckets all reach zero transition to `DEPLETED`."
    PRD §3.6: "Conversely, whenever a release, condemnation, expiry, void, or re-grade cascade pushes any line's `committed_qty_kg` back below its `requested_qty_kg`, a `FULFILLED` order regresses to `CONFIRMED` — this regression is the system's way of keeping the order's promise honest as inventory evaporates."

    Design: Corner/endpoints/ep_deliver_moves_committed_to_shipped
    """
    ctx = setup_committed_allocation(line_qty_kg=20.00, lot_landed_weight_kg=20.00)
    order_id, lot_id = ctx["order"]["id"], ctx["lot"]["id"]
    assert get_order(order_id)["status"] == "FULFILLED"

    shipment = create_shipment(order_id, mode="TRUCK", booked_weight_kg=20.00)
    get_success_data(api_client.book_shipment(shipment["id"], LC))
    get_success_data(api_client.tender_shipment(
        shipment["id"], {"actual_weight_kg": 20.00, "volume_m3": 0.10}, LC))
    get_success_data(api_client.depart_shipment(shipment["id"], LC))
    delivered = validate_success(api_client.deliver_shipment(shipment["id"], LC))
    assert delivered["status"] == "DELIVERED"

    lot = get_lot(lot_id)
    assert_lot_buckets(lot, available=0.00, committed=0.00, shipped=20.00)
    assert lot["lifecycle_status"] == "DEPLETED", (
        "available + reserved + committed all reached zero")
    assert get_order(order_id)["status"] == "FULFILLED", (
        "Delivery is not a regression trigger")
