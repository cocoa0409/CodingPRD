"""Composite setup helpers (6 tiers) for food delivery platform tests.

Every fixture uses get_success_data() internally so setup failures produce
clear errors instead of confusing assertion failures in tests.
"""
import math
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_restaurant_payload,
    create_menu_item_payload,
    create_customer_payload,
    create_rider_payload,
    create_order_payload,
    create_delivery_payload,
    create_promotion_payload,
    create_complaint_payload,
    create_rating_payload,
    create_surge_zone_payload,
    create_settlement_run_payload,
    create_top_up_payload,
    create_resolve_complaint_payload,
)

_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]
_rider = TEST_USERS["rider_headers"]
_cs = TEST_USERS["cs_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Tier 1: State Progression — single entity brought to a target state
# ═══════════════════════════════════════════════════════════════════════════

def create_and_approve_restaurant(**overrides):
    """Create a restaurant and approve it to ACTIVE status. Returns the ACTIVE restaurant."""
    payload = create_restaurant_payload(**overrides)
    r = get_success_data(api_client.create_restaurant(payload, _admin))
    rid = r["id"]
    r = get_success_data(api_client.approve_restaurant(rid, _admin))
    assert r["status"] == "ACTIVE", f"Expected ACTIVE, got {r['status']}"
    return r


def create_active_customer(wallet_cents=50000, **overrides):
    """Create a customer (ACTIVE by default) and top up wallet. Returns customer dict."""
    payload = create_customer_payload(**overrides)
    c = get_success_data(api_client.create_customer(payload, _customer))
    if wallet_cents > 0:
        c = get_success_data(
            api_client.top_up_wallet(c["id"], create_top_up_payload(wallet_cents), _customer)
        )
    return c


def create_and_approve_rider(vehicle_type="MOTORCYCLE", **overrides):
    """Create a rider and approve to ACTIVE. Returns ACTIVE rider."""
    payload = create_rider_payload(vehicle_type=vehicle_type, **overrides)
    r = get_success_data(api_client.create_rider(payload, _admin))
    rid = r["id"]
    r = get_success_data(api_client.approve_rider(rid, _admin))
    # Set online
    r = get_success_data(api_client.update_rider(rid, {"is_online": True}, _rider))
    assert r["status"] == "ACTIVE", f"Expected ACTIVE, got {r['status']}"
    return r


# ═══════════════════════════════════════════════════════════════════════════
# Tier 2: Entity Hierarchy — parent + child setups
# ═══════════════════════════════════════════════════════════════════════════

def setup_restaurant_with_menu_items(num_items=2, item_overrides=None, **restaurant_overrides):
    """Create an ACTIVE restaurant with N available menu items.

    Returns (restaurant, [menu_items]).
    """
    rest = create_and_approve_restaurant(**restaurant_overrides)
    items = []
    for i in range(num_items):
        ov = {}
        if item_overrides and i < len(item_overrides):
            ov = item_overrides[i]
        payload = create_menu_item_payload(**ov)
        mi = get_success_data(api_client.create_menu_item(rest["id"], payload, _restaurant))
        items.append(mi)
    return rest, items


def setup_basic_order_scenario(
    wallet_cents=100000,
    num_items=1,
    item_price_cents=1500,
    tip_cents=0,
    commission_rate=0.15,
    restaurant_overrides=None,
    order_overrides=None,
):
    """Create ACTIVE restaurant + menu items + ACTIVE customer with wallet + PLACED order.

    Returns (restaurant, menu_items, customer, order).
    """
    r_ov = restaurant_overrides or {}
    r_ov.setdefault("commission_rate", commission_rate)
    rest, menu_items = setup_restaurant_with_menu_items(
        num_items=num_items,
        item_overrides=[{"base_price_cents": item_price_cents}] * num_items,
        **r_ov,
    )
    # Ensure restaurant is accepting orders
    get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))

    customer = create_active_customer(wallet_cents=wallet_cents)
    items = [{"menu_item_id": mi["id"], "quantity": 1} for mi in menu_items]

    o_ov = order_overrides or {}
    o_ov.setdefault("tip_cents", tip_cents)
    order_payload = create_order_payload(customer["id"], rest["id"], items, **o_ov)
    order = get_success_data(api_client.create_order(order_payload, _customer))

    return rest, menu_items, customer, order


