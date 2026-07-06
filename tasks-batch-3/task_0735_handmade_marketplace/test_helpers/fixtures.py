"""Composite setup helpers.

Each test starts against an empty database (the runner restarts the server before every
test), so every helper builds its preconditions from scratch through PRD-declared
endpoints only. Helpers use the lenient get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after a helper creates a shop, every ownership-gated seller call uses
make_seller_headers(shop_id) with that shop's actual id; buyer calls use
make_buyer_headers(buyer_id) with the id captured as the order's buyer_id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .test_users import TEST_USERS, make_seller_headers, make_buyer_headers

ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(iso=CLOCK_DEFAULT):
    """Set the server logical clock (PlatformAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def create_shop(**overrides):
    payload = {"owner_seller_id": "seller_1", "name": "Handmade Co"}
    payload.update(overrides)
    return get_success_data(api_client.create_shop(payload, ADMIN))


def create_shipping_profile(shop_id, base_cost_cents=0, per_item_cost_cents=0, **overrides):
    payload = {
        "shop_id": shop_id,
        "name": "US",
        "base_cost_cents": base_cost_cents,
        "per_item_cost_cents": per_item_cost_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_shipping_profile(payload, make_seller_headers(shop_id)))


def create_material(shop_id, stock_qty, reorder_threshold=0, name="Material", **overrides):
    payload = {
        "shop_id": shop_id,
        "name": name,
        "stock_qty": stock_qty,
        "reorder_threshold": reorder_threshold,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_material(payload, make_seller_headers(shop_id)))


def create_listing(shop_id, shipping_profile_id, fulfillment_type="READY_TO_SHIP",
                   price_cents=2000, processing_time_days=1, title="Handmade Item",
                   quantity=10, **overrides):
    payload = {
        "shop_id": shop_id,
        "shipping_profile_id": shipping_profile_id,
        "title": title,
        "fulfillment_type": fulfillment_type,
        "processing_time_days": processing_time_days,
        "price_cents": price_cents,
    }
    if fulfillment_type == "READY_TO_SHIP":
        payload["quantity"] = quantity
    payload.update(overrides)
    return get_success_data(api_client.create_listing(payload, make_seller_headers(shop_id)))


def publish_listing(shop_id, listing_id):
    return get_success_data(api_client.publish_listing(listing_id, make_seller_headers(shop_id)))


def place_order(shop_id, listing_id, buyer_id="buyer_1", quantity=1, **overrides):
    payload = {"shop_id": shop_id, "listing_id": listing_id, "quantity": quantity}
    payload.update(overrides)
    return get_success_data(api_client.create_order(payload, make_buyer_headers(buyer_id)))


def pay_order(order_id, buyer_id="buyer_1"):
    return get_success_data(api_client.pay_order(order_id, make_buyer_headers(buyer_id)))


def ship_order(order_id, shop_id):
    return get_success_data(api_client.ship_order(order_id, make_seller_headers(shop_id)))


def deliver_order(order_id, shop_id):
    return get_success_data(api_client.deliver_order(order_id, make_seller_headers(shop_id)))


def complete_order(order_id, buyer_id="buyer_1"):
    return get_success_data(api_client.complete_order(order_id, make_buyer_headers(buyer_id)))


def create_review(order_id, rating, buyer_id="buyer_1", **overrides):
    payload = {"order_id": order_id, "rating": rating}
    payload.update(overrides)
    return get_success_data(api_client.create_review(payload, make_buyer_headers(buyer_id)))


def open_dispute_case(order_id, buyer_id="buyer_1", case_type="NON_DELIVERY", **overrides):
    payload = {"order_id": order_id, "type": case_type}
    payload.update(overrides)
    return get_success_data(api_client.create_case(payload, make_buyer_headers(buyer_id)))


def seller_respond_case(case_id, shop_id, message=None):
    payload = {} if message is None else {"message": message}
    return get_success_data(api_client.respond_case(case_id, make_seller_headers(shop_id), payload))


def seller_resolve_case(case_id, shop_id, decision, resolution=None):
    payload = {"decision": decision}
    if resolution is not None:
        payload["resolution"] = resolution
    return get_success_data(api_client.resolve_case(case_id, make_seller_headers(shop_id), payload))


# --------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------
def get_shop(shop_id):
    return get_success_data(api_client.get_shop(shop_id, make_seller_headers(shop_id)))


def get_shop_version(shop_id):
    return get_shop(shop_id)["version"]


def get_order(order_id, shop_id):
    return get_success_data(api_client.get_order(order_id, make_seller_headers(shop_id)))


def get_material(material_id, shop_id):
    return get_success_data(api_client.get_material(material_id, make_seller_headers(shop_id)))


def get_listing(listing_id, shop_id):
    return get_success_data(api_client.get_listing(listing_id, make_seller_headers(shop_id)))


def get_payout(payout_id, shop_id):
    return get_success_data(api_client.get_payout(payout_id, make_seller_headers(shop_id)))


def create_payout(shop_id, expected_shop_version=None):
    if expected_shop_version is None:
        expected_shop_version = get_shop_version(shop_id)
    payload = {"shop_id": shop_id, "expected_shop_version": expected_shop_version}
    return get_success_data(api_client.create_payout(payload, make_seller_headers(shop_id)))


# --------------------------------------------------------------------------
# Tier 1/2: shop + active listing setup helpers
# --------------------------------------------------------------------------
def setup_active_listing(shop_overrides=None, sp_overrides=None, listing_overrides=None):
    """Active shop + shipping profile + a published (ACTIVE) listing.
    Returns (shop, shipping_profile, listing) where listing is the post-publish state."""
    shop = create_shop(**(shop_overrides or {}))
    sp = create_shipping_profile(shop["id"], **(sp_overrides or {}))
    listing = create_listing(shop["id"], sp["id"], **(listing_overrides or {}))
    listing = publish_listing(shop["id"], listing["id"])
    return shop, sp, listing


# --------------------------------------------------------------------------
# Tier 3: full order lifecycle
# --------------------------------------------------------------------------
def setup_shop_with_completed_orders(num_orders=1, price_cents=100,
                                     free_shipping_threshold_cents=100,
                                     base_cost_cents=500, per_item_cost_cents=150,
                                     quantity=1, buyer_id="buyer_1"):
    """Active shop + published READY_TO_SHIP listing + N orders driven all the way to
    COMPLETED (pay -> ship -> deliver -> complete). Returns (shop, listing, orders).

    Defaults price 100 with a free-shipping threshold of 100 so each order totals 100
    cents (fee 55, net 45) — the canonical payout/settlement figures.
    """
    shop, sp, listing = setup_active_listing(
        sp_overrides={
            "base_cost_cents": base_cost_cents,
            "per_item_cost_cents": per_item_cost_cents,
            "free_shipping_threshold_cents": free_shipping_threshold_cents,
        },
        listing_overrides={"price_cents": price_cents, "quantity": 10},
    )
    orders = []
    for _ in range(num_orders):
        order = place_order(shop["id"], listing["id"], buyer_id, quantity=quantity)
        pay_order(order["id"], buyer_id)
        ship_order(order["id"], shop["id"])
        deliver_order(order["id"], shop["id"])
        complete_order(order["id"], buyer_id)
        orders.append(order)
    return shop, listing, orders


def setup_paid_ready_to_ship_order(price_cents=2000, quantity=1, listing_quantity=5):
    """Active shop + published READY_TO_SHIP listing + one PAID (not yet completed)
    order. Returns (shop, listing, order)."""
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 0, "per_item_cost_cents": 0},
        listing_overrides={"price_cents": price_cents, "quantity": listing_quantity},
    )
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=quantity)
    pay_order(order["id"], "buyer_1")
    return shop, listing, order


