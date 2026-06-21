"""Order pricing: tiered shipping, per-line tax rounding, totals (PRD §3.2).

Difficulty queue: combinatorial_formula, boundary_precision_check (shipping tier).
Corner queue: calculations (free shipping upper tier), consistency_model (immediate),
cross_cutting (version increments).
"""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_success,
    make_customer_headers,
    create_order_payload,
    create_order_line_payload,
    checkout_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]


def test_promo_flips_shipping_tier_across_5000_boundary(api):
    """PRD §3.2: "if the discounted subtotal is below 50 dollars (5000 cents) the
    fee is 999 cents; if it is at least 50 dollars but below 100 dollars (10000
    cents) the fee is 499 cents; and if it is at least 100 dollars the fee is 0."
    PRD §3.2: "discounted_subtotal_cents is the larger of 0 and subtotal_cents
    minus promo_flat_cents; this discounted figure both drives the shipping tier
    and serves as the base that will eventually be captured."

    Design: Difficulty/combinatorial_formula/order_total_tiered_shipping_with_promo_and_per_line_tax_mode_a
    """
    customer, warehouse, product, _ = fx.setup_catalog(
        product_overrides={"unit_price_cents": 5100, "tax_rate_bps": 875,
                           "return_window_days": 30, "final_sale": False},
        on_hand_qty=50)
    order, _ = fx.build_cart_with_line(customer["id"], product["id"], qty=1,
                                       promo_flat_cents=200)
    headers = make_customer_headers(customer["id"])
    version = fx.get_order(order["id"], customer["id"])["version"]
    resp = api.checkout_order(order["id"], checkout_payload(version), headers)
    data = validate_success(resp, 200)

    assert data["subtotal_cents"] == 5100
    assert data["discounted_subtotal_cents"] == 4900
    assert data["tax_total_cents"] == 446
    assert data["shipping_fee_cents"] == 999, "discounted 4900 < 5000 → standard 999"
    assert data["grand_total_cents"] == 6345


def test_no_promo_keeps_higher_shipping_tier(api):
    """PRD §3.2: "discounted_subtotal_cents is the larger of 0 and subtotal_cents
    minus promo_flat_cents; this discounted figure both drives the shipping tier and
    serves as the base that will eventually be captured."
    PRD §3.2: "if it is at least 50 dollars but below 100 dollars (10000 cents) the
    fee is 499 cents".

    Design: Difficulty/combinatorial_formula/order_total_tiered_shipping_with_promo_and_per_line_tax_mode_a
    """
    # Same product (unit 5100, tax 875) as the promo case, but promo 0: discounted
    # stays 5100 >= 5000 → reduced shipping 499, and grand is 6045, not 6345.
    customer, warehouse, product, _ = fx.setup_catalog(
        product_overrides={"unit_price_cents": 5100, "tax_rate_bps": 875,
                           "return_window_days": 30, "final_sale": False},
        on_hand_qty=50)
    order, _ = fx.build_cart_with_line(customer["id"], product["id"], qty=1,
                                       promo_flat_cents=0)
    after = fx.checkout(order["id"], customer["id"])
    assert after["discounted_subtotal_cents"] == 5100
    assert after["tax_total_cents"] == 446
    assert after["shipping_fee_cents"] == 499, "discounted 5100 >= 5000 → reduced 499"
    assert after["grand_total_cents"] == 6045


