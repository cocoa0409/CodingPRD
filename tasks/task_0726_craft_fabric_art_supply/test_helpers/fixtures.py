"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before each test. Setup calls
use get_success_data() (lenient) so setup failures surface clearly.

Identity threading: after creating a Customer, ownership-gated Customer calls
use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)
from . import factories as f

MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(instant: str):
    """Set the logical clock to an ISO8601 instant (StoreManager-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": instant}, MANAGER))


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_customer(**overrides):
    """Register a customer (auto-creates its loyalty account). Returns Customer dict."""
    return get_success_data(
        api_client.create_customer(f.create_customer_payload(**overrides), ASSOCIATE)
    )


def create_product(**overrides):
    """Create a product SKU. Returns Product dict."""
    return get_success_data(
        api_client.create_product(f.create_product_payload(**overrides), MANAGER)
    )


def create_inventory_lot(product_id, on_hand_yards=100):
    """Create an inventory lot for a product. Returns InventoryLot dict."""
    return get_success_data(
        api_client.create_inventory_lot(
            product_id, f.create_inventory_lot_payload(on_hand_yards=on_hand_yards), MANAGER
        )
    )


def create_product_with_lot(on_hand_yards=100, **product_overrides):
    """Create a product plus a stocked inventory lot. Returns (product, lot)."""
    product = create_product(**product_overrides)
    lot = create_inventory_lot(product["id"], on_hand_yards=on_hand_yards)
    return product, lot


def create_coupon(**overrides):
    """Create a coupon. Returns Coupon dict."""
    return get_success_data(
        api_client.create_coupon(f.create_coupon_payload(**overrides), MANAGER)
    )


def create_order(customer_id, **overrides):
    """Create a BUILDING order for a customer. Returns Order dict."""
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_order(f.create_order_payload(customer_id, **overrides), headers)
    )


def add_line(order_id, customer_id, product_id, requested_yards, **overrides):
    """Add an order line as the owning customer. Returns OrderLine dict."""
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.add_order_line(
            order_id,
            f.create_order_line_payload(product_id, requested_yards, **overrides),
            headers,
        )
    )


def create_room(**overrides):
    """Create a classroom. Returns Room dict."""
    return get_success_data(api_client.create_room(f.create_room_payload(**overrides), MANAGER))


def create_workshop(**overrides):
    """Create a DRAFT workshop. Returns Workshop dict."""
    return get_success_data(
        api_client.create_workshop(f.create_workshop_payload(**overrides), MANAGER)
    )


def create_session(workshop_id, room_id, starts_at, ends_at, capacity, **overrides):
    """Create a workshop session. Returns WorkshopSession dict."""
    return get_success_data(
        api_client.create_session(
            workshop_id,
            f.create_session_payload(room_id, starts_at, ends_at, capacity, **overrides),
            MANAGER,
        )
    )


# --------------------------------------------------------------------------
# Order lifecycle progression
# --------------------------------------------------------------------------
def create_order_with_line(customer_id, product_id, requested_yards, **line_overrides):
    """Create a BUILDING order with a single line. Returns (order, line)."""
    order = create_order(customer_id)
    line = add_line(order["id"], customer_id, product_id, requested_yards, **line_overrides)
    return order, line


def submit_order(order_id, customer_id):
    """Submit an order as the owning customer. Returns Order dict."""
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.submit_order(order_id, headers))


def pay_order(order_id, customer_id, points_redeemed_on_order=None):
    """Pay an order as the owning customer. Returns Order dict."""
    headers = make_customer_headers(customer_id)
    payload = {}
    if points_redeemed_on_order is not None:
        payload["points_redeemed_on_order"] = points_redeemed_on_order
    return get_success_data(api_client.pay_order(order_id, payload, headers))


def record_cut(line_id, actual_cut_yards):
    """Record actual_cut_yards on a by-the-yard line (StoreAssociate). Returns OrderLine."""
    return get_success_data(
        api_client.record_cut(line_id, {"actual_cut_yards": actual_cut_yards}, ASSOCIATE)
    )


def ready_order(order_id):
    """Mark an order ready for pickup (StoreAssociate). Returns Order dict."""
    return get_success_data(api_client.ready_order(order_id, ASSOCIATE))


def pickup_order(order_id):
    """Complete pickup (StoreAssociate). Returns Order dict."""
    return get_success_data(api_client.pickup_order(order_id, ASSOCIATE))


def setup_submitted_order(customer_id, product_id, requested_yards):
    """Create order + line, then submit. Returns (order_after_submit, line)."""
    order, line = create_order_with_line(customer_id, product_id, requested_yards)
    submitted = submit_order(order["id"], customer_id)
    return submitted, line


def complete_picked_up_order(customer_id, product_id, requested_yards,
                             actual_cut_yards=None, points_redeemed_on_order=None):
    """Drive an order all the way through PICKED_UP.

    create -> add line -> submit -> pay -> [record cut] -> ready -> pickup.
    If actual_cut_yards is given, records the cut before ready (needed for BY_YARD).
    Returns (order_after_pickup, line).
    """
    order, line = create_order_with_line(customer_id, product_id, requested_yards)
    submit_order(order["id"], customer_id)
    pay_order(order["id"], customer_id, points_redeemed_on_order=points_redeemed_on_order)
    if actual_cut_yards is not None:
        record_cut(line["id"], actual_cut_yards)
    ready_order(order["id"])
    picked = pickup_order(order["id"])
    return picked, line


# --------------------------------------------------------------------------
# Loyalty accumulation
# --------------------------------------------------------------------------
def get_loyalty_account(customer_id):
    """Reverse-lookup the customer's loyalty account. Returns the first account dict."""
    headers = make_customer_headers(customer_id)
    data = get_success_data(api_client.get_loyalty_account(customer_id, headers))
    # Endpoint returns an array; return the single companion account.
    if isinstance(data, list):
        return data[0]
    return data


