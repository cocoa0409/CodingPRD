"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch — each test runs against an empty
database with the logical clock at its 2026-07-01T00:00:00Z startup default.

Identity threading: the Customer role is entity-backed, so ownership-gated calls
(order create/line/place/cancel, return request, claim) always use
make_customer_headers(customer["id"]) — never the shared constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_product_payload,
    create_variant_payload,
    create_order_payload,
    create_order_line_payload,
    create_subscription_payload,
    create_shipment_payload,
    create_allocation_window_payload,
    create_claim_payload,
    create_return_payload,
)
from .test_users import TEST_USERS, make_customer_headers

MERCH = TEST_USERS["merchandiser_headers"]
FULFILL = TEST_USERS["fulfillment_headers"]
ADMIN = TEST_USERS["admin_headers"]

_email_seq = itertools.count(1)


def _unique_email() -> str:
    return f"customer{next(_email_seq)}@example.com"


# ─── Clock ────────────────────────────────────────────
def set_clock(iso: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


# ─── Tier 1: single-entity builders ───────────────────
def make_customer(**overrides) -> dict:
    overrides.setdefault("email", _unique_email())
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def suspend_customer(customer_id: str) -> dict:
    return get_success_data(api_client.suspend_customer(customer_id, ADMIN))


def make_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_payload(**overrides), MERCH))


def make_variant(product_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_variant(product_id, create_variant_payload(**overrides), MERCH))


def make_subscription(customer_id: str, **overrides) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_subscription(create_subscription_payload(customer_id, **overrides), headers)
    )


def make_allocation_window(product_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_allocation_window(product_id, create_allocation_window_payload(**overrides), MERCH)
    )


def make_shipment(subscription_id: str, period_start: str, period_end: str) -> dict:
    return get_success_data(
        api_client.create_shipment(subscription_id, create_shipment_payload(period_start, period_end), FULFILL)
    )


def fulfill_shipment(shipment_id: str) -> dict:
    return get_success_data(api_client.fulfill_shipment(shipment_id, FULFILL))


# ─── Tier 1: order lifecycle primitives ───────────────
def make_order(customer_id: str) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.create_order(create_order_payload(customer_id), headers))


def add_line(order_id: str, customer_id: str, variant_id: str, quantity: int = 1) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_order_line(order_id, create_order_line_payload(variant_id, quantity), headers)
    )


def place_order(order_id: str, customer_id: str, redeem_points: int = 0) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.place_order(order_id, {"redeem_points": redeem_points}, headers))


def fulfill_order(order_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, FULFILL))


def cancel_order(order_id: str, customer_id: str) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(api_client.cancel_order(order_id, headers))


def request_return(order_id: str, customer_id: str, line_ids: list, condition: str) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_return(create_return_payload(order_id, line_ids, condition), headers)
    )


def approve_return(return_id: str) -> dict:
    return get_success_data(api_client.approve_return(return_id, FULFILL))


# ─── Tier 1: allocation primitives ────────────────────
def get_window(window_id: str) -> dict:
    return get_success_data(api_client.get_allocation_window(window_id, ADMIN))


def claim_allocation(window_id: str, customer_id: str, units: int, expected_window_version: int) -> dict:
    headers = make_customer_headers(customer_id)
    return get_success_data(
        api_client.create_claim(
            window_id, create_claim_payload(customer_id, units, expected_window_version), headers
        )
    )


# ─── Tier 2/3: composite lifecycle shortcuts ──────────
def setup_cart_order(unit_price_cents: int, quantity: int = 1, on_hand_qty: int = 5,
                     hygiene_returnable: bool = False, concentration: str = "EDP",
                     variant_kind: str = "FULL_BOTTLE") -> dict:
    """Active customer + product + one variant + a CART order carrying one line.

    Returns dict with cust_id, cust_headers, prod_id, var_id, order_id, line_id.
    """
    cust = make_customer()
    prod = make_product(concentration=concentration, hygiene_returnable=hygiene_returnable)
    var = make_variant(prod["id"], kind=variant_kind, unit_price_cents=unit_price_cents, on_hand_qty=on_hand_qty)
    order = make_order(cust["id"])
    line = add_line(order["id"], cust["id"], var["id"], quantity)
    return {
        "cust_id": cust["id"],
        "cust_headers": make_customer_headers(cust["id"]),
        "prod_id": prod["id"],
        "var_id": var["id"],
        "order_id": order["id"],
        "line_id": line["id"],
    }


def setup_placed_order(unit_price_cents: int, quantity: int = 1, on_hand_qty: int = 5,
                       redeem_points: int = 0, hygiene_returnable: bool = False,
                       concentration: str = "EDP", variant_kind: str = "FULL_BOTTLE") -> dict:
    """A CART order placed (fulfillment PLACED, payment PAID)."""
    ctx = setup_cart_order(unit_price_cents, quantity, on_hand_qty, hygiene_returnable,
                           concentration, variant_kind)
    place_order(ctx["order_id"], ctx["cust_id"], redeem_points)
    return ctx


def setup_fulfilled_order(unit_price_cents: int, quantity: int = 1, on_hand_qty: int = 5,
                          redeem_points: int = 0, hygiene_returnable: bool = False,
                          concentration: str = "EDP", variant_kind: str = "FULL_BOTTLE") -> dict:
    """A single-line order walked through to FULFILLED (loyalty earned, tier recomputed)."""
    ctx = setup_placed_order(unit_price_cents, quantity, on_hand_qty, redeem_points,
                             hygiene_returnable, concentration, variant_kind)
    fulfill_order(ctx["order_id"])
    return ctx


def setup_return_requested(unit_price_cents: int = 10000, condition: str = "SEALED",
                           hygiene_returnable: bool = True) -> dict:
    """A fulfilled single-line order with a REQUESTED return over that line.

    Returns the setup_fulfilled_order dict plus return_id.
    """
    ctx = setup_fulfilled_order(unit_price_cents, hygiene_returnable=hygiene_returnable)
    ret = request_return(ctx["order_id"], ctx["cust_id"], [ctx["line_id"]], condition)
    ctx["return_id"] = ret["id"]
    return ctx


def setup_open_exclusive_window(total_allocation: int, per_customer_cap: int,
                                per_customer_limit=100,
                                window_start: str = "2026-06-15T00:00:00Z",
                                window_end: str = "2026-07-31T00:00:00Z",
                                is_exclusive: bool = True) -> dict:
    """Active customer + exclusive product + one OPEN window (OPEN at the default
    clock 2026-07-01). Returns cust_id, cust_headers, prod_id, win_id, win_version.
    """
    cust = make_customer()
    prod = make_product(concentration="PARFUM", is_exclusive=is_exclusive,
                        per_customer_limit=per_customer_limit)
    win = make_allocation_window(prod["id"], window_start=window_start, window_end=window_end,
                                 total_allocation=total_allocation, per_customer_cap=per_customer_cap)
    return {
        "cust_id": cust["id"],
        "cust_headers": make_customer_headers(cust["id"]),
        "prod_id": prod["id"],
        "win_id": win["id"],
        "win_version": win["version"],
    }
