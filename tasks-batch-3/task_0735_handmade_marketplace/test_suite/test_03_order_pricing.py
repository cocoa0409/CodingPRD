"""Order pricing: item subtotal, non-linear shipping, free-shipping boundary, fees, ship-by."""
from test_helpers import (
    validate_success,
    make_buyer_headers,
    setup_active_listing, set_clock,
    create_shop, create_shipping_profile, create_listing, publish_listing, place_order,
)

BUYER = make_buyer_headers("buyer_1")


# ==========================================================================
# Difficulty / combinatorial_formula / shipping_nonlinear_base_plus_per_item
# ==========================================================================
def test_shipping_is_base_plus_per_item_for_additional_units(api):
    """PRD §3.4: "Otherwise `shipping_cents` is the profile's `base_cost_cents` plus its
    `per_item_cost_cents` multiplied by the number of additional items, which is the
    ordered `quantity` minus one but never below zero."

    Design: Difficulty/combinatorial_formula/shipping_nonlinear_base_plus_per_item
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 10000},
        listing_overrides={"price_cents": 2000, "quantity": 10, "title": "Scarf"})
    data = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 3}, BUYER), 201)
    assert data["shipping_cents"] == 800, "500 + 150*max(0, 3-1) == 800"


def test_item_subtotal_and_total_for_multi_unit_order(api):
    """PRD §3.4: "the `item_subtotal_cents` is that per-unit price multiplied by the
    ordered `quantity`."
    PRD §3.4: "The `order_total_cents` is the sum of `item_subtotal_cents` and
    `shipping_cents`."

    Design: Difficulty/combinatorial_formula/shipping_nonlinear_base_plus_per_item
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 10000},
        listing_overrides={"price_cents": 2000, "quantity": 10, "title": "Scarf"})
    data = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 3}, BUYER), 201)
    assert data["item_subtotal_cents"] == 6000
    assert data["order_total_cents"] == 6800


# ==========================================================================
# Difficulty / boundary_precision_check / free_shipping_threshold_ge_boundary
# ==========================================================================
def test_subtotal_at_free_shipping_threshold_ships_free(api):
    """PRD §3.4: "If the profile's `free_shipping_threshold_cents` is greater than zero
    and the `item_subtotal_cents` is greater than or equal to that threshold,
    `shipping_cents` is zero — a subtotal exactly equal to the threshold ships free."

    Design: Difficulty/boundary_precision_check/free_shipping_threshold_ge_boundary
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 6000},
        listing_overrides={"price_cents": 3000, "quantity": 10, "title": "Vase"})
    data = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 2}, BUYER), 201)
    assert data["item_subtotal_cents"] == 6000
    assert data["shipping_cents"] == 0, "subtotal == threshold ships free"


def test_subtotal_below_free_shipping_threshold_is_charged(api):
    """PRD §3.4: "If the profile's `free_shipping_threshold_cents` is greater than zero
    and the `item_subtotal_cents` is greater than or equal to that threshold,
    `shipping_cents` is zero — a subtotal exactly equal to the threshold ships free."

    Design: Difficulty/boundary_precision_check/free_shipping_threshold_ge_boundary
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 6000},
        listing_overrides={"price_cents": 3000, "quantity": 10, "title": "Vase"})
    data = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER), 201)
    assert data["item_subtotal_cents"] == 3000
    assert data["shipping_cents"] == 500, "subtotal one unit below threshold is charged base cost"


# ==========================================================================
# Corner / calculations / order_fees_and_net_single_order
# ==========================================================================
def test_order_fees_and_net_computed_at_payment(api):
    """PRD §3.5: "A flat listing fee of 20 cents is always charged. A transaction fee is
    6.5 percent of `order_total_cents`, rounded half up to whole cents. A
    payment-processing fee is 3 percent of `order_total_cents` rounded half up to whole
    cents, plus a fixed 25-cent surcharge. The `order_fee_cents` is the sum of the flat
    listing fee, the transaction fee, and the payment-processing fee. The
    `order_net_cents` is `order_total_cents` minus `order_fee_cents`".

    Design: Corner/calculations/order_fees_and_net_single_order
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 0},
        listing_overrides={"price_cents": 2000, "quantity": 10, "title": "Mug"})
    created = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 3}, BUYER), 201)
    assert created["order_total_cents"] == 6800
    paid = validate_success(api.pay_order(created["id"], BUYER))
    # 20 + round(0.065*6800=442) + round(0.03*6800=204)+25 = 20 + 442 + 229 = 691
    assert paid["order_fee_cents"] == 691
    assert paid["order_net_cents"] == 6109


# ==========================================================================
# Corner / consistency_model / immediate_visibility_of_computed_pricing_on_order_create
# ==========================================================================
def test_order_create_returns_pricing_immediately(api):
    """PRD §3.4: "the `item_subtotal_cents` is that per-unit price multiplied by the
    ordered `quantity`."
    PRD §3.4: "Otherwise `shipping_cents` is the profile's `base_cost_cents` plus its
    `per_item_cost_cents` multiplied by the number of additional items, which is the
    ordered `quantity` minus one but never below zero. The `order_total_cents` is the sum
    of `item_subtotal_cents` and `shipping_cents`."

    Design: Corner/consistency_model/immediate_visibility_of_computed_pricing_on_order_create
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 500, "per_item_cost_cents": 150,
                      "free_shipping_threshold_cents": 0},
        listing_overrides={"price_cents": 2000, "quantity": 10, "title": "Mug"})
    data = validate_success(api.create_order(
        {"shop_id": shop["id"], "listing_id": listing["id"], "quantity": 1}, BUYER), 201)
    assert data["item_subtotal_cents"] == 2000
    assert data["shipping_cents"] == 500
    assert data["order_total_cents"] == 2500


# ==========================================================================
# Corner / calculations / ship_by_date_mto_processing_days
# ==========================================================================
def test_ship_by_date_uses_listing_processing_days(api):
    """PRD §3.5: "The order's `ship_by_date` is computed as `paid_at` plus an effective
    number of processing days: the listing's own `processing_time_days` when that is
    greater than zero, otherwise the shipping profile's `processing_time_days` as a
    fallback."
    PRD §2.10: "The clock's startup default is `2026-03-01T00:00:00Z`, and before any
    client sets it the clock reads exactly that default."

    Design: Corner/calculations/ship_by_date_mto_processing_days
    """
    set_clock("2026-03-01T00:00:00Z")
    shop = create_shop(max_concurrent_production=5)
    sp = create_shipping_profile(shop["id"], base_cost_cents=0, per_item_cost_cents=0,
                                 processing_time_days=2)
    listing = create_listing(shop["id"], sp["id"], fulfillment_type="MADE_TO_ORDER",
                             processing_time_days=7, price_cents=4000, title="Custom Sign")
    publish_listing(shop["id"], listing["id"])
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    paid = validate_success(api.pay_order(order["id"], BUYER))
    assert paid["ship_by_date"].startswith("2026-03-08T00:00:00"), \
        f"ship_by_date should be paid_at + 7 days, got {paid['ship_by_date']!r}"
