"""Composite setup helpers.

These encapsulate the multi-step preambles that nearly every interesting test
shares: register a customer, configure a warehouse + product + inventory, build a
cart, check out (reserving stock), capture payment, ship/deliver, and open/approve/
settle a return. Every helper builds its preconditions from scratch using only
PRD-declared endpoints, because the server database is empty before each test.

Identity threading: Customer is entity_backed, so every ownership-gated Customer
call uses make_customer_headers(customer["id"]) — never the shared constant.

All setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion deep in a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_store_admin_headers,
    make_warehouse_operator_headers,
    make_anonymous_headers,
)
from . import factories as f

ADMIN = TEST_USERS["store_admin_headers"]
OP = TEST_USERS["warehouse_operator_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(iso8601: str):
    """Set the logical UTC clock (StoreAdmin-driven)."""
    return get_success_data(api_client.set_clock(iso8601, ADMIN))


# ---------------------------------------------------------------------------
# Tier 0: primitive resource creators (return the resource dict)
# ---------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(f.create_customer_payload(**overrides), ANON))


def create_warehouse(**overrides) -> dict:
    return get_success_data(
        api_client.create_warehouse(f.create_warehouse_payload(**overrides), ADMIN))


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(f.create_product_payload(**overrides), ADMIN))


def stock_inventory(product_id, warehouse_id, on_hand_qty=10, **overrides) -> dict:
    return get_success_data(api_client.create_inventory(
        f.create_inventory_payload(product_id, warehouse_id, on_hand_qty, **overrides), ADMIN))


def create_cart(customer_id, **overrides) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_order(f.create_order_payload(customer_id, **overrides), headers))


def add_line(order_id, customer_id, product_id, qty=1) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.add_order_line(
        order_id, f.create_order_line_payload(product_id, qty), headers))


def get_order(order_id, customer_id=None) -> dict:
    headers = make_customer_headers(customer_id) if customer_id else ADMIN
    return get_success_data(api_client.get_order(order_id, headers))


def checkout(order_id, customer_id, expected_version=None) -> dict:
    headers = make_customer_headers(customer_id)
    if expected_version is None:
        expected_version = get_order(order_id, customer_id)["version"]
    return get_success_data(api_client.checkout_order(
        order_id, f.checkout_payload(expected_version), headers))


def capture(order_id) -> dict:
    return get_success_data(api_client.capture_payment(order_id, ADMIN))


def get_line_reservations(order_line_id, warehouse_id=None) -> list:
    params = {"warehouse_id": warehouse_id} if warehouse_id else None
    resp = api_client.list_order_line_reservations(order_line_id, ADMIN, params=params)
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)


# ---------------------------------------------------------------------------
# Tier 1: a single product fully stocked at one warehouse, owned by a customer
# ---------------------------------------------------------------------------
def setup_catalog(product_overrides=None, on_hand_qty=100, warehouse_overrides=None):
    """Customer + warehouse + product + inventory. Returns
    (customer, warehouse, product, inventory)."""
    customer = create_customer()
    warehouse = create_warehouse(**(warehouse_overrides or {}))
    product = create_product(**(product_overrides or {}))
    inventory = stock_inventory(product["id"], warehouse["id"], on_hand_qty)
    return customer, warehouse, product, inventory


# ---------------------------------------------------------------------------
# Tier 2: an order at a chosen lifecycle stage
# ---------------------------------------------------------------------------
def build_cart_with_line(customer_id, product_id, qty=1, promo_flat_cents=None):
    """CART order with one line. Returns (order, order_line)."""
    extra = {} if promo_flat_cents is None else {"promo_flat_cents": promo_flat_cents}
    order = create_cart(customer_id, **extra)
    line = add_line(order["id"], customer_id, product_id, qty)
    return order, line


def setup_authorized_order(product_overrides=None, qty=1, on_hand_qty=100,
                           promo_flat_cents=None):
    """Customer + stocked product + a checked-out (AUTHORIZED) order.
    Returns dict with customer, warehouse, product, inventory, order, line."""
    customer, warehouse, product, inventory = setup_catalog(
        product_overrides=product_overrides, on_hand_qty=on_hand_qty)
    order, line = build_cart_with_line(
        customer["id"], product["id"], qty, promo_flat_cents=promo_flat_cents)
    checkout(order["id"], customer["id"])
    return {
        "customer": customer, "warehouse": warehouse, "product": product,
        "inventory": inventory, "order": order, "line": line,
    }


def setup_captured_order(product_overrides=None, qty=1, on_hand_qty=100,
                         promo_flat_cents=None):
    """As setup_authorized_order, then capture payment (CAPTURED)."""
    ctx = setup_authorized_order(product_overrides=product_overrides, qty=qty,
                                 on_hand_qty=on_hand_qty,
                                 promo_flat_cents=promo_flat_cents)
    capture(ctx["order"]["id"])
    return ctx


def create_pending_shipment(order_id, warehouse_id, order_line_id, qty):
    """Create a PENDING shipment committing the single HELD reservation of the
    given line at the given warehouse. Returns (shipment, reservation_id)."""
    reservations = get_line_reservations(order_line_id, warehouse_id)
    res_id = reservations[0]["id"]
    shipment = get_success_data(api_client.create_shipment(
        order_id,
        f.create_shipment_payload(warehouse_id, [{"reservation_id": res_id, "qty": qty}]),
        OP))
    return shipment, res_id


def setup_shipped_order(product_overrides=None, qty=1, on_hand_qty=100,
                        promo_flat_cents=None):
    """Captured order with its single reservation shipped (SHIPPED, not delivered).
    Returns ctx with ...order/line plus shipment and reservation_id."""
    ctx = setup_captured_order(product_overrides=product_overrides, qty=qty,
                               on_hand_qty=on_hand_qty,
                               promo_flat_cents=promo_flat_cents)
    shipment, res_id = create_pending_shipment(
        ctx["order"]["id"], ctx["warehouse"]["id"], ctx["line"]["id"], qty)
    get_success_data(api_client.ship_shipment(shipment["id"], OP))
    ctx["shipment"] = shipment
    ctx["reservation_id"] = res_id
    return ctx


def setup_delivered_order(product_overrides=None, qty=1, on_hand_qty=100,
                          promo_flat_cents=None, delivered_clock=None):
    """Captured order shipped AND delivered. If delivered_clock is given, the clock
    is set to it just before delivery so delivered_at is anchored there.
    Returns ctx with ...shipment plus delivery completed."""
    ctx = setup_shipped_order(product_overrides=product_overrides, qty=qty,
                              on_hand_qty=on_hand_qty,
                              promo_flat_cents=promo_flat_cents)
    if delivered_clock is not None:
        set_clock(delivered_clock)
    get_success_data(api_client.deliver_shipment(ctx["shipment"]["id"], OP))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: a multi-line delivered order (for divergent-settlement money tests)
# ---------------------------------------------------------------------------
def setup_delivered_two_line_order(p1_overrides, p2_overrides, qty1, qty2,
                                   promo_flat_cents=0, on_hand_qty=100,
                                   delivered_clock=None):
    """Customer with a CAPTURED+DELIVERED two-line order. Ships and delivers BOTH
    lines (a single warehouse holds both, so two parcels are created and shipped).
    Returns dict: customer, warehouse, p1, p2, order, line1, line2, shipments."""
    customer = create_customer()
    warehouse = create_warehouse()
    p1 = create_product(**p1_overrides)
    p2 = create_product(**p2_overrides)
    stock_inventory(p1["id"], warehouse["id"], on_hand_qty)
    stock_inventory(p2["id"], warehouse["id"], on_hand_qty)

    order = create_cart(customer["id"], promo_flat_cents=promo_flat_cents)
    line1 = add_line(order["id"], customer["id"], p1["id"], qty1)
    line2 = add_line(order["id"], customer["id"], p2["id"], qty2)
    checkout(order["id"], customer["id"])
    capture(order["id"])

    shipments = []
    for line, qty in ((line1, qty1), (line2, qty2)):
        shipment, _ = create_pending_shipment(
            order["id"], warehouse["id"], line["id"], qty)
        get_success_data(api_client.ship_shipment(shipment["id"], OP))
        shipments.append(shipment)

    if delivered_clock is not None:
        set_clock(delivered_clock)
    for shipment in shipments:
        get_success_data(api_client.deliver_shipment(shipment["id"], OP))

    return {
        "customer": customer, "warehouse": warehouse, "p1": p1, "p2": p2,
        "order": order, "line1": line1, "line2": line2, "shipments": shipments,
    }


# ---------------------------------------------------------------------------
# Tier 4: return lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_return(order_id, customer_id, reason, resolution, lines):
    """Open an RMA (REQUESTED). `lines` is a list of return-line dicts."""
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.open_return(
        order_id, f.open_return_payload(reason, resolution, lines), headers))


def get_return(return_id) -> dict:
    return get_success_data(api_client.get_return(return_id, ADMIN))


def approve_return(return_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = get_return(return_id)["version"]
    return get_success_data(api_client.approve_return(
        return_id, f.approve_return_payload(expected_version), ADMIN))


def settle_return(return_id) -> dict:
    return get_success_data(api_client.settle_return(return_id, ADMIN))


def open_approve_return(order_id, customer_id, reason, resolution, lines):
    """Open + approve an RMA. Returns the APPROVED RMA dict."""
    rma = open_return(order_id, customer_id, reason, resolution, lines)
    return approve_return(rma["id"])


def open_approve_settle_return(order_id, customer_id, reason, resolution, lines):
    """Open + approve + settle an RMA. Returns the settled RMA dict."""
    rma = open_approve_return(order_id, customer_id, reason, resolution, lines)
    return settle_return(rma["id"])


def list_return_refunds(return_id) -> list:
    data = get_success_data(api_client.list_return_refunds(return_id, ADMIN))
    return data if isinstance(data, list) else data.get("data", data)


def list_refund_credit_entries(refund_id) -> list:
    data = get_success_data(api_client.list_refund_credit_entries(refund_id, ADMIN))
    return data if isinstance(data, list) else data.get("data", data)


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_inventory(inventory_id) -> dict:
    return get_success_data(api_client.get_inventory(inventory_id, ADMIN))


def get_order_line(order_line_id) -> dict:
    return get_success_data(api_client.get_order_line(order_line_id, ADMIN))


def get_reservation(reservation_id) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: split / backorder waterfall scenarios
# ---------------------------------------------------------------------------
def setup_two_warehouse_catalog(w1_on_hand, w2_on_hand,
                                w1_priority=1, w2_priority=2, product_overrides=None):
    """Customer + two warehouses (priorities) + one product stocked at both.
    Returns (customer, w1, w2, product)."""
    customer = create_customer()
    w1 = create_warehouse(fulfillment_priority=w1_priority)
    w2 = create_warehouse(fulfillment_priority=w2_priority)
    product = create_product(**(product_overrides or {}))
    stock_inventory(product["id"], w1["id"], w1_on_hand)
    stock_inventory(product["id"], w2["id"], w2_on_hand)
    return customer, w1, w2, product
