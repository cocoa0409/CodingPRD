"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

Identity threading: after an entity_backed resource is created, ownership-gated
calls use make_<role>_headers(entity_id) — never the shared fallback constant.
The server DB is empty at the start of every test, so each helper builds its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_product_payload, create_inventory_lot_payload, create_customer_payload,
    create_commercial_account_payload, create_retail_order_payload,
    create_commercial_order_payload, create_subscription_payload,
    create_consultant_payload, create_booking_payload, create_room_payload,
    create_workshop_session_payload, create_registration_payload, create_rma_payload,
    order_line,
)
from .test_users import (
    TEST_USERS, make_customer_headers, make_commercial_buyer_headers,
    make_consultant_headers,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Products & inventory ─────────────────────────────────────────────────
def new_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), ADMIN)
    )


def receive_lot(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_lot(
            product_id, create_inventory_lot_payload(**overrides), ADMIN
        )
    )


def new_stocked_product(quantity: int = 100, lot_code: str = "L-001", **product_overrides):
    """Create a product plus one ACTIVE lot. Returns (product, lot)."""
    product = new_product(**product_overrides)
    lot = receive_lot(product["id"], lot_code=lot_code, quantity_on_hand=quantity)
    return product, lot


# ─── Customers ────────────────────────────────────────────────────────────
def new_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), ADMIN)
    )


# ─── Commercial accounts ──────────────────────────────────────────────────
def new_commercial_account(**overrides) -> dict:
    """Create a PENDING commercial account."""
    return get_success_data(
        api_client.create_commercial_account(
            create_commercial_account_payload(**overrides), ADMIN
        )
    )


def activate_account(account_id: str) -> dict:
    return get_success_data(api_client.activate_commercial_account(account_id, ADMIN))


def hold_account(account_id: str) -> dict:
    return get_success_data(api_client.hold_commercial_account(account_id, ADMIN))


def set_account_tier(account_id: str, discount_tier: str) -> dict:
    return get_success_data(
        api_client.set_commercial_account_tier(
            account_id, {"discount_tier": discount_tier}, ADMIN
        )
    )


def new_active_account(**overrides) -> dict:
    """Create + activate a commercial account. Returned dict's version reflects
    the activation bump."""
    account = new_commercial_account(**overrides)
    return activate_account(account["id"])


def get_account(account_id: str) -> dict:
    return get_success_data(api_client.get_commercial_account(account_id, ADMIN))


def place_commercial_order(account: dict, lines: list, version: int = None) -> dict:
    """Place a commercial order on `account`. Defaults expected version to the
    account's current version. Returns the created order."""
    if version is None:
        version = account["version"]
    buyer = make_commercial_buyer_headers(account["id"])
    payload = create_commercial_order_payload(lines, version)
    return get_success_data(
        api_client.create_commercial_order(account["id"], payload, buyer)
    )


# ─── Retail orders ────────────────────────────────────────────────────────
def new_retail_order(customer_id: str, lines: list) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_order(create_retail_order_payload(customer_id, lines), headers)
    )


def confirm_order(order_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.confirm_order(order_id, make_customer_headers(customer_id))
    )


def pay_order(order_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.pay_order(order_id, make_customer_headers(customer_id))
    )


def ship_order(order_id: str) -> dict:
    return get_success_data(api_client.ship_order(order_id, ADMIN))


def cancel_order(order_id: str, customer_id: str = None) -> dict:
    headers = make_customer_headers(customer_id) if customer_id else ADMIN
    return get_success_data(api_client.cancel_order(order_id, headers))


def refund_order(order_id: str) -> dict:
    return get_success_data(api_client.refund_order(order_id, ADMIN))


def setup_shipped_retail_order(quantity: int = 1, stock: int = 50, **product_overrides):
    """Customer + stocked product + a retail order confirmed and shipped.
    Returns (customer, product, order). Order.shipped_at is stamped at the
    current logical clock."""
    customer = new_customer()
    product, _lot = new_stocked_product(quantity=stock, **product_overrides)
    order = new_retail_order(customer["id"], [order_line(product["id"], quantity)])
    confirm_order(order["id"], customer["id"])
    order = ship_order(order["id"])
    return customer, product, order


