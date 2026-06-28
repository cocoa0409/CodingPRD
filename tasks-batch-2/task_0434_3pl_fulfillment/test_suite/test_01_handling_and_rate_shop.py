"""Handling-fee estimate-vs-billed and carrier rate-shop calculations.

Covers the dual-variant and combinatorial-formula difficulty rules plus the
calculation-section corner instances for handling and rate-shop.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_packed_order,
    setup_labelled_order,
    buy_label,
    ship_order,
    get_order,
    pack_order,
    order_in_picking,
    stock_client_sku_bin,
)


def test_multi_carton_billed_handling_exceeds_estimate(api):
    """PRD §3.6: "The estimate deliberately omits any per-carton surcharge and
    creates no billing charge — it is a preview written before the shipped carton
    count is final."
    PRD §3.8: "Because of this surcharge a multi-carton order is billed strictly
    more than its earlier estimate; a single-carton order is billed exactly its
    estimate."

    A 3-unit order (base 500 + 2*50 = 600 estimate) packed into 2 cartons is
    billed 600 + 1*200 surcharge = 800 at ship.

    Design: Difficulty/dual_variant_calc/handling_estimate_vs_billed_diverges_on_multi_carton_order
    """
    client, sku, b, order, cartons = setup_packed_order(
        order_qty=3, carton_units=[2, 1], ship_to_zone=3,
        handling_rate_per_order_cents=500,
        handling_rate_per_extra_unit_cents=50,
        handling_surcharge_per_extra_carton_cents=200,
        carrier_discount_bps=0,
    )
    assert order["estimated_handling_cents"] == 600, order["estimated_handling_cents"]

    buy_label(client["id"], order["id"])
    shipped = ship_order(client["id"], order["id"])

    assert shipped["billed_handling_cents"] == 800, shipped["billed_handling_cents"]
    assert shipped["billed_handling_cents"] > shipped["estimated_handling_cents"]


def test_multi_carton_handling_charge_posts_billed_amount(api):
    """PRD §3.8: "The server creates a `BillingCharge` whose `charge_type` is
    `HANDLING`, whose `amount_cents` equals the order's `billed_handling_cents`
    exactly, and whose `source_order_id` is the shipped order; posting this charge
    increases the client's `handling_balance_cents` by that `amount_cents`."

    Design: Difficulty/dual_variant_calc/handling_estimate_vs_billed_diverges_on_multi_carton_order
    """
    client, sku, b, order, cartons = setup_packed_order(
        order_qty=3, carton_units=[2, 1], ship_to_zone=3,
        handling_rate_per_order_cents=500,
        handling_rate_per_extra_unit_cents=50,
        handling_surcharge_per_extra_carton_cents=200,
        carrier_discount_bps=0,
    )
    buy_label(client["id"], order["id"])
    ship_order(client["id"], order["id"])

    charges, _ = _list_charges(api, client["id"], source_order_id=order["id"], charge_type="HANDLING")
    assert len(charges) == 1, charges
    assert charges[0]["amount_cents"] == 800
    assert charges[0]["source_order_id"] == order["id"]
    updated_client = validate_success(api.get_client(client["id"], _BILLING))
    assert updated_client["handling_balance_cents"] == 800


def test_rate_shop_negotiated_quote_below_published(api):
    """PRD §3.7: "for a non-zero discount the negotiated quote is strictly below
    the published quote, so the two diverge on the same shipment inputs."

    GROUND_ECONOMY published for zone 3, 1 carton = 300 + 50*3 + 100*1 = 550;
    at carrier_discount_bps 1000 (10%) the negotiated quote is round_half_up(495.0) = 495.

    Design: Difficulty/dual_variant_calc/rate_shop_published_vs_negotiated_quote_diverges
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, carrier_discount_bps=1000,
    )
    assert shipment["carrier"] == "GROUND_ECONOMY"
    assert shipment["quoted_cost_cents"] == 495, shipment["quoted_cost_cents"]
    assert shipment["quoted_cost_cents"] < 550


def test_rate_shop_hazmat_drops_ground_economy_from_candidates(api):
    """PRD §3.7: "`GROUND_ECONOMY` is excluded from the candidate pool whenever
    any line SKU on the order is flagged `hazmat`; `GROUND_PLUS` and `AIR_EXPRESS`
    are always eligible, so the candidate pool is never empty."
    PRD §3.7: "The winner is the eligible carrier with the lowest negotiated figure."

    With GROUND_ECONOMY excluded, zone 3, 1 carton, discount 0:
    GROUND_PLUS = 500 + 40*3 + 120*1 = 740; AIR_EXPRESS = 1200 + 80*3 + 150*1 = 1590.
    Winner GROUND_PLUS at 740.

    Design: Difficulty/combinatorial_formula/rate_shop_carrier_min_with_hazmat_eligibility_branch
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, hazmat=True, carrier_discount_bps=0,
    )
    assert shipment["carrier"] == "GROUND_PLUS", shipment["carrier"]
    assert shipment["quoted_cost_cents"] == 740, shipment["quoted_cost_cents"]


def test_rate_shop_discount_then_round_half_up_order_pinned(api):
    """PRD §3.7: "(2) forms the exact discounted amount by multiplying
    `published_cents` by the quantity ten thousand minus the client's
    `carrier_discount_bps`, then dividing by ten thousand; and (3) rounds that
    discounted amount half up to a whole cent to obtain the negotiated figure."

    GROUND_ECONOMY published 550 at carrier_discount_bps 2500 (25%):
    550 * 0.75 = 412.5 rounds half up to 413.

    Design: Difficulty/combinatorial_formula/rate_shop_negotiated_rounding_order_pinned_half_up
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, carrier_discount_bps=2500,
    )
    assert shipment["carrier"] == "GROUND_ECONOMY", shipment["carrier"]
    assert shipment["quoted_cost_cents"] == 413, shipment["quoted_cost_cents"]