# --------------------------------------------------------------------------
# Tier 4/5: payout + settlement setup helpers
# --------------------------------------------------------------------------
def setup_two_completed_orders_and_payout():
    """Two completed 100-cent orders swept into a SCHEDULED payout.
    Returns (shop, listing, orders, payout). estimated_net_cents should be 90."""
    shop, listing, orders = setup_shop_with_completed_orders(
        num_orders=2, price_cents=100, free_shipping_threshold_cents=100)
    payout = create_payout(shop["id"])
    return shop, listing, orders, payout


def setup_payout_with_refunded_order():
    """Two completed 100-cent orders in a payout; a case opened on the second order is
    resolved with a full REFUND and the payout hold is released. Returns
    (shop, listing, orders, payout, case). At mark-paid settled_net_cents should be 45."""
    shop, listing, orders, payout = setup_two_completed_orders_and_payout()
    order_b = orders[1]
    case = open_dispute_case(order_b["id"], "buyer_1", "NOT_AS_DESCRIBED")
    seller_respond_case(case["id"], shop["id"], message="Looking into it")
    seller_resolve_case(case["id"], shop["id"], "REFUND", resolution="full refund")
    get_success_data(api_client.release_hold_payout(payout["id"], ADMIN))
    return shop, listing, orders, payout, case


