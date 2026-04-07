"""Composite setup helpers for e-commerce marketplace tests."""
import math
from datetime import datetime, timedelta, timezone

from prd_bench_runner.testing import get_success_data
from .api_client import api_client
from .factories import *
from .test_users import TEST_USERS
from .constants import COMMISSION_TIERS, RESERVATION_TIMEOUT_MINUTES


# ─── Header shortcuts ────────────────────────────────────────────────────────

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]


# =============================================================================
# Tier 1: State Progression
# =============================================================================
# For entities whose testable state differs from their initial state.
# Each function creates the entity and walks it to the desired status.


def create_and_approve_shop(**overrides):
    """Create a shop (PENDING_REVIEW) and approve it (ACTIVE).

    Returns the ACTIVE shop dict.  The shop is ready to receive products,
    promotions, and orders.
    """
    payload = create_shop_payload(**overrides)
    shop = get_success_data(api_client.create_shop(payload, _seller))
    approved = get_success_data(
        api_client.approve_shop(shop["id"], _admin)
    )
    assert approved["status"] == "ACTIVE"
    return approved


def create_and_list_product(shop_id, **overrides):
    """Create a product (DRAFT) under *shop_id* and list it (LISTED).

    The shop must already be ACTIVE.  Returns the LISTED product dict.
    """
    payload = create_product_payload(**overrides)
    product = get_success_data(
        api_client.create_product(shop_id, payload, _seller)
    )
    listed = get_success_data(
        api_client.list_product(shop_id, product["id"], _seller)
    )
    assert listed["status"] == "LISTED"
    return listed


def create_and_activate_promotion(shop_id, **overrides):
    """Create a promotion (DRAFT) under *shop_id* and activate it (ACTIVE).

    Sensible defaults are provided for time window and priority so callers
    only need to override what they care about.  Returns the ACTIVE promotion.
    """
    now = datetime.now(timezone.utc)
    defaults = {
        "start_time": (now - timedelta(hours=1)).isoformat(),
        "end_time": (now + timedelta(days=30)).isoformat(),
    }
    defaults.update(overrides)
    payload = create_promotion_payload(**defaults)
    promo = get_success_data(
        api_client.create_promotion(shop_id, payload, _seller)
    )
    activated = get_success_data(
        api_client.activate_promotion(shop_id, promo["id"], _seller)
    )
    assert activated["status"] == "ACTIVE"
    return activated


# =============================================================================
# Tier 2: Entity Hierarchy
# =============================================================================
# Combine Tier-1 helpers to stand up a shop with its children in one call.


def setup_shop_with_products(num_products=1, **overrides):
    """Approved shop with *num_products* LISTED products.

    Returns ``(shop, [product, ...])``.

    Keyword *product_overrides* (dict) is forwarded to every product.
    All other ``**overrides`` are forwarded to the shop.
    """
    product_overrides = overrides.pop("product_overrides", {})
    shop = create_and_approve_shop(**overrides)
    products = []
    for i in range(num_products):
        per_product = dict(product_overrides)
        if "product_name" not in per_product:
            per_product["product_name"] = f"Test Product {i + 1}"
        products.append(create_and_list_product(shop["id"], **per_product))
    return shop, products


def setup_shop_with_promotion(promo_overrides=None, **shop_overrides):
    """Approved shop + 1 LISTED product + 1 ACTIVE promotion.

    Returns ``(shop, product, promotion)``.
    """
    shop, products = setup_shop_with_products(num_products=1, **shop_overrides)
    product = products[0]
    promo = create_and_activate_promotion(
        shop["id"], **(promo_overrides or {})
    )
    return shop, product, promo


def setup_basic_order_scenario(**overrides):
    """Approved shop + 1 LISTED product ready for order placement.

    The product has ``inventory_count=100`` and ``base_price=99.99`` by
    default (overridable).  Returns ``(shop, product)``.
    """
    product_defaults = {
        "inventory_count": 100,
        "base_price": 99.99,
    }
    product_defaults.update(overrides.pop("product_overrides", {}))
    overrides["product_overrides"] = product_defaults
    shop, products = setup_shop_with_products(num_products=1, **overrides)
    return shop, products[0]


# =============================================================================
# Tier 3: Full Lifecycle Shortcuts
# =============================================================================
# Multi-step order lifecycles collapsed into single calls.


