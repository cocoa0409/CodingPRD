"""Delivery vehicle windows (buffered overlap), capacity, and fulfill-gating.

Difficulty: vehicle_window_buffer_abuts_exactly_allowed, vehicle_buffered_window_overlap,
order_fulfill_requires_delivery_delivered.
Corner: vehicle_capacity_exceeded_on_delivery.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


def _vehicle_with_first_delivery(turnaround_minutes=30, ws="2026-04-02T10:00:00Z", we="2026-04-02T11:00:00Z"):
    """Nursery + RETAIL account + DRY_GOOD product + vehicle with one booked delivery
    [ws, we). Returns (nursery, account, product, vehicle)."""
    X.set_clock("2026-04-01T07:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    vehicle = X.create_vehicle(nursery["id"], label="T-1", vehicle_type="FLATBED",
                               capacity_cubic_yards=50, turnaround_minutes=turnaround_minutes)
    product = X.create_product(nursery["id"], sku="DG-7", name="Stone", unit_price_cents=500)
    order_a = X.create_order(account["id"])
    X.add_line(order_a["id"], product["id"], qty=1)
    X.book_delivery(order_a["id"], vehicle["id"], ws, we)
    return nursery, account, product, vehicle


def _second_order(account_id, product_id):
    order = X.create_order(account_id)
    X.add_line(order["id"], product_id, qty=1)
    return order


# ---------------------------------------------------------------------------
# Difficulty: vehicle_window_buffer_abuts_exactly_allowed
# ---------------------------------------------------------------------------
def test_second_window_at_buffer_end_exactly_allowed(api):
    """PRD §3.8: "Two windows that merely abut — one ending exactly when the
    buffered interval of another begins — do not collide."

    Design: Difficulty/boundary_precision_check/vehicle_window_buffer_abuts_exactly_allowed
    """
    nursery, account, product, vehicle = _vehicle_with_first_delivery(turnaround_minutes=30)
    order_b = _second_order(account["id"], product["id"])
    # first busy interval ends at 11:00 + 30min = 11:30; start exactly at 11:30 abuts -> allowed.
    resp = api.create_delivery(
        order_b["id"],
        F.create_delivery_payload(vehicle["id"], "2026-04-02T11:30:00Z", "2026-04-02T12:00:00Z"),
        INV,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


def test_second_window_one_minute_before_buffer_end_collides(api):
    """PRD §3.8: "two deliveries collide when their busy intervals intersect, and a
    collision is rejected with `ERR_VEHICLE_WINDOW_CONFLICT`."

    Design: Difficulty/boundary_precision_check/vehicle_window_buffer_abuts_exactly_allowed
    """
    nursery, account, product, vehicle = _vehicle_with_first_delivery(turnaround_minutes=30)
    order_b = _second_order(account["id"], product["id"])
    # start at 11:29 < 11:30 buffer end -> intersects -> conflict.
    resp = api.create_delivery(
        order_b["id"],
        F.create_delivery_payload(vehicle["id"], "2026-04-02T11:29:00Z", "2026-04-02T12:00:00Z"),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT.value)


# ---------------------------------------------------------------------------
# Difficulty: vehicle_buffered_window_overlap
# ---------------------------------------------------------------------------
def test_window_intersecting_buffer_rejected(api):
    """PRD §3.8: "Each delivery occupies a busy interval that runs from its
    `window_start` up to but not including its `window_end` plus the vehicle's
    `turnaround_minutes`; two deliveries collide when their busy intervals intersect,
    and a collision is rejected with `ERR_VEHICLE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffered_window_overlap
    """
    nursery, account, product, vehicle = _vehicle_with_first_delivery(turnaround_minutes=30)
    order_b = _second_order(account["id"], product["id"])
    # [11:15, 12:00) intersects the [10:00, 11:30) buffered busy interval.
    resp = api.create_delivery(
        order_b["id"],
        F.create_delivery_payload(vehicle["id"], "2026-04-02T11:15:00Z", "2026-04-02T12:00:00Z"),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_WINDOW_CONFLICT.value)


def test_non_overlapping_window_on_same_vehicle_allowed(api):
    """PRD §3.8: "the chosen vehicle's window must not collide with any other
    non-cancelled delivery already on that vehicle, accounting for the vehicle's
    turnaround buffer."

    Design: Difficulty/resource_temporal_overlap/vehicle_buffered_window_overlap
    """
    nursery, account, product, vehicle = _vehicle_with_first_delivery(turnaround_minutes=30)
    order_b = _second_order(account["id"], product["id"])
    # [13:00, 14:00) is well clear of the [10:00, 11:30) busy interval.
    resp = api.create_delivery(
        order_b["id"],
        F.create_delivery_payload(vehicle["id"], "2026-04-02T13:00:00Z", "2026-04-02T14:00:00Z"),
        INV,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Difficulty: order_fulfill_requires_delivery_delivered
# ---------------------------------------------------------------------------
def _allocated_paid_order_with_scheduled_delivery():
    """Order confirmed/paid/allocated with a SCHEDULED (undelivered) delivery.
    Returns (order_id, order_version, delivery)."""
    X.set_clock("2026-04-01T07:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    vehicle = X.create_vehicle(nursery["id"], label="T-2", vehicle_type="BOX_TRUCK",
                               capacity_cubic_yards=20, turnaround_minutes=0)
    product = X.create_product(nursery["id"], sku="DG-9", name="Cart", unit_price_cents=1500)
    X.create_released_lot(product["id"], received_qty=5, unit_cost_cents=500)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=2)
    c = X.confirm(order["id"], order["version"])
    a = X.allocate(order["id"], c["version"])
    p = X.pay(order["id"], a["version"])
    delivery = X.book_delivery(order["id"], vehicle["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z")
    return order["id"], p["version"], delivery


def test_fulfill_blocked_while_delivery_scheduled(api):
    """PRD §3.4: "if the order has an associated delivery, that delivery has reached
    `DELIVERED` status (otherwise `ERR_DELIVERY_NOT_COMPLETED`)".

    Design: Difficulty/cross_entity_state_dependency/order_fulfill_requires_delivery_delivered
    """
    order_id, version, _delivery = _allocated_paid_order_with_scheduled_delivery()
    resp = api.fulfill_order(order_id, F.version_payload(version), INV)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_COMPLETED.value)


def test_delivered_delivery_unblocks_fulfill(api):
    """PRD §3.8: "reaching `DELIVERED` is what unblocks the parent order's
    fulfillment."

    Design: Difficulty/cross_entity_state_dependency/order_fulfill_requires_delivery_delivered
    """
    order_id, version, delivery = _allocated_paid_order_with_scheduled_delivery()
    # Drive the single delivery to DELIVERED, then fulfill must succeed.
    validate_success(api.dispatch_delivery(delivery["id"], INV))
    validate_success(api.complete_delivery(delivery["id"], INV))
    fulfilled = validate_success(api.fulfill_order(order_id, F.version_payload(version), INV))
    assert fulfilled["fulfillment_status"] == "FULFILLED"


# ---------------------------------------------------------------------------
# Corner: vehicle capacity
# ---------------------------------------------------------------------------
def test_vehicle_capacity_exceeded_on_delivery(api):
    """PRD §3.8: "the order's total bulk volume across its `BULK_MATERIAL` lines
    must not exceed the chosen vehicle's `capacity_cubic_yards`; exceeding it is
    rejected with `ERR_VEHICLE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/vehicle_capacity_exceeded_on_delivery
    """
    X.set_clock("2026-04-01T07:00:00Z")
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    vehicle = X.create_vehicle(nursery["id"], label="Small", vehicle_type="BOX_TRUCK",
                               capacity_cubic_yards=5, turnaround_minutes=0)
    product = X.create_product(nursery["id"], sku="SOIL-2", name="Mulch",
                               category="BULK_MATERIAL", unit="CUBIC_YARD", unit_price_cents=3000)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=10)  # 10 cubic yards > capacity 5
    resp = api.create_delivery(
        order["id"],
        F.create_delivery_payload(vehicle["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_VEHICLE_CAPACITY_EXCEEDED.value)