def setup_completed_order_with_scheduled_payout(price_cents=100,
                                                free_shipping_threshold_cents=100):
    """One completed order swept into a SCHEDULED payout.
    Returns (shop, listing, order, payout)."""
    shop, listing, orders = setup_shop_with_completed_orders(
        num_orders=1, price_cents=price_cents,
        free_shipping_threshold_cents=free_shipping_threshold_cents)
    payout = create_payout(shop["id"])
    return shop, listing, orders[0], payout


def setup_completed_order_capture_stale_version():
    """One completed order; capture the shop version, then advance it by two via a
    vacation enable/return cycle so the captured value is stale.
    Returns (shop, listing, order, stale_version)."""
    shop, listing, orders = setup_shop_with_completed_orders(
        num_orders=1, price_cents=100, free_shipping_threshold_cents=100)
    stale_version = get_shop_version(shop["id"])
    get_success_data(api_client.enable_vacation(shop["id"], make_seller_headers(shop["id"])))
    get_success_data(api_client.return_from_vacation(shop["id"], make_seller_headers(shop["id"])))
    return shop, listing, orders[0], stale_version


# --------------------------------------------------------------------------
# Made-to-order setup helpers (cascade / capacity / conservation / parallel axes)
# --------------------------------------------------------------------------
def setup_mto_listing_with_material(material_stock=2, reorder_threshold=0,
                                    material_qty_per_unit=2, processing_time_days=7,
                                    price_cents=8000, max_concurrent_production=5,
                                    clock=CLOCK_DEFAULT):
    """Active shop + material + published MADE_TO_ORDER listing consuming that material.
    Returns (shop, shipping_profile, material, listing)."""
    set_clock(clock)
    shop = create_shop(max_concurrent_production=max_concurrent_production)
    sp = create_shipping_profile(shop["id"], base_cost_cents=0, per_item_cost_cents=0)
    material = create_material(shop["id"], stock_qty=material_stock,
                               reorder_threshold=reorder_threshold, name="Walnut blank")
    listing = create_listing(shop["id"], sp["id"], fulfillment_type="MADE_TO_ORDER",
                             primary_material_id=material["id"],
                             material_qty_per_unit=material_qty_per_unit,
                             processing_time_days=processing_time_days,
                             price_cents=price_cents, title="Made Item")
    listing = publish_listing(shop["id"], listing["id"])
    return shop, sp, material, listing


def setup_unpaid_mto_order_with_material(material_stock=2, reorder_threshold=0,
                                         material_qty_per_unit=2, quantity=1,
                                         processing_time_days=7, price_cents=8000):
    """MADE_TO_ORDER listing (with material) + one UNPAID order.
    Returns (shop, material, listing, order)."""
    shop, sp, material, listing = setup_mto_listing_with_material(
        material_stock=material_stock, reorder_threshold=reorder_threshold,
        material_qty_per_unit=material_qty_per_unit,
        processing_time_days=processing_time_days, price_cents=price_cents)
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=quantity)
    return shop, material, listing, order


