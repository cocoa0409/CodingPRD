"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors, not confusing assertion failures. Every helper builds its
preconditions from scratch — the server restarts with an empty DB before each test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_product_payload, create_by_unit_product_payload,
    create_cave_payload, create_lot_payload, create_order_payload,
    create_product_line_payload, create_board_payload, create_subscription_payload,
    create_prep_station_payload, create_tasting_room_payload, create_tasting_event_payload,
)
from .test_users import TEST_USERS, make_wholesale_customer_headers

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Set the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(iso, SM))


# ─── Tier 1: single-entity creation ───────────────────────────────────────
def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SM))


def create_wholesale_customer(**overrides) -> dict:
    overrides.setdefault("account_type", "WHOLESALE_RESTAURANT")
    overrides.setdefault("name", "Test Bistro")
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SM))


def create_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_payload(**overrides), SM))


def create_by_unit_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_by_unit_product_payload(**overrides), SM))


def create_cave(**overrides) -> dict:
    return get_success_data(api_client.create_cave(create_cave_payload(**overrides), SM))


def create_prep_station(**overrides) -> dict:
    return get_success_data(api_client.create_prep_station(create_prep_station_payload(**overrides), SM))


def create_tasting_room(**overrides) -> dict:
    return get_success_data(api_client.create_tasting_room(create_tasting_room_payload(**overrides), SM))


def create_board(components: list, **overrides) -> dict:
    return get_success_data(api_client.create_board(create_board_payload(components, **overrides), SM))


# ─── Tier 2: lot lifecycle helpers ─────────────────────────────────────────
def receive_lot(product_id: str, cave_id: str, received_weight_g: int = 1000) -> dict:
    """Receive a lot into a cave (status AGING)."""
    return get_success_data(api_client.receive_lot(
        create_lot_payload(product_id, cave_id, received_weight_g), SM))


def create_ready_lot(product_id: str, cave_id: str, received_weight_g: int = 1000) -> dict:
    """Receive a lot then run a rotation so it becomes READY. Intended for products
    with min_aging_days 0 and shrink 0. Returns the READY lot (fresh GET)."""
    lot = receive_lot(product_id, cave_id, received_weight_g)
    api_client.rotate_cave(cave_id, SM)
    return get_success_data(api_client.get_lot(lot["id"], SM))


def get_lot(lot_id: str, headers=CS) -> dict:
    return get_success_data(api_client.get_lot(lot_id, headers))


def allocate_line(line_id: str, lot_id: str, headers=CS):
    """Allocate a line to a lot, echoing the lot's current version (PRD §2.7).
    Returns the raw response so callers can assert on it if needed."""
    lot = get_success_data(api_client.get_lot(lot_id, headers))
    return api_client.allocate_order_line(
        line_id, {"lot_id": lot_id, "expected_lot_version": lot["version"]}, headers)


# ─── Tier 3: order build helpers ───────────────────────────────────────────
def create_order(customer_id: str, order_type: str = "RETAIL", headers=CS, **overrides) -> dict:
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, order_type, **overrides), headers))


def add_weight_line(order_id: str, product_id: str, requested_weight_g: int, headers=CS) -> dict:
    return get_success_data(api_client.add_order_line(
        order_id, create_product_line_payload(product_id, requested_weight_g=requested_weight_g), headers))


def add_unit_line(order_id: str, product_id: str, requested_qty: int, headers=CS) -> dict:
    return get_success_data(api_client.add_order_line(
        order_id, create_product_line_payload(product_id, requested_qty=requested_qty), headers))


def setup_allocated_retail_order(price_per_kg_cents: int = 3000, requested_weight_g: int = 500,
                                 received_weight_g: int = 1000, store_credit_cents: int = 0):
    """RETAIL customer + pasteurized BY_WEIGHT product (min_aging 0, shrink 0) + READY lot,
    DRAFT order with one allocated by-weight line. Returns a scenario dict."""
    customer = create_customer(store_credit_cents=store_credit_cents)
    product = create_product(price_per_kg_cents=price_per_kg_cents)
    cave = create_cave()
    lot = create_ready_lot(product["id"], cave["id"], received_weight_g)
    order = create_order(customer["id"], "RETAIL")
    line = add_weight_line(order["id"], product["id"], requested_weight_g)
    allocate_line(line["id"], lot["id"])
    return {"customer": customer, "product": product, "cave": cave,
            "lot": lot, "order": order, "line": line}