# ═══════════════════════════════════════════════════════════════════════════
# Tier 3: Full Lifecycle Shortcuts
# ═══════════════════════════════════════════════════════════════════════════

def confirm_order(order_id):
    """Confirm a PLACED order. Returns confirmed order."""
    return get_success_data(api_client.confirm_order(order_id, _restaurant))


def prepare_order(order_id):
    """Move order through CONFIRMED -> PREPARING. Returns PREPARING order."""
    return get_success_data(api_client.start_preparing_order(order_id, _restaurant))


def mark_order_ready(order_id):
    """Move order through PREPARING -> READY_FOR_PICKUP. Returns order."""
    return get_success_data(api_client.mark_order_ready(order_id, _restaurant))


def confirm_and_prepare_order(order_id):
    """Confirm, start preparing, and mark ready. Returns READY_FOR_PICKUP order."""
    confirm_order(order_id)
    prepare_order(order_id)
    return mark_order_ready(order_id)


def assign_rider_to_order(order_id, rider_id):
    """Assign a rider to an order, creating a delivery. Returns delivery."""
    payload = create_delivery_payload(rider_id)
    return get_success_data(api_client.create_delivery(order_id, payload, _admin))


def progress_delivery_to_restaurant(order_id, delivery_id):
    """Move delivery from ASSIGNED -> HEADING_TO_RESTAURANT -> AT_RESTAURANT. Returns delivery."""
    get_success_data(api_client.start_delivery(order_id, delivery_id, _rider))
    return get_success_data(api_client.arrive_at_restaurant(order_id, delivery_id, _rider))


def pickup_and_deliver(order_id, delivery_id):
    """Pickup order and mark as delivered. Returns delivered order."""
    get_success_data(api_client.pickup_order(order_id, _rider))
    return get_success_data(api_client.deliver_order(order_id, _rider))


def complete_order_lifecycle(
    wallet_cents=100000,
    item_price_cents=1500,
    tip_cents=0,
    commission_rate=0.15,
    vehicle_type="MOTORCYCLE",
    num_items=1,
    restaurant_overrides=None,
    order_overrides=None,
):
    """Full cycle: create restaurant, customer, rider, order, confirm, prepare, assign, pickup, deliver.

    Returns (restaurant, menu_items, customer, rider, order, delivery).
    """
    rest, menu_items, customer, order = setup_basic_order_scenario(
        wallet_cents=wallet_cents,
        num_items=num_items,
        item_price_cents=item_price_cents,
        tip_cents=tip_cents,
        commission_rate=commission_rate,
        restaurant_overrides=restaurant_overrides,
        order_overrides=order_overrides,
    )

    rider = create_and_approve_rider(vehicle_type=vehicle_type)
    order = confirm_order(order["id"])
    prepare_order(order["id"])
    mark_order_ready(order["id"])

    delivery = assign_rider_to_order(order["id"], rider["id"])
    progress_delivery_to_restaurant(order["id"], delivery["id"])
    order = pickup_and_deliver(order["id"], delivery["id"])

    # Refresh delivery
    delivery = get_success_data(api_client.get_delivery(order["id"], delivery["id"], _admin))
    return rest, menu_items, customer, rider, order, delivery


def create_confirmed_order_with_delivery(
    wallet_cents=100000,
    item_price_cents=1500,
    tip_cents=0,
    vehicle_type="MOTORCYCLE",
):
    """Create a confirmed order with an assigned delivery at AT_RESTAURANT.

    Returns (restaurant, customer, rider, order, delivery).
    """
    rest, menu_items, customer, order = setup_basic_order_scenario(
        wallet_cents=wallet_cents,
        item_price_cents=item_price_cents,
        tip_cents=tip_cents,
    )
    rider = create_and_approve_rider(vehicle_type=vehicle_type)
    order = confirm_order(order["id"])
    delivery = assign_rider_to_order(order["id"], rider["id"])
    prepare_order(order["id"])
    mark_order_ready(order["id"])
    progress_delivery_to_restaurant(order["id"], delivery["id"])
    return rest, customer, rider, order, delivery


# ═══════════════════════════════════════════════════════════════════════════
# Tier 4: Accumulation / Threshold Targeting
# ═══════════════════════════════════════════════════════════════════════════