def test_rate_shop_zero_discount_negotiated_equals_published(api):
    """PRD §3.7: "For a client whose `carrier_discount_bps` is zero the negotiated
    quote equals the published quote (no rounding changes an exact integer)".

    GROUND_ECONOMY published for zone 3, 1 carton = 550; with discount 0 the
    quoted_cost_cents is 550.

    Design: Corner/calculations/rate_shop_published_variant_no_discount_applies_for_zero_bps_client
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, carrier_discount_bps=0,
    )
    assert shipment["carrier"] == "GROUND_ECONOMY", shipment["carrier"]
    assert shipment["quoted_cost_cents"] == 550, shipment["quoted_cost_cents"]


def test_rate_shop_stamps_winning_carrier_on_shipment(api):
    """PRD §3.7: "The winning carrier is written to the shipment's `carrier`, and
    the winner's negotiated figure is stamped as `quoted_cost_cents`."

    A second assertion on the same divergence instance: the winner GROUND_ECONOMY
    is the value stamped on `carrier` alongside its negotiated 495.

    Design: Difficulty/dual_variant_calc/rate_shop_published_vs_negotiated_quote_diverges
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, carrier_discount_bps=1000,
    )
    fetched = validate_success(api.get_shipment(shipment["id"], _SHIP))
    assert fetched["carrier"] == "GROUND_ECONOMY"
    assert fetched["quoted_cost_cents"] == 495


def test_rate_shop_hazmat_winner_is_not_ground_economy(api):
    """PRD §3.7: "`GROUND_ECONOMY` is excluded from the candidate pool whenever any
    line SKU on the order is flagged `hazmat`; `GROUND_PLUS` and `AIR_EXPRESS` are
    always eligible, so the candidate pool is never empty."

    A second assertion on the eligibility-branch instance: the stamped carrier is
    never GROUND_ECONOMY for a hazmat order, and the persisted shipment confirms it.

    Design: Difficulty/combinatorial_formula/rate_shop_carrier_min_with_hazmat_eligibility_branch
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, hazmat=True, carrier_discount_bps=0,
    )
    fetched = validate_success(api.get_shipment(shipment["id"], _SHIP))
    assert fetched["carrier"] != "GROUND_ECONOMY"
    assert fetched["carrier"] == "GROUND_PLUS"


def test_rate_shop_rounding_at_different_discount_value(api):
    """PRD §3.7: "(3) rounds that discounted amount half up to a whole cent to
    obtain the negotiated figure. Rounding happens only at step three, once per
    carrier, after the discount."

    A second discount value on the pinned-rounding instance: GROUND_ECONOMY
    published 550 at carrier_discount_bps 1500 (15%): 550*0.85 = 467.5 -> 468.

    Design: Difficulty/combinatorial_formula/rate_shop_negotiated_rounding_order_pinned_half_up
    """
    client, sku, b, order, shipment = setup_labelled_order(
        order_qty=1, ship_to_zone=3, carrier_discount_bps=1500,
    )
    assert shipment["carrier"] == "GROUND_ECONOMY"
    assert shipment["quoted_cost_cents"] == 468, shipment["quoted_cost_cents"]


def test_single_unit_handling_estimate_is_base_only(api):
    """PRD §3.6: "When `total_units` is one or fewer, the incremental component is
    zero."

    A 1-unit order with base 500 and per-extra-unit 50 has estimated_handling 500.

    Design: Corner/calculations/single_unit_order_handling_estimate_is_base_only
    """
    client, sku, b = stock_client_sku_bin(
        stock_qty=2,
        handling_rate_per_order_cents=500,
        handling_rate_per_extra_unit_cents=50,
    )
    order, wave = order_in_picking(client["id"], sku["id"], 1, ship_to_zone=2)
    packed = pack_order(client["id"], order["id"], [1])
    assert packed["estimated_handling_cents"] == 500, packed["estimated_handling_cents"]


# --- module-local helpers ---
from test_helpers import TEST_USERS  # noqa: E402

_BILLING = TEST_USERS["billing_clerk_headers"]
_SHIP = TEST_USERS["ship_station_headers"]


def _list_charges(api, client_id, **params):
    resp = api.list_client_billing_charges(client_id, _BILLING, params=params)
    body = resp.json()
    return body["data"], body["meta"]