def setup_submitted_retail_order(**kwargs):
    """setup_allocated_retail_order then submit (DRAFT -> SUBMITTED)."""
    sc = setup_allocated_retail_order(**kwargs)
    api_client.submit_order(sc["order"]["id"], CS)
    sc["order"] = get_success_data(api_client.get_order(sc["order"]["id"], CS))
    return sc


def setup_paid_retail_order(payment_method: str = "EXTERNAL", **kwargs):
    """setup_submitted_retail_order then pay (UNPAID -> PAID)."""
    sc = setup_submitted_retail_order(**kwargs)
    api_client.pay_order(sc["order"]["id"], {"payment_method": payment_method}, CS)
    sc["order"] = get_success_data(api_client.get_order(sc["order"]["id"], CS))
    return sc


def setup_fulfilled_retail_order(actual_cut_weight_g: int, payment_method: str = "EXTERNAL", **kwargs):
    """setup_paid_retail_order then fulfill (SUBMITTED -> FULFILLED) with the given actual cut."""
    sc = setup_paid_retail_order(payment_method=payment_method, **kwargs)
    api_client.fulfill_order(
        sc["order"]["id"],
        {"line_actuals": [{"line_id": sc["line"]["id"], "actual_cut_weight_g": actual_cut_weight_g}]},
        CS)
    sc["order"] = get_success_data(api_client.get_order(sc["order"]["id"], CS))
    return sc


def setup_allocated_wholesale_order(price_per_kg_cents: int, requested_weight_g: int,
                                    received_weight_g: int):
    """WHOLESALE customer + BY_WEIGHT product + READY lot; order created by the wholesale
    owner, one line added and allocated by CounterStaff. Returns a scenario dict."""
    customer = create_wholesale_customer()
    wc = make_wholesale_customer_headers(customer["id"])
    product = create_product(price_per_kg_cents=price_per_kg_cents, form="BLOCK")
    cave = create_cave()
    lot = create_ready_lot(product["id"], cave["id"], received_weight_g)
    order = create_order(customer["id"], "WHOLESALE", headers=wc)
    line = add_weight_line(order["id"], product["id"], requested_weight_g)
    allocate_line(line["id"], lot["id"])
    return {"customer": customer, "wc_headers": wc, "product": product,
            "cave": cave, "lot": lot, "order": order, "line": line}


# ─── Tier 4: subscription helpers ──────────────────────────────────────────
def setup_active_subscription(tier: str = "CLASSIC", monthly_price_cents: int = 5000):
    """WHOLESALE customer + board + ACTIVE subscription owned by that customer."""
    customer = create_wholesale_customer(region_code="NY")
    wc = make_wholesale_customer_headers(customer["id"])
    product = create_product()
    board = create_board([{"product_id": product["id"], "portion_g": 100}])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(customer["id"], board["id"],
                                    tier=tier, monthly_price_cents=monthly_price_cents), wc))
    return {"customer": customer, "wc_headers": wc, "board": board, "subscription": sub}


# ─── Tier 5: tasting helpers ───────────────────────────────────────────────
def setup_scheduled_tasting_event(seats: int = 5, buffer_minutes: int = 30, seat_capacity: int = 20,
                                  start_at: str = "2026-07-05T10:00:00Z",
                                  end_at: str = "2026-07-05T11:00:00Z"):
    """ACTIVE customer + tasting room + one SCHEDULED event. Returns a scenario dict."""
    customer = create_customer()
    room = create_tasting_room(seat_capacity=seat_capacity, buffer_minutes=buffer_minutes)
    event = get_success_data(api_client.create_tasting_event(
        create_tasting_event_payload(room["id"], customer["id"], start_at, end_at, seats), CS))
    return {"customer": customer, "room": room, "event": event}
