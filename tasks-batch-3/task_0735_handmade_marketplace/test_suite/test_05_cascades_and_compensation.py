"""Depth-3 pay cascade, cancel compensation (stock + money invariants), production capacity."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_seller_headers, make_buyer_headers,
    setup_unpaid_mto_order_with_material, setup_capacity_scenario, setup_active_listing,
    place_order, get_shop, get_material, get_listing, get_order,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / transitive_cascade / pay_material_stockout_listing_soldout
# ==========================================================================
def test_pay_decrements_material_to_out_of_stock(api):
    """PRD §3.5: "Inventory is then drawn down ... while a made-to-order order reduces the
    primary material's `stock_qty` by `material_qty_per_unit` multiplied by the ordered
    `quantity`."
    PRD §3.2: "When `stock_qty` is exactly 0 the material is `OUT_OF_STOCK`."

    Design: Difficulty/transitive_cascade/pay_material_stockout_listing_soldout
    """
    shop, material, listing, order = setup_unpaid_mto_order_with_material(
        material_stock=2, reorder_threshold=0, material_qty_per_unit=2, quantity=1)
    validate_success(api.pay_order(order["id"], BUYER))
    mat = get_material(material["id"], shop["id"])
    assert mat["stock_qty"] == 0
    assert mat["status"] == "OUT_OF_STOCK"


def test_pay_flips_listing_to_sold_out(api):
    """PRD §3.5: "If that draw-down leaves a ready-to-ship listing's `quantity` at zero,
    or leaves a made-to-order listing's primary material `OUT_OF_STOCK`, the affected
    listing transitions from `ACTIVE` to `SOLD_OUT`."

    Design: Difficulty/transitive_cascade/pay_material_stockout_listing_soldout
    """
    shop, material, listing, order = setup_unpaid_mto_order_with_material(
        material_stock=2, reorder_threshold=0, material_qty_per_unit=2, quantity=1)
    validate_success(api.pay_order(order["id"], BUYER))
    lst = get_listing(listing["id"], shop["id"])
    assert lst["status"] == "SOLD_OUT"


# ==========================================================================
# Difficulty / compensating_invariant / material_stock_conserved_on_cancel
# ==========================================================================
def test_paid_mto_order_decrements_material_stock(api):
    """PRD §3.5: "a made-to-order order reduces the primary material's `stock_qty` by
    `material_qty_per_unit` multiplied by the ordered `quantity`."

    Design: Difficulty/compensating_invariant/material_stock_conserved_on_cancel
    """
    shop, material, listing, order = setup_unpaid_mto_order_with_material(
        material_stock=10, reorder_threshold=1, material_qty_per_unit=2, quantity=3,
        price_cents=9000)
    validate_success(api.pay_order(order["id"], BUYER))
    mat = get_material(material["id"], shop["id"])
    assert mat["stock_qty"] == 4, "10 - 2*3 == 4 after pay"


def test_cancelling_paid_mto_order_restores_material_stock(api):
    """PRD §3.6: "a made-to-order order's primary material `stock_qty` is increased back
    by `material_qty_per_unit` multiplied by the ordered `quantity`".
    PRD §3.6: "These restorations keep both the material stock total and the shop's
    in-flight money conserved."

    Design: Difficulty/compensating_invariant/material_stock_conserved_on_cancel
    """
    shop, material, listing, order = setup_unpaid_mto_order_with_material(
        material_stock=10, reorder_threshold=1, material_qty_per_unit=2, quantity=3,
        price_cents=9000)
    validate_success(api.pay_order(order["id"], BUYER))
    validate_success(api.cancel_order(order["id"], make_seller_headers(shop["id"]),
                                      {"cancel_reason": "buyer changed mind"}))
    mat = get_material(material["id"], shop["id"])
    assert mat["stock_qty"] == 10, "cancel restores the consumed 6 units back to 10"


# ==========================================================================
# Difficulty / compensating_invariant / shop_pending_balance_conserved_on_refund
# ==========================================================================
def _shop_with_paid_free_shipping_order():
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 100},
        listing_overrides={"price_cents": 100, "quantity": 10, "title": "Sticker"})
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    return shop, listing, order


def test_pay_credits_shop_pending_balance(api):
    """PRD §3.5: "On the same payment, the shop's `pending_balance_cents` is increased by
    `order_net_cents` and its `lifetime_gross_cents` is increased by `order_total_cents`."

    Design: Difficulty/compensating_invariant/shop_pending_balance_conserved_on_refund
    """
    shop, listing, order = _shop_with_paid_free_shipping_order()
    validate_success(api.pay_order(order["id"], BUYER))
    assert get_shop(shop["id"])["pending_balance_cents"] == 45, "net 45 credited to pending"


def test_cancel_reverses_pending_balance_and_refunds_order(api):
    """PRD §3.6: "If the order had been paid, its `payment_status` becomes `REFUNDED` and
    its `refunded_cents` is set to the full `order_total_cents`."
    PRD §3.6: "the shop's `pending_balance_cents` is decreased by `order_net_cents`,
    exactly reversing the credit that payment had made."

    Design: Difficulty/compensating_invariant/shop_pending_balance_conserved_on_refund
    """
    shop, listing, order = _shop_with_paid_free_shipping_order()
    validate_success(api.pay_order(order["id"], BUYER))
    cancelled = validate_success(api.cancel_order(order["id"], make_seller_headers(shop["id"])))
    assert get_shop(shop["id"])["pending_balance_cents"] == 0
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["refunded_cents"] == 100


# ==========================================================================
# Difficulty / resource_temporal_overlap / production_capacity_aggregate_overlap
# ==========================================================================
def test_second_overlapping_mto_order_exceeds_capacity(api):
    """PRD §3.5: "counting the shop's orders whose production window — the span from
    `paid_at` to `ship_by_date`, treated as a closed interval — would overlap this order's
    window, that count must remain within the shop's `max_concurrent_production`;
    exceeding it is rejected with `ERR_PRODUCTION_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/production_capacity_aggregate_overlap
    """
    shop, listing, order1, order2 = setup_capacity_scenario()
    resp = api.pay_order(order2["id"], BUYER)
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_CAPACITY_EXCEEDED)


def test_capacity_exceeded_leaves_second_order_unpaid(api):
    """PRD §3.5: "exceeding it is rejected with `ERR_PRODUCTION_CAPACITY_EXCEEDED`
    (HTTP 409)."
    PRD §3.5: "Payment is defined only from `UNPAID`".

    Design: Difficulty/resource_temporal_overlap/production_capacity_aggregate_overlap
    """
    shop, listing, order1, order2 = setup_capacity_scenario()
    validate_error(api.pay_order(order2["id"], BUYER),
                   ApiErrorId.ERR_PRODUCTION_CAPACITY_EXCEEDED)
    assert get_order(order2["id"], shop["id"])["payment_status"] == "UNPAID"