def setup_mto_listing_no_material(processing_time_days=7, price_cents=5000,
                                  max_concurrent_production=5, clock=CLOCK_DEFAULT):
    """Active shop + published MADE_TO_ORDER listing that tracks no material.
    Returns (shop, shipping_profile, listing)."""
    set_clock(clock)
    shop = create_shop(max_concurrent_production=max_concurrent_production)
    sp = create_shipping_profile(shop["id"], base_cost_cents=0, per_item_cost_cents=0)
    listing = create_listing(shop["id"], sp["id"], fulfillment_type="MADE_TO_ORDER",
                             processing_time_days=processing_time_days,
                             price_cents=price_cents, title="Custom Ring")
    listing = publish_listing(shop["id"], listing["id"])
    return shop, sp, listing


def setup_unpaid_mto_order_no_material(processing_time_days=7, price_cents=5000,
                                       max_concurrent_production=5):
    """MADE_TO_ORDER listing (no material) + one UNPAID order.
    Returns (shop, listing, order)."""
    shop, sp, listing = setup_mto_listing_no_material(
        processing_time_days=processing_time_days, price_cents=price_cents,
        max_concurrent_production=max_concurrent_production)
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    return shop, listing, order


def setup_capacity_scenario():
    """max_concurrent_production=1 MADE_TO_ORDER listing (processing 7). One order is
    paid (IN_PRODUCTION, window 03-01..03-08); a second overlapping order is left UNPAID.
    Returns (shop, listing, order1, order2)."""
    shop, sp, listing = setup_mto_listing_no_material(
        processing_time_days=7, price_cents=12000, max_concurrent_production=1)
    order1 = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    pay_order(order1["id"], "buyer_1")
    order2 = place_order(shop["id"], listing["id"], "buyer_1", quantity=1)
    return shop, listing, order1, order2


# --------------------------------------------------------------------------
# Reviews & rating setup helpers
# --------------------------------------------------------------------------
def setup_two_reviewed_orders(ratings=(5, 5), price_cents=2000):
    """Two completed orders, each reviewed with the given rating.
    Returns (shop, listing, orders, reviews)."""
    shop, listing, orders = setup_shop_with_completed_orders(
        num_orders=2, price_cents=price_cents, base_cost_cents=0,
        per_item_cost_cents=0, free_shipping_threshold_cents=0)
    reviews = []
    for order, rating in zip(orders, ratings):
        reviews.append(create_review(order["id"], rating, "buyer_1"))
    return shop, listing, orders, reviews


# --------------------------------------------------------------------------
# Validation-precedence setup helpers
# --------------------------------------------------------------------------
def setup_inactive_listing_vacation_shop():
    """Published listing deactivated back to INACTIVE, then the shop set to VACATION.
    An order create now hits both the state precondition (listing not ACTIVE) and the
    business precondition (shop on vacation). Returns (shop, listing)."""
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 0, "per_item_cost_cents": 0},
        listing_overrides={"price_cents": 2000, "quantity": 5, "title": "Tote"},
    )
    get_success_data(api_client.deactivate_listing(listing["id"], make_seller_headers(shop["id"])))
    get_success_data(api_client.enable_vacation(shop["id"], make_seller_headers(shop["id"])))
    return shop, listing


def setup_order_then_vacation(order_quantity=5, listing_quantity=1):
    """READY_TO_SHIP listing (quantity 1); an order for quantity 5 is placed while the
    shop is ACTIVE, then the shop is set to VACATION. Paying now hits both the vacation
    precondition and the insufficient-inventory precondition. Returns (shop, listing, order)."""
    shop, sp, listing = setup_active_listing(
        sp_overrides={"base_cost_cents": 0, "per_item_cost_cents": 0},
        listing_overrides={"price_cents": 2000, "quantity": listing_quantity, "title": "Hat"},
    )
    order = place_order(shop["id"], listing["id"], "buyer_1", quantity=order_quantity)
    get_success_data(api_client.enable_vacation(shop["id"], make_seller_headers(shop["id"])))
    return shop, listing, order