def place_and_pay_order(shop_id, items, **overrides):
    """Create an order, pay it, and confirm payment.

    *items* is a list of ``{"product_id": ..., "quantity": ...}`` dicts.

    Returns the PAID order (``order_status`` == CONFIRMED,
    ``payment_status`` == PAID).

    Uses customer headers for order creation and payment initiation, and
    admin headers for payment confirmation (simulating gateway callback).
    """
    order_payload = create_order_payload(shop_id=shop_id, items=items, **overrides)
    order = get_success_data(
        api_client.create_order(order_payload, _customer)
    )

    pay_payload = {
        "payment_method": overrides.get("payment_method", "CREDIT_CARD"),
        "transaction_ref": overrides.get(
            "transaction_ref", f"txn-{order['id'][:8]}"
        ),
    }
    get_success_data(api_client.pay_order(order["id"], pay_payload, _customer))

    confirmed = get_success_data(
        api_client.confirm_payment(order["id"], _admin)
    )
    assert confirmed["payment_status"] == "PAID"
    return confirmed


def place_pay_and_deliver_order(shop_id, items, **overrides):
    """Full order lifecycle: create -> pay -> confirm -> process -> ship -> deliver.

    Returns the COMPLETED order with ``commission_rate`` and
    ``commission_amount`` populated.  The shop's ``monthly_gmv`` and
    ``settlement_balance`` are updated as a side effect.
    """
    paid_order = place_and_pay_order(shop_id, items, **overrides)
    order_id = paid_order["id"]

    get_success_data(api_client.start_processing(order_id, _seller))
    get_success_data(api_client.ship_order(order_id, _seller))
    delivered = get_success_data(api_client.deliver_order(order_id, _seller))

    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["order_status"] == "COMPLETED"
    return delivered


def create_paid_order(shop_id, product_id, quantity=1):
    """Convenience: place a single-product order and pay it.

    Returns ``(order, order_items)`` where *order_items* is extracted
    from the order detail response.
    """
    items = [{"product_id": product_id, "quantity": quantity}]
    paid = place_and_pay_order(shop_id, items)
    order_items = get_order_items(paid["id"])
    return paid, order_items


# =============================================================================
# Tier 4: Accumulation / Threshold Targeting
# =============================================================================
# CRITICAL for commission tier boundary tests.  Without these, tests cannot
# reach the exact cumulative GMV needed for threshold assertions.


def setup_shop_at_gmv(target_gmv, product_price=100.0):
    """Create an approved shop and drive its ``monthly_gmv`` to *target_gmv*.

    Internally creates one LISTED product at *product_price* and places,
    pays, and delivers enough orders to accumulate *target_gmv*.

    Returns ``(shop, product)`` where *shop* is re-fetched after all
    deliveries so computed fields (``monthly_gmv``, ``settlement_balance``)
    are current.

    Example::

        shop, product = setup_shop_at_gmv(9500)
        # shop["monthly_gmv"] == 9500.0 (approximately)
    """
    if target_gmv <= 0:
        shop, products = setup_shop_with_products(
            num_products=1,
            product_overrides={"base_price": product_price, "inventory_count": 10000},
        )
        return shop, products[0]

    # Calculate how many orders we need
    num_orders = math.ceil(target_gmv / product_price)
    # Inventory must cover all orders
    inventory_needed = num_orders + 10  # small buffer

    shop, products = setup_shop_with_products(
        num_products=1,
        product_overrides={
            "base_price": product_price,
            "inventory_count": inventory_needed,
        },
    )
    product = products[0]

    # Place orders in batches — each order buys 1 unit at product_price
    remaining_gmv = target_gmv
    while remaining_gmv > 0:
        qty = 1
        order_value = product_price * qty
        if order_value > remaining_gmv and remaining_gmv > 0:
            # For the last order, adjust quantity if possible; otherwise
            # accept slight overshoot (product_price is the minimum unit).
            qty = 1
        place_pay_and_deliver_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": qty}],
        )
        remaining_gmv -= order_value

    shop = get_shop_after(shop["id"])
    return shop, product


def setup_shop_near_tier_boundary(tier_index=0, offset=-500):
    """Setup a shop whose ``monthly_gmv`` sits near a commission tier boundary.

    *tier_index*: which tier boundary to target (0 = first boundary at
    ``COMMISSION_TIERS[0]["upper"]``, 1 = second boundary, etc.).

    *offset*: signed distance from the tier boundary.  Negative means
    *below* the boundary; positive means *above*.

    Example::

        # GMV at 9500 (500 below the 10 000 tier-0 boundary)
        shop, product = setup_shop_near_tier_boundary(tier_index=0, offset=-500)

        # GMV at 50500 (500 above the 50 000 tier-1 boundary)
        shop, product = setup_shop_near_tier_boundary(tier_index=1, offset=500)

    Returns ``(shop, product)``.
    """
    tier = COMMISSION_TIERS[tier_index]
    boundary = tier["upper"]
    target_gmv = boundary + offset
    if target_gmv < 0:
        target_gmv = 0
    return setup_shop_at_gmv(target_gmv)


# =============================================================================
# Tier 5: Order + Refund Scenarios
# =============================================================================