def setup_customer_with_picked_up_spend(unit_price_cents, clock_instant=None):
    """Create a customer and drive one UNIT order through PICKED_UP so the
    customer has spend_ytd_cents == final_total_cents == unit_price_cents (qty 1).
    Returns the customer dict.
    """
    if clock_instant is not None:
        set_clock(clock_instant)
    customer = create_customer()
    product, _ = create_product_with_lot(
        on_hand_yards=10, sell_mode="UNIT", unit_price_cents=unit_price_cents
    )
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    return customer


# --------------------------------------------------------------------------
# Workshop lifecycle
# --------------------------------------------------------------------------
def setup_open_workshop_with_session(starts_at, ends_at, capacity=1,
                                     cleanup_buffer_min=None, kit_product_id=None,
                                     room_id=None):
    """Create room + workshop + one session, then open the workshop.

    Returns (workshop, session, room).
    """
    if room_id is None:
        room_overrides = {}
        if cleanup_buffer_min is not None:
            room_overrides["cleanup_buffer_min"] = cleanup_buffer_min
        room = create_room(**room_overrides)
        room_id = room["id"]
    else:
        room = None
    ws_overrides = {}
    if kit_product_id is not None:
        ws_overrides["kit_product_id"] = kit_product_id
    workshop = create_workshop(**ws_overrides)
    session = create_session(workshop["id"], room_id, starts_at, ends_at, capacity)
    get_success_data(api_client.open_workshop(workshop["id"], MANAGER))
    return workshop, session, room


def register_customer(workshop_id, session_id, customer_id, order_id=None):
    """Register a customer to a session as the owning customer. Returns WorkshopRegistration."""
    headers = make_customer_headers(customer_id)
    payload = f.register_payload(session_id, customer_id)
    if order_id is not None:
        payload["order_id"] = order_id
    return get_success_data(api_client.register_workshop(workshop_id, payload, headers))


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------
def create_framing_order(order_id, customer_id, width_in, height_in):
    """Create a framing order as the owning customer. Returns FramingOrder dict."""
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_framing_order(
            f.create_framing_order_payload(order_id, customer_id, width_in, height_in),
            headers,
        )
    )


# --------------------------------------------------------------------------
# Special orders
# --------------------------------------------------------------------------
def create_special_order(customer_id, product_id, quantity):
    """Request a special order as the owning customer. Returns SpecialOrder dict."""
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_special_order(
            f.create_special_order_payload(customer_id, product_id, quantity), headers
        )
    )