def test_tax_rounds_per_line_then_sums(api):
    """PRD §3.2: "each line's line_tax_cents is the line subtotal multiplied by
    tax_rate_bps_snapshot, divided by 10000, rounded half up to a whole cent — and
    tax_total_cents is the sum of those already-rounded per-line taxes, never the
    rounding of their unrounded sum."

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_tax_mode_b
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    pa = fx.create_product(unit_price_cents=1000, tax_rate_bps=875, return_window_days=30)
    pb = fx.create_product(unit_price_cents=1000, tax_rate_bps=875, return_window_days=30)
    fx.stock_inventory(pa["id"], warehouse["id"], 50)
    fx.stock_inventory(pb["id"], warehouse["id"], 50)

    order = fx.create_cart(customer["id"], promo_flat_cents=0)
    line_a = fx.add_line(order["id"], customer["id"], pa["id"], 1)
    line_b = fx.add_line(order["id"], customer["id"], pb["id"], 1)
    order_after = fx.checkout(order["id"], customer["id"])

    la = fx.get_order_line(line_a["id"])
    lb = fx.get_order_line(line_b["id"])
    assert la["line_tax_cents"] == 88
    assert lb["line_tax_cents"] == 88
    assert order_after["tax_total_cents"] == 176, "round-per-line-then-sum; sum-then-round would be 175"
    assert order_after["grand_total_cents"] == 3175


def test_three_line_tax_rounds_each_line_independently(api):
    """PRD §3.2: "each line's line_tax_cents is the line subtotal multiplied by
    tax_rate_bps_snapshot, divided by 10000, rounded half up to a whole cent — and
    tax_total_cents is the sum of those already-rounded per-line taxes, never the
    rounding of their unrounded sum."

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum_tax_mode_b
    """
    # Three identical lines of subtotal 1000 @ 875 bps: each rounds to 88 → 264.
    # Sum-then-round of 3000 @ 875 bps = round(262.5) = 263, which the calc forbids.
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    products = [fx.create_product(unit_price_cents=1000, tax_rate_bps=875,
                                  return_window_days=30) for _ in range(3)]
    for p in products:
        fx.stock_inventory(p["id"], warehouse["id"], 50)
    order = fx.create_cart(customer["id"], promo_flat_cents=0)
    lines = [fx.add_line(order["id"], customer["id"], p["id"], 1) for p in products]
    after = fx.checkout(order["id"], customer["id"])
    for line in lines:
        assert fx.get_order_line(line["id"])["line_tax_cents"] == 88
    assert after["tax_total_cents"] == 264, "88*3; sum-then-round would be 263"


def test_shipping_tier_inclusive_lower_bound_at_5000(api):
    """PRD §3.2: "if the discounted subtotal is below 50 dollars (5000 cents) the
    fee is 999 cents; if it is at least 50 dollars but below 100 dollars (10000
    cents) the fee is 499 cents".

    Design: Difficulty/boundary_precision_check/shipping_tier_inclusive_lower_bound_at_5000_on_checkout
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    px = fx.create_product(unit_price_cents=5000, tax_rate_bps=0, return_window_days=30)
    py = fx.create_product(unit_price_cents=4999, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(px["id"], warehouse["id"], 10)
    fx.stock_inventory(py["id"], warehouse["id"], 10)

    order_x = fx.create_cart(customer["id"], promo_flat_cents=0)
    fx.add_line(order_x["id"], customer["id"], px["id"], 1)
    order_x_after = fx.checkout(order_x["id"], customer["id"])

    order_y = fx.create_cart(customer["id"], promo_flat_cents=0)
    fx.add_line(order_y["id"], customer["id"], py["id"], 1)
    order_y_after = fx.checkout(order_y["id"], customer["id"])

    assert order_x_after["shipping_fee_cents"] == 499, "discounted 5000 == boundary → reduced 499"
    assert order_y_after["shipping_fee_cents"] == 999, "discounted 4999 < 5000 → standard 999"


def test_shipping_tier_boundary_at_4999_takes_standard(api):
    """PRD §3.2: "if the discounted subtotal is below 50 dollars (5000 cents) the
    fee is 999 cents; if it is at least 50 dollars but below 100 dollars (10000
    cents) the fee is 499 cents".

    Design: Difficulty/boundary_precision_check/shipping_tier_inclusive_lower_bound_at_5000_on_checkout
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=4999, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(product["id"], warehouse["id"], 10)
    order = fx.create_cart(customer["id"], promo_flat_cents=0)
    fx.add_line(order["id"], customer["id"], product["id"], 1)
    after = fx.checkout(order["id"], customer["id"])
    assert after["discounted_subtotal_cents"] == 4999
    assert after["shipping_fee_cents"] == 999


def test_free_shipping_at_10000_upper_tier_inclusive(api):
    """PRD §3.2: "if it is at least 50 dollars but below 100 dollars (10000 cents)
    the fee is 499 cents; and if it is at least 100 dollars the fee is 0."

    Design: Corner/calculations/free_shipping_above_10000_threshold
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=10000, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(product["id"], warehouse["id"], 10)
    order = fx.create_cart(customer["id"], promo_flat_cents=0)
    fx.add_line(order["id"], customer["id"], product["id"], 1)
    after = fx.checkout(order["id"], customer["id"])
    assert after["shipping_fee_cents"] == 0, "discounted 10000 >= 10000 → free shipping"
    assert after["grand_total_cents"] == 10000


def test_checkout_response_carries_recomputed_totals_immediately(api):
    """PRD §3.2: "A successful checkout recomputes all order totals and advances
    payment_status from CART to AUTHORIZED."
    PRD §3.2: "if the discounted subtotal is below 50 dollars (5000 cents) the fee
    is 999 cents".

    Design: Corner/consistency_model/immediate_visibility_of_checkout_totals_in_same_response
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=3000, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(product["id"], warehouse["id"], 10)
    order = fx.create_cart(customer["id"], promo_flat_cents=0)
    fx.add_line(order["id"], customer["id"], product["id"], 1)
    headers = make_customer_headers(customer["id"])
    version = fx.get_order(order["id"], customer["id"])["version"]
    resp = api.checkout_order(order["id"], checkout_payload(version), headers)
    data = validate_success(resp, 200)
    assert data["grand_total_cents"] == 3999, "subtotal 3000 < 5000 → standard ship 999; tax 0"
    assert data["shipping_fee_cents"] == 999


def test_order_version_increments_on_every_mutation(api):
    """PRD §2.4: "The version field is an integer that starts at its initial value
    and increments by one with every mutation of the resource".
    PRD §3.2: "Adding a line increments the parent Order's version by one".
    PRD §3.2: "Checkout also increments the Order's version by one."
    PRD §3.4: "advances payment_status from AUTHORIZED to CAPTURED, and increments
    the Order's version."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_order_mutation
    """
    customer = fx.create_customer()
    warehouse = fx.create_warehouse()
    product = fx.create_product(unit_price_cents=1000, tax_rate_bps=0, return_window_days=30)
    fx.stock_inventory(product["id"], warehouse["id"], 10)

    order = fx.create_cart(customer["id"])
    assert order["version"] == 1, "created order starts at version 1"
    fx.add_line(order["id"], customer["id"], product["id"], 1)
    after_line = fx.get_order(order["id"], customer["id"])
    assert after_line["version"] == 2

    after_checkout = fx.checkout(order["id"], customer["id"], after_line["version"])
    assert after_checkout["version"] == 3

    after_capture = fx.capture(order["id"])
    assert after_capture["version"] == 4
