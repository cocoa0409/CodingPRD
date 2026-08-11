"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts empty).
Uses get_success_data() so setup failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_product_payload, create_subscription_payload,
    create_delivery_route_payload, create_delivery_window_payload,
    create_order_payload, order_line, create_payment_payload,
)
from .test_users import TEST_USERS

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
DR = TEST_USERS["driver_headers"]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ─── Tier 0: clock ─────────────────────────────────────────────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, OM))


# ─── Tier 1: single-entity creators ────────────────────────────────────────

def create_customer(postal_code="01010", **overrides):
    res = api_client.create_customer(
        create_customer_payload(postal_code=postal_code, **overrides), CS)
    return get_success_data(res)


def create_product(**overrides):
    res = api_client.create_product(create_product_payload(**overrides), OM)
    return get_success_data(res)


def create_route(prefixes=("0",), capacity=100.0, **overrides):
    res = api_client.create_delivery_route(
        create_delivery_route_payload(
            service_postal_prefixes=list(prefixes),
            capacity_cord_equivalent=capacity, **overrides), RP)
    return get_success_data(res)


def create_window(route_id, service_date="2026-08-15", start_hour=8, end_hour=18,
                  capacity=100.0):
    res = api_client.create_delivery_window(
        create_delivery_window_payload(
            route_id, service_date=service_date, start_hour=start_hour,
            end_hour=end_hour, capacity_cord_equivalent=capacity), RP)
    return get_success_data(res)


def create_subscription(customer_id, **overrides):
    """Create a subscription with a fresh expected_customer_version (OCC, PRD §2.7)."""
    customer = get_success_data(api_client.get_customer(customer_id, CS))
    res = api_client.create_subscription(
        create_subscription_payload(
            customer_id, customer["version"], **overrides), CS)
    return get_success_data(res)


def create_activated_subscription(customer_id, **overrides):
    """Create + activate a subscription. Clock must be on/before Nov 1 of season_year."""
    sub = create_subscription(customer_id, **overrides)
    return get_success_data(api_client.activate_subscription(sub["id"], OM))


# ─── Tier 2: basic catalog + routing scenario ──────────────────────────────

def setup_catalog_with_route(postal_code="01010", prefixes=("0",), **product_overrides):
    """Customer + product + a route matching the postal code. Returns (customer, product, route)."""
    customer = create_customer(postal_code=postal_code)
    product = create_product(**product_overrides)
    route = create_route(prefixes=prefixes)
    return customer, product, route


def create_order(customer_id, product_id, quantity, postal_code="01010",
                 requested_delivery_date="2026-08-15", **overrides):
    """Create a DRAFT order with one line. Returns the order."""
    res = api_client.create_order(
        create_order_payload(
            customer_id, [order_line(product_id, quantity)],
            delivery_postal_code=postal_code,
            requested_delivery_date=requested_delivery_date, **overrides), CS)
    return get_success_data(res)


# ─── Tier 3: lifecycle shortcuts ───────────────────────────────────────────

def pay_order_in_full(order_id):
    """AUTHORIZE + CAPTURE the full invoice amount. Returns the updated order
    (payment PAID; fulfillment cascades PENDING_PAYMENT -> CONFIRMED, PRD §3.8)."""
    order = get_success_data(api_client.get_order(order_id, CS))
    amount = order["total_cents"]
    get_success_data(api_client.post_payment(
        order_id, create_payment_payload("AUTHORIZE", amount), CS))
    get_success_data(api_client.post_payment(
        order_id, create_payment_payload("CAPTURE", amount), CS))
    return get_success_data(api_client.get_order(order_id, CS))


def submit_and_pay(order_id):
    """Submit DRAFT -> PENDING_PAYMENT, then pay in full -> CONFIRMED."""
    get_success_data(api_client.submit_order(order_id, CS))
    return pay_order_in_full(order_id)


def schedule_order(order_id, window_id):
    """Schedule a CONFIRMED order into a window with a fresh OCC version."""
    order = get_success_data(api_client.get_order(order_id, RP))
    res = api_client.schedule_order(
        order_id, {"delivery_window_id": window_id,
                   "expected_order_version": order["version"]}, RP)
    return get_success_data(res)


def deliver_scheduled_order(order_id, window, moisture_pct=18.0,
                            delivery_time=None, driver_headers=None):
    """From SCHEDULED: lock window, move clock into the window, dispatch,
    record a passing moisture reading on every line, deliver. Returns order."""
    driver_headers = driver_headers or DR
    get_success_data(api_client.lock_delivery_window(window["id"], RP))
    service_date = window["service_date"]
    hour = window["start_hour"] + 1
    at = delivery_time or f"{service_date}T{hour:02d}:00:00Z"
    set_clock(at)
    get_success_data(api_client.dispatch_order(order_id, driver_headers))
    lines = get_success_data(api_client.list_order_lines(order_id, driver_headers))
    for line in lines:
        get_success_data(api_client.create_moisture_reading(
            line["id"], {"moisture_pct": moisture_pct}, driver_headers))
    return get_success_data(api_client.deliver_order(order_id, driver_headers))


def create_delivered_order(customer_id, product_id, quantity, route,
                           postal_code="01010", service_date="2026-08-15",
                           requested_delivery_date=None, moisture_pct=18.0,
                           window_hours=(8, 18), **order_overrides):
    """Full lifecycle: DRAFT -> PENDING_PAYMENT -> CONFIRMED -> SCHEDULED ->
    OUT_FOR_DELIVERY -> DELIVERED. Returns (order, window)."""
    requested_delivery_date = requested_delivery_date or service_date
    window = create_window(route["id"], service_date=service_date,
                           start_hour=window_hours[0], end_hour=window_hours[1],
                           capacity=route["capacity_cord_equivalent"])
    order = create_order(customer_id, product_id, quantity,
                         postal_code=postal_code,
                         requested_delivery_date=requested_delivery_date,
                         **order_overrides)
    submit_and_pay(order["id"])
    schedule_order(order["id"], window["id"])
    order = deliver_scheduled_order(order["id"], window, moisture_pct=moisture_pct)
    return order, window


# ─── Tier 4: accumulation / threshold targeting ────────────────────────────

def drive_customer_lifetime_ce(customer_id, product_id, route, target_ce,
                               postal_code="01010", chunk_ce=6.0,
                               first_service_date="2026-10-20"):
    """Deliver enough orders for the customer's lifetime cord-equivalent to reach
    target_ce. Uses mid-October dates (outside the winter peak)."""
    delivered = 0.0
    day = int(first_service_date[-2:])
    while delivered < target_ce - 1e-9:
        qty = min(chunk_ce, target_ce - delivered)
        service_date = f"2026-10-{day:02d}"
        create_delivered_order(
            customer_id, product_id, qty, route, postal_code=postal_code,
            service_date=service_date)
        delivered += qty
        day += 5
    customer = get_success_data(api_client.get_customer(customer_id, CS))
    return customer
