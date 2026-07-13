"""Freight quoting (provisional-over-ordered vs final-over-allocated), the free-freight
waiver, and shipment booking state guards.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
)

WH = TEST_USERS["warehouse_headers"]


# --------------------------------------------------------------------------- #
# dual_variant_calc / freight_provisional_vs_final_on_shipment
# --------------------------------------------------------------------------- #
def _confirmed_backordered_heavy_order(api):
    """Order for 5 HEAVY (100 lb each), on_hand 3 -> 3 allocated, 2 backordered."""
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="HEAVY-1", name="Floor Mixer", unit_price_cents=1000,
                                   case_qty=100, case_price_cents=90000, pallet_case_qty=10,
                                   pallet_price_cents=800000, weight_lbs_per_unit=100,
                                   fulfillment_type="STOCK", freight_type="LTL",
                                   on_hand_qty=3, par_level=50, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 5)
    fixtures.confirm_order(api, order["id"], acct["id"])
    return acct, order


def test_provisional_freight_weighs_ordered_quantity(api):
    """PRD §3.7: "The provisional variant, used at shipment creation for `freight_quote_cents`,
    weighs each line's ordered `quantity` (so it includes eaches that were backordered)."
    PRD §3.7: "the `shipping_mode` is `LTL` and the freight is 7500 cents plus 30 cents per pound
    multiplied by the weight (that product rounded half-up), plus a 4500-cent liftgate fee when
    `liftgate_required` is true."

    Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_on_shipment
    """
    _acct, order = _confirmed_backordered_heavy_order(api)
    ship = validate_success(
        api.create_shipment({"order_id": order["id"], "carrier": "YRC", "liftgate_required": True}, WH),
        201,
    )
    # ordered 5 * 100 lb = 500 lb -> LTL 7500 + 30*500 (15000) + liftgate 4500 = 27000
    assert ship["freight_quote_cents"] == 27000


def test_final_freight_weighs_allocated_quantity_and_diverges(api):
    """PRD §3.7: "The final variant, used at booking for `final_freight_cents`, weighs each line's
    `allocated_qty` only, so it diverges from the provisional figure whenever any line was partially
    or fully backordered."

    Design: Difficulty/dual_variant_calc/freight_provisional_vs_final_on_shipment
    """
    _acct, order = _confirmed_backordered_heavy_order(api)
    ship = validate_success(
        api.create_shipment({"order_id": order["id"], "carrier": "YRC", "liftgate_required": True}, WH),
        201,
    )
    booked = validate_success(api.book_shipment(ship["id"], WH))
    # allocated 3 * 100 lb = 300 lb -> LTL 7500 + 30*300 (9000) + liftgate 4500 = 21000
    assert booked["final_freight_cents"] == 21000
    assert booked["final_freight_cents"] != ship["freight_quote_cents"]


# --------------------------------------------------------------------------- #
# calculations / free_freight_threshold_waives_parcel_base (corner)
# --------------------------------------------------------------------------- #
def test_free_freight_threshold_zeroes_parcel_base(api):
    """PRD §3.7: "if the order's `merchandise_subtotal_cents` is at least 250000 cents, the base
    charge is instead 0 (free freight), and no liftgate fee ever applies to a parcel shipment."

    Design: Corner/calculations/free_freight_threshold_waives_parcel_base
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="FF-1", name="Digital Scale", taxable=False,
                                   unit_price_cents=250000, case_qty=100, case_price_cents=24000000,
                                   pallet_case_qty=10, pallet_price_cents=230000000,
                                   weight_lbs_per_unit=1, fulfillment_type="STOCK",
                                   freight_type="PARCEL", on_hand_qty=100, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 1)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = validate_success(api.create_shipment({"order_id": order["id"], "carrier": "UPS"}, WH), 201)
    assert ship["shipping_mode"] == "PARCEL"
    assert ship["freight_quote_cents"] == 0


# --------------------------------------------------------------------------- #
# state_machines / book_already_booked_shipment_returns_not_quoted (corner)
# --------------------------------------------------------------------------- #
def test_book_already_booked_shipment_rejected(api):
    """PRD §3.7: "It requires the shipment to be `QUOTED` (otherwise `ERR_SHIPMENT_NOT_QUOTED`)
    and its order to be `CONFIRMED` (otherwise `ERR_ORDER_NOT_CONFIRMED`)."

    Design: Corner/state_machines/book_already_booked_shipment_returns_not_quoted
    """
    acct = fixtures.create_account(api)
    prod = fixtures.create_product(api, sku="SHIP-1", name="Cart", unit_price_cents=5000,
                                   case_qty=4, case_price_cents=18000, pallet_case_qty=4,
                                   pallet_price_cents=70000, weight_lbs_per_unit=10,
                                   on_hand_qty=50, par_level=20, reorder_point=4)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 2)
    fixtures.confirm_order(api, order["id"], acct["id"])
    ship = validate_success(api.create_shipment({"order_id": order["id"], "carrier": "UPS"}, WH), 201)
    validate_success(api.book_shipment(ship["id"], WH))
    resp = api.book_shipment(ship["id"], WH)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_QUOTED.value)