def setup_completed_order_for_refund(**overrides):
    """Approved shop + product + completed (paid & delivered) order.

    Returns ``(shop, product, order)`` ready for a refund request.
    """
    product_overrides = overrides.pop("product_overrides", {})
    product_defaults = {"inventory_count": 100, "base_price": 99.99}
    product_defaults.update(product_overrides)

    shop, products = setup_shop_with_products(
        num_products=1,
        product_overrides=product_defaults,
        **{k: v for k, v in overrides.items() if k not in ("quantity",)},
    )
    product = products[0]
    quantity = overrides.get("quantity", 2)
    order = place_pay_and_deliver_order(
        shop["id"],
        [{"product_id": product["id"], "quantity": quantity}],
    )
    return shop, product, order


def setup_partial_refund_scenario(refund_items):
    """Setup a completed order, create a PARTIAL refund request, and approve it.

    *refund_items* is a list of ``{"order_item_id": ..., "quantity": ...}``
    dicts.  If you need concrete item IDs, call
    :func:`setup_completed_order_for_refund` first and inspect the order.

    This helper creates the full chain: shop + product + completed order +
    refund request (PARTIAL) + seller approval.

    Returns ``(order, refund)`` where *refund* is in APPROVED state
    (ready to be processed by admin).
    """
    shop, product, order = setup_completed_order_for_refund()

    # If caller didn't supply concrete item IDs, extract them from the order
    if refund_items is None or len(refund_items) == 0:
        items = get_order_items(order["id"])
        refund_items = [
            {"order_item_id": items[0]["id"], "quantity": 1}
        ]

    refund_payload = create_refund_payload(
        refund_type="PARTIAL",
        refund_items=refund_items,
    )
    refund = get_success_data(
        api_client.create_refund(order["id"], refund_payload, _customer)
    )
    approved_refund = get_success_data(
        api_client.approve_refund(order["id"], refund["id"], _seller)
    )
    assert approved_refund["status"] == "APPROVED"
    return order, approved_refund


# =============================================================================
# Tier 6: Settlement Scenarios
# =============================================================================


def setup_settlement_scenario(num_orders=3, product_price=100.0):
    """Shop with *num_orders* completed orders + a DRAFT settlement.

    Creates an approved shop, lists one product, places/pays/delivers
    *num_orders* orders, then creates a settlement covering the full
    period.

    Returns ``(shop, orders, settlement)`` where *settlement* is in
    DRAFT state (ready to submit).
    """
    inventory_needed = num_orders + 10
    shop, products = setup_shop_with_products(
        num_products=1,
        product_overrides={
            "base_price": product_price,
            "inventory_count": inventory_needed,
        },
    )
    product = products[0]

    period_start = datetime.now(timezone.utc) - timedelta(hours=1)
    orders = []
    for _ in range(num_orders):
        delivered = place_pay_and_deliver_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        orders.append(delivered)

    period_end = datetime.now(timezone.utc) + timedelta(hours=1)

    settlement_payload = create_settlement_payload(
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
    )
    settlement = get_success_data(
        api_client.create_settlement(shop["id"], settlement_payload, _seller)
    )
    assert settlement["status"] == "DRAFT"
    return shop, orders, settlement


def setup_submitted_settlement(shop_id, **overrides):
    """Create a settlement and submit it.

    The shop must already have completed orders so that ``net_amount > 0``.

    Returns the settlement in PENDING_APPROVAL state.
    """
    now = datetime.now(timezone.utc)
    defaults = {
        "period_start": (now - timedelta(days=30)).isoformat(),
        "period_end": now.isoformat(),
    }
    defaults.update(overrides)
    settlement_payload = create_settlement_payload(**defaults)
    settlement = get_success_data(
        api_client.create_settlement(shop_id, settlement_payload, _seller)
    )
    submitted = get_success_data(
        api_client.submit_settlement(shop_id, settlement["id"], _seller)
    )
    assert submitted["status"] == "PENDING_APPROVAL"
    return submitted


# =============================================================================
# Helper Utilities
# =============================================================================


def get_order_items(order_id, headers=None):
    """Fetch order details and extract the items list.

    Uses admin headers by default (full visibility).  Returns a list of
    order-item dicts.
    """
    headers = headers or _admin
    order_detail = get_success_data(
        api_client.get_order(order_id, headers)
    )
    # The order detail response may nest items under different keys
    # depending on the implementation.  Try common conventions.
    if "items" in order_detail:
        return order_detail["items"]
    if "order_items" in order_detail:
        return order_detail["order_items"]
    # Fallback: if items are returned as a top-level array alongside the
    # order object, the validator already extracted data — return as-is.
    return order_detail.get("items", [])


def get_shop_after(shop_id):
    """Re-fetch a shop to obtain updated computed fields.

    Useful after a sequence of order deliveries or refunds to read the
    current ``monthly_gmv`` and ``settlement_balance``.
    """
    return get_success_data(api_client.get_shop(shop_id, _admin))