# ─── Subscriptions ────────────────────────────────────────────────────────
def new_subscription(customer_id: str, product_id: str, **overrides) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_subscription(
            create_subscription_payload(customer_id, product_id, **overrides), headers
        )
    )


def new_active_subscription(**product_overrides):
    """Customer + subscribable product + ACTIVE subscription.
    Returns (customer, product, subscription)."""
    customer = new_customer()
    product = new_product(is_subscribable=True, category="CONSUMABLE", **product_overrides)
    sub = new_subscription(customer["id"], product["id"])
    return customer, product, sub


# ─── Consultants & bookings ───────────────────────────────────────────────
def new_consultant(**overrides) -> dict:
    return get_success_data(
        api_client.create_consultant(create_consultant_payload(**overrides), ADMIN)
    )


def book_consult(consultant_id: str, customer_id: str, start_at: str, end_at: str,
                 **overrides) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_booking(
            consultant_id,
            create_booking_payload(customer_id, start_at, end_at, **overrides),
            headers,
        )
    )


def confirm_booking(booking_id: str, consultant_id: str) -> dict:
    return get_success_data(
        api_client.confirm_booking(booking_id, make_consultant_headers(consultant_id))
    )


def complete_booking(booking_id: str, consultant_id: str, actual_minutes: int) -> dict:
    return get_success_data(
        api_client.complete_booking(
            booking_id, {"actual_minutes": actual_minutes},
            make_consultant_headers(consultant_id),
        )
    )


# ─── Rooms & workshops ────────────────────────────────────────────────────
def new_room(**overrides) -> dict:
    return get_success_data(api_client.create_room(create_room_payload(**overrides), ADMIN))


def new_session(room_id: str, start_at: str, end_at: str, capacity: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_workshop_session(
            create_workshop_session_payload(room_id, start_at, end_at, capacity, **overrides),
            ADMIN,
        )
    )


def open_session(session_id: str) -> dict:
    return get_success_data(api_client.open_workshop_session(session_id, ADMIN))


def new_open_session(capacity: int, seat_capacity: int = 20,
                     start_at: str = "2026-07-10T18:00:00Z",
                     end_at: str = "2026-07-10T20:00:00Z"):
    """Room + workshop session moved to OPEN. Returns (room, session)."""
    room = new_room(seat_capacity=seat_capacity)
    session = new_session(room["id"], start_at, end_at, capacity)
    session = open_session(session["id"])
    return room, session


def cancel_workshop_session(session_id: str) -> dict:
    return get_success_data(api_client.cancel_workshop_session(session_id, ADMIN))


def register(session_id: str, customer_id: str) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_registration(
            session_id, create_registration_payload(customer_id), headers
        )
    )


# ─── RMA ──────────────────────────────────────────────────────────────────
def submit_rma(order_id: str, product_id: str, return_quantity: int, customer_id: str,
               reason: str = "defective") -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_rma(
            create_rma_payload(order_id, product_id, return_quantity, reason), headers
        )
    )


def review_rma(rma_id: str) -> dict:
    return get_success_data(api_client.review_rma(rma_id, ADMIN))


def request_info_rma(rma_id: str, note: str = "need serial") -> dict:
    return get_success_data(api_client.request_info_rma(rma_id, {"note": note}, ADMIN))


def provide_info_rma(rma_id: str, customer_id: str, note: str = "serial 123") -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.provide_info_rma(rma_id, {"note": note}, headers))


def approve_rma(rma_id: str) -> dict:
    return get_success_data(api_client.approve_rma(rma_id, ADMIN))


def setup_rma_under_review(quantity: int = 1, stock: int = 50, return_quantity: int = 1,
                           **product_overrides):
    """Customer + stocked product + shipped retail order + RMA submitted and moved
    to UNDER_REVIEW. Returns (customer, product, order, rma)."""
    customer, product, order = setup_shipped_retail_order(
        quantity=quantity, stock=stock, **product_overrides
    )
    rma = submit_rma(order["id"], product["id"], return_quantity, customer["id"])
    rma = review_rma(rma["id"])
    return customer, product, order, rma
