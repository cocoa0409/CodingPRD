"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.

Fixtures use get_success_data() (lenient 2xx validator) for setup calls so a
broken precondition surfaces as a clear "Setup failed" rather than a confusing
downstream assertion.

Identity threading: after creating an entity_backed entity (Restaurant,
Customer, Dasher) every ownership-gated call uses make_<role>_headers(entity_id),
never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_zone_payload, create_restaurant_payload, create_menu_item_payload,
    create_customer_payload, create_dasher_payload, create_order_payload,
    line_item, dispatch_payload, issue_payload, tip_adjustment_payload,
    add_line_item_payload,
)
from .test_users import (
    make_admin_headers, make_support_headers,
    make_restaurant_headers, make_customer_headers, make_dasher_headers,
)

ADMIN = make_admin_headers()
SUPPORT = make_support_headers()


# ===========================================================================
# Tier 0 — atomic creators (return the created resource dict)
# ===========================================================================
def create_zone(**overrides) -> dict:
    """PlatformAdmin creates a zone. Returns the Zone."""
    resp = api_client.create_zone(create_zone_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_restaurant(zone_id, **overrides) -> dict:
    """PlatformAdmin registers a restaurant. Returns the Restaurant."""
    resp = api_client.create_restaurant(create_restaurant_payload(zone_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_menu_item(restaurant_id, **overrides) -> dict:
    """Owning Restaurant adds a menu item (ownership-gated). Returns MenuItem."""
    resp = api_client.create_menu_item(
        restaurant_id, create_menu_item_payload(**overrides),
        make_restaurant_headers(restaurant_id),
    )
    return get_success_data(resp)


def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_dasher(home_zone_id, **overrides) -> dict:
    resp = api_client.create_dasher(create_dasher_payload(home_zone_id, **overrides), ADMIN)
    return get_success_data(resp)


# ===========================================================================
# Tier 1 — base scenarios
# ===========================================================================
def setup_zone_restaurant_menu(zone_overrides=None, restaurant_overrides=None,
                               item_overrides=None):
    """Zone (DT) + ACTIVE open restaurant + one LISTED menu item.

    Returns (zone, restaurant, menu_item).
    """
    zone = create_zone(**(zone_overrides or {}))
    restaurant = create_restaurant(zone["id"], **(restaurant_overrides or {}))
    item = create_menu_item(restaurant["id"], **(item_overrides or {}))
    return zone, restaurant, item


def setup_market(zone_overrides=None, restaurant_overrides=None, item_overrides=None,
                 dasher_overrides=None):
    """Zone + restaurant + menu item + one ONLINE dasher + one customer.

    The most common base for order-lifecycle tests.
    Returns (zone, restaurant, item, dasher, customer).
    """
    zone, restaurant, item = setup_zone_restaurant_menu(
        zone_overrides, restaurant_overrides, item_overrides)
    dasher = create_dasher(zone["id"], **(dasher_overrides or {}))
    customer = create_customer()
    return zone, restaurant, item, dasher, customer


# ===========================================================================
# Tier 2 — order placement helpers
# ===========================================================================
def place_order(customer_id, restaurant_id, items, **overrides) -> dict:
    """Customer places an order (ownership-gated on customer_id).

    `items` is a list of (menu_item_id, quantity) tuples or line-item dicts.
    Returns the Order.
    """
    line_items = []
    for it in items:
        if isinstance(it, dict):
            line_items.append(it)
        else:
            mid, qty = it
            line_items.append(line_item(mid, qty))
    resp = api_client.create_order(
        create_order_payload(customer_id, restaurant_id, line_items, **overrides),
        make_customer_headers(customer_id),
    )
    return get_success_data(resp)


def place_simple_order(customer_id, restaurant_id, menu_item_id, quantity=1, **overrides) -> dict:
    """Single-line ASAP order. Returns the Order."""
    return place_order(customer_id, restaurant_id,
                       [line_item(menu_item_id, quantity)], **overrides)


def get_first_line_item(order_id, customer_id) -> dict:
    """Return the first OrderLineItem of an order (via the owning customer)."""
    resp = api_client.list_line_items(order_id, make_customer_headers(customer_id))
    data, _ = _paginated(resp)
    return data[0]


def _paginated(resp):
    body = resp.json()
    return body["data"], body["meta"]


# ===========================================================================
# Tier 3 — lifecycle shortcuts
# ===========================================================================
def dispatch(order_id, restaurant_id, expected_version) -> dict:
    """Owning Restaurant dispatches; returns the created Delivery."""
    resp = api_client.dispatch_order(
        order_id, dispatch_payload(expected_version),
        make_restaurant_headers(restaurant_id),
    )
    return get_success_data(resp)


def setup_order_routed(zone_overrides=None, restaurant_overrides=None,
                       item_overrides=None, dasher_overrides=None,
                       order_overrides=None):
    """Place a single ASAP order and dispatch it (order ROUTED, Delivery OFFERED).

    Returns dict with zone, restaurant, item, dasher, customer, order, delivery.
    """
    zone, restaurant, item, dasher, customer = setup_market(
        zone_overrides, restaurant_overrides, item_overrides, dasher_overrides)
    order = place_simple_order(customer["id"], restaurant["id"], item["id"],
                               **(order_overrides or {}))
    delivery = dispatch(order["id"], restaurant["id"], order["version"])
    return {
        "zone": zone, "restaurant": restaurant, "item": item, "dasher": dasher,
        "customer": customer, "order": order, "delivery": delivery,
    }


def setup_order_accepted(**kwargs):
    """Order ROUTED with the Delivery accepted (ACCEPTED). Returns the same dict."""
    ctx = setup_order_routed(**kwargs)
    resp = api_client.accept_delivery(ctx["delivery"]["id"],
                                      make_dasher_headers(ctx["dasher"]["id"]))
    ctx["delivery"] = get_success_data(resp)
    return ctx


def setup_order_picked_up(**kwargs):
    """Order PICKED_UP / Delivery EN_ROUTE. Returns the same dict."""
    ctx = setup_order_accepted(**kwargs)
    resp = api_client.pickup_delivery(ctx["delivery"]["id"],
                                      make_dasher_headers(ctx["dasher"]["id"]))
    ctx["delivery"] = get_success_data(resp)
    return ctx


def setup_order_delivered(**kwargs):
    """Order DELIVERED / Delivery DELIVERED / billing SETTLED. Returns the dict."""
    ctx = setup_order_picked_up(**kwargs)
    resp = api_client.deliver_delivery(ctx["delivery"]["id"],
                                       make_dasher_headers(ctx["dasher"]["id"]))
    ctx["delivery"] = get_success_data(resp)
    return ctx


# ===========================================================================
# Tier 4 — demand / threshold targeting
# ===========================================================================
def place_filler_orders(customer_id, restaurant_id, menu_item_id, count):
    """Place `count` ASAP orders left in PLACED to raise the zone's
    active_order_count (each placed order counts toward demand)."""
    orders = []
    for _ in range(count):
        orders.append(place_simple_order(customer_id, restaurant_id, menu_item_id))
    return orders


def setup_demand_then_measure(filler_count, zone_overrides=None,
                              restaurant_overrides=None, item_overrides=None,
                              measured_overrides=None, with_dasher=False,
                              dasher_overrides=None):
    """Build a zone with `filler_count` PLACED filler orders, then place one
    more measured order so its placement sees demand == filler_count + 1.

    Returns dict with zone, restaurant, item, customer, fillers, order
    (the measured order), and optionally dasher.
    """
    zone, restaurant, item = setup_zone_restaurant_menu(
        zone_overrides, restaurant_overrides, item_overrides)
    customer = create_customer()
    dasher = None
    if with_dasher:
        dasher = create_dasher(zone["id"], **(dasher_overrides or {}))
    fillers = place_filler_orders(customer["id"], restaurant["id"], item["id"], filler_count)
    order = place_simple_order(customer["id"], restaurant["id"], item["id"],
                               **(measured_overrides or {}))
    ctx = {
        "zone": zone, "restaurant": restaurant, "item": item,
        "customer": customer, "fillers": fillers, "order": order,
    }
    if dasher is not None:
        ctx["dasher"] = dasher
    return ctx


# ===========================================================================
# Tier 5 — issue / refund scenarios (post-delivery)
# ===========================================================================
def setup_issue_ready(quantity=1, missing_quantity=1, refund_destination=None,
                      item_price_cents=500, zone_overrides=None):
    """Full lifecycle to DELIVERED for a single-line order of `quantity` units of
    a $`item_price_cents` item, then file an OPEN missing-item issue.

    service_fee_bps defaults to 0 for clean refund math.
    Returns dict: zone, restaurant, item, dasher, customer, order, delivery,
    line_item, issue.
    """
    zo = {"service_fee_bps": 0}
    if zone_overrides:
        zo.update(zone_overrides)
    zone, restaurant, item = setup_zone_restaurant_menu(
        zone_overrides=zo, item_overrides={"price_cents": item_price_cents})
    dasher = create_dasher(zone["id"])
    customer = create_customer()
    order = place_simple_order(customer["id"], restaurant["id"], item["id"],
                               quantity=quantity)
    li = get_first_line_item(order["id"], customer["id"])
    delivery = dispatch(order["id"], restaurant["id"], order["version"])
    dh = make_dasher_headers(dasher["id"])
    delivery = get_success_data(api_client.accept_delivery(delivery["id"], dh))
    delivery = get_success_data(api_client.pickup_delivery(delivery["id"], dh))
    delivery = get_success_data(api_client.deliver_delivery(delivery["id"], dh))
    extra = {}
    if refund_destination is not None:
        extra["refund_destination"] = refund_destination
    issue = get_success_data(api_client.file_issue(
        order["id"],
        issue_payload(li["id"], missing_quantity, **extra),
        make_customer_headers(customer["id"]),
    ))
    return {
        "zone": zone, "restaurant": restaurant, "item": item, "dasher": dasher,
        "customer": customer, "order": order, "delivery": delivery,
        "line_item": li, "issue": issue,
    }


# ===========================================================================
# Tier 6 — scheduled order helpers (use the test clock)
# ===========================================================================
def set_clock(to_iso8601):
    """Set the server's logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def setup_scheduled_order(scheduled_for, clock_iso="2026-06-07T10:00:00Z",
                          restaurant_overrides=None):
    """Set the clock, build a market (no dasher), and place one scheduled order.

    Returns dict: zone, restaurant, item, customer, order.
    """
    set_clock(clock_iso)
    zone, restaurant, item = setup_zone_restaurant_menu(
        restaurant_overrides=restaurant_overrides)
    customer = create_customer()
    order = place_order(customer["id"], restaurant["id"],
                        [line_item(item["id"], 1)], scheduled_for=scheduled_for)
    return {"zone": zone, "restaurant": restaurant, "item": item,
            "customer": customer, "order": order}
