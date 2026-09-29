"""Protocol-order pricing: the pinned order of three independent cent roundings."""
from test_helpers import OrderStatus, assert_protocol_order, fixtures


def _priced_instrument():
    """An instrument priced at 1,799 cents a booklet, with an empty shelf."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    return fixtures.create_instrument(
        name="WISC-V",
        instrument_code="WISC5",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1799,
        license_seat_total=2,
        license_expires_on="2027-06-30",
        supported_language_editions=["en", "es"],
    )


def test_each_pricing_component_is_rounded_to_whole_cents_on_its_own():
    """Thirty rush booklets at 1,799 cents price to 52,039 rather than 52,041.

    "Protocol-order pricing rounds three separate components half up to whole cents *independently*, and only then sums them; applying the percentages to a running total and rounding once at the end produces a different — and wrong — total."

    Design: Difficulty/combinatorial_formula/protocol_order_independent_rounding_order_pin
    """
    instrument = _priced_instrument()

    order = fixtures.order_protocols(instrument["id"], 30, rush_flag=True)

    assert_protocol_order(order)
    # 1799 * 0.95 = 1709.05, rounded half up.
    assert order["unit_price_cents"] == 1709
    assert order["base_cents"] == 51270
    # 51270 * 7 percent = 3588.90, rounded half up on its own.
    assert order["contract_discount_cents"] == 3589
    # 51270 * 8.5 percent = 4357.95, rounded half up on its own.
    assert order["rush_surcharge_cents"] == 4358
    assert order["handling_fee_cents"] == 0
    assert order["total_cost_cents"] == 52039
    assert order["total_cost_cents"] != 52041


def test_an_order_above_the_threshold_waits_for_a_human_decision():
    """52,039 cents is past 40,000, so the order opens unapproved.

    "Otherwise `auto_approved` is false and the order opens in `SUBMITTED` status awaiting a decision."

    Design: Difficulty/combinatorial_formula/protocol_order_independent_rounding_order_pin
    """
    instrument = _priced_instrument()

    order = fixtures.order_protocols(instrument["id"], 30, rush_flag=True)

    assert order["total_cost_cents"] > 40000
    assert order["auto_approved"] is False
    assert order["status"] == OrderStatus.SUBMITTED.value
    assert order["decided_by_user_id"] is None
    assert order["received_quantity"] == 0


def test_pricing_an_order_leaves_the_shelf_untouched():
    """The instrument still holds zero booklets after the order is placed.

    "Creating an order never touches `protocol_stock_count`; booklets move only on receipt."

    Design: Difficulty/combinatorial_formula/protocol_order_independent_rounding_order_pin
    """
    instrument = _priced_instrument()

    fixtures.order_protocols(instrument["id"], 30, rush_flag=True)

    refreshed = fixtures.get_instrument(instrument["id"])
    assert refreshed["protocol_stock_count"] == 0