def setup_rider_with_penalty_points(target_points, vehicle_type="MOTORCYCLE"):
    """Create a rider and accumulate penalty points by cancelling deliveries.

    Each cancellation gives 20 points. This will create enough cancelled
    deliveries to reach (but not exceed) the target points.

    Returns (rider, last_order, last_delivery) — rider may be SUSPENDED if >= 100.
    """
    rider = create_and_approve_rider(vehicle_type=vehicle_type)
    cancellations_needed = target_points // 20
    last_order = None
    last_delivery = None

    for _ in range(cancellations_needed):
        rest, menu_items, customer, order = setup_basic_order_scenario()
        order = confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        get_success_data(api_client.cancel_delivery(order["id"], delivery["id"], _rider))
        last_order = order
        last_delivery = delivery

    # Refresh rider
    rider = get_success_data(api_client.get_rider(rider["id"], _admin))
    return rider, last_order, last_delivery


def setup_delivered_order_for_rating(
    wallet_cents=100000,
    item_price_cents=2000,
    tip_cents=200,
):
    """Complete an order lifecycle suitable for rating submission.

    Returns (restaurant, customer, rider, order, delivery).
    """
    rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
        wallet_cents=wallet_cents,
        item_price_cents=item_price_cents,
        tip_cents=tip_cents,
    )
    return rest, customer, rider, order, delivery


def setup_delivered_order_for_complaint(**kwargs):
    """Alias for delivered order setup suitable for complaint filing."""
    return setup_delivered_order_for_rating(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# Tier 5: Terminal State / Settlement
# ═══════════════════════════════════════════════════════════════════════════

def setup_settlement_scenario(num_orders=1, item_price_cents=2000):
    """Create N delivered orders and run a settlement.

    Returns (restaurant, rider, customer, orders, settlements).
    """
    orders = []
    rest = None
    rider = None
    customer = None

    for i in range(num_orders):
        if i == 0:
            r, mi, c, rd, o, d = complete_order_lifecycle(
                item_price_cents=item_price_cents, wallet_cents=200000
            )
            rest = r
            rider = rd
            customer = c
        else:
            # Reuse existing restaurant, customer, rider for subsequent orders
            cust = get_success_data(api_client.get_customer(customer["id"], _admin))
            if cust["wallet_balance_cents"] < 50000:
                get_success_data(
                    api_client.top_up_wallet(customer["id"], create_top_up_payload(100000), _customer)
                )
            # Need a new order with the same setup
            r2, mi2, c2, rd2, o2, d2 = complete_order_lifecycle(
                item_price_cents=item_price_cents, wallet_cents=200000
            )
            o = o2
        orders.append(o)

    # Run settlement
    settlement_resp = get_success_data(
        api_client.run_settlement(create_settlement_run_payload(), _admin)
    )
    return rest, rider, customer, orders, settlement_resp


# ═══════════════════════════════════════════════════════════════════════════
# Tier 6: Concurrency / Race Condition helpers
# ═══════════════════════════════════════════════════════════════════════════

def setup_race_order_confirmation():
    """Setup for concurrent order confirmation attempts.

    Returns (order, restaurant_headers, restaurant_headers_2).
    """
    rest, menu_items, customer, order = setup_basic_order_scenario()
    return order, _restaurant, TEST_USERS["restaurant_headers_2"]


def setup_race_delivery_assignment(order_id):
    """Create two riders for concurrent delivery assignment.

    Returns (rider1, rider2).
    """
    rider1 = create_and_approve_rider()
    rider2 = create_and_approve_rider()
    return rider1, rider2


# ═══════════════════════════════════════════════════════════════════════════
# Promotion helpers
# ═══════════════════════════════════════════════════════════════════════════

def create_active_promotion(**overrides):
    """Create an ACTIVE promotion. Returns promotion dict."""
    payload = create_promotion_payload(**overrides)
    return get_success_data(api_client.create_promotion(payload, _admin))


def create_active_surge_zone(**overrides):
    """Create an ACTIVE surge zone. Returns surge zone dict."""
    payload = create_surge_zone_payload(**overrides)
    return get_success_data(api_client.create_surge_zone(payload, _admin))
