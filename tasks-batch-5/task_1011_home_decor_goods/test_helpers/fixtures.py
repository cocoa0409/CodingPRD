"""Composite setup helpers for multi-step test prerequisites.

Every helper uses get_success_data() (lenient validator) so setup failures
produce clear "Setup step failed" errors instead of confusing assertion
failures. The test harness restarts the server (empty DB, clock reset to
2026-07-01T00:00:00Z) before every test, so each helper builds its state
entirely from PRD-declared endpoints.

Customer is entity-backed by a LoyaltyMember: registry helpers thread the
acting member's id through make_customer_headers(member_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_store_payload,
    create_product_payload,
    create_store_inventory_payload,
    adjust_inventory_payload,
    create_loyalty_member_payload,
    create_order_payload,
    create_order_line_payload,
    create_assembly_crew_payload,
    create_delivery_booking_payload,
    create_return_payload,
    create_registry_payload,
    create_registry_item_payload,
    create_special_order_payload,
    quote_special_order_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["admin_headers"]
MERCH = TEST_USERS["merch_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
DELIVERY = TEST_USERS["delivery_headers"]


# ─── Logical clock ────────────────────────────────────
def set_clock(iso: str):
    """Set the logical clock (Admin)."""
    get_success_data(api_client.set_clock(iso, ADMIN))


# ─── Primitive creators (assert 2xx, return the resource) ───
def new_store(**overrides):
    return get_success_data(api_client.create_store(create_store_payload(**overrides), ADMIN))


def new_product(**overrides):
    return get_success_data(api_client.create_product(create_product_payload(**overrides), MERCH))


def new_inventory(store_id, product_id, allocated_qty=10):
    return get_success_data(api_client.create_store_inventory(
        create_store_inventory_payload(store_id, product_id, allocated_qty), MERCH))


def adjust_inventory(inv_id, delta_qty):
    return get_success_data(api_client.adjust_store_inventory(
        inv_id, adjust_inventory_payload(delta_qty), MERCH))


def new_member(email="member@x.com", **overrides):
    return get_success_data(api_client.create_loyalty_member(
        create_loyalty_member_payload(email=email, **overrides), ASSOCIATE))


def new_order(store_id, order_type="CARRYOUT", member_id=None, requested_redeem_points=None):
    kwargs = {}
    if member_id is not None:
        kwargs["member_id"] = member_id
    if requested_redeem_points is not None:
        kwargs["requested_redeem_points"] = requested_redeem_points
    return get_success_data(api_client.create_order(
        create_order_payload(store_id, order_type, **kwargs), ASSOCIATE))


def add_line(order_id, product_id, qty=1):
    return get_success_data(api_client.add_order_line(
        order_id, create_order_line_payload(product_id, qty), ASSOCIATE))


def capture(order_id):
    return get_success_data(api_client.capture_order(order_id, ASSOCIATE))


def ready(order_id):
    return get_success_data(api_client.ready_order(order_id, ASSOCIATE))


def fulfill(order_id):
    return get_success_data(api_client.fulfill_order(order_id, ASSOCIATE))


def cancel_order(order_id):
    return get_success_data(api_client.cancel_order(order_id, ASSOCIATE))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, ASSOCIATE))


def get_inventory(inv_id):
    return get_success_data(api_client.get_store_inventory(inv_id, MERCH))


def get_member(member_id):
    return get_success_data(api_client.get_loyalty_member(member_id, ASSOCIATE))


def get_line(line_id):
    return get_success_data(api_client.get_order_line(line_id, ASSOCIATE))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, MERCH))


# ─── Assembly crews & delivery bookings ───────────────
def new_crew(store_id, name="Crew Alpha"):
    return get_success_data(api_client.create_assembly_crew(
        create_assembly_crew_payload(store_id, name), ADMIN))


def new_booking(order_id, store_id, delivery_date, **overrides):
    return get_success_data(api_client.create_delivery_booking(
        create_delivery_booking_payload(order_id, store_id, delivery_date, **overrides), DELIVERY))


# ─── Registries (Customer, entity-backed) ─────────────
def new_registry(member_id, title="Housewarming", event_date="2026-12-01"):
    return get_success_data(api_client.create_registry(
        create_registry_payload(member_id, title, event_date), make_customer_headers(member_id)))


def new_registry_item(registry_id, member_id, product_id, desired_qty=1):
    return get_success_data(api_client.add_registry_item(
        registry_id, create_registry_item_payload(product_id, desired_qty),
        make_customer_headers(member_id)))


def close_registry(registry_id, member_id):
    return get_success_data(api_client.close_registry(registry_id, make_customer_headers(member_id)))


# ─── Special orders ───────────────────────────────────
def new_special_order(store_id, member_id, description="Custom item"):
    return get_success_data(api_client.create_special_order(
        create_special_order_payload(store_id, member_id, description), ASSOCIATE))


def quote(so_id, quoted_price_cents, expected_version):
    return get_success_data(api_client.quote_special_order(
        so_id, quote_special_order_payload(quoted_price_cents, expected_version), ASSOCIATE))


def submit_for_review(so_id):
    return get_success_data(api_client.submit_special_order_for_review(so_id, ASSOCIATE))


def request_changes(so_id):
    return get_success_data(api_client.request_special_order_changes(so_id, ASSOCIATE))


# ─── Composite: order with one reserved line ──────────
def setup_order_with_line(*, store_kwargs=None, product_kwargs=None, allocated_qty=10,
                          member_kwargs=None, order_type="CARRYOUT",
                          requested_redeem_points=None, qty=1):
    """Store + product + inventory + optional member + order + one reserved line.

    Returns dict: store, product, inventory, member (or None), order, line.
    """
    store = new_store(**(store_kwargs or {}))
    product = new_product(**(product_kwargs or {}))
    inventory = new_inventory(store["id"], product["id"], allocated_qty)
    member = new_member(**member_kwargs) if member_kwargs is not None else None
    mid = member["id"] if member else None
    order = new_order(store["id"], order_type, member_id=mid,
                      requested_redeem_points=requested_redeem_points)
    line = add_line(order["id"], product["id"], qty)
    return {"store": store, "product": product, "inventory": inventory,
            "member": member, "order": order, "line": line}


def setup_fulfilled_order(*, store_kwargs=None, product_kwargs=None, allocated_qty=10,
                          member_kwargs=None, order_type="CARRYOUT",
                          requested_redeem_points=None, qty=1):
    """setup_order_with_line then capture → ready → fulfill.

    Returns the same dict; order/line reflect post-fulfill reads are the
    caller's responsibility (re-read via get_order/get_line if needed).
    """
    ctx = setup_order_with_line(
        store_kwargs=store_kwargs, product_kwargs=product_kwargs,
        allocated_qty=allocated_qty, member_kwargs=member_kwargs,
        order_type=order_type, requested_redeem_points=requested_redeem_points, qty=qty)
    capture(ctx["order"]["id"])
    ready(ctx["order"]["id"])
    fulfill(ctx["order"]["id"])
    return ctx


# ─── Composite: special order walked to a target state ─
def setup_special_order_quoted(*, quoted_price_cents=50000):
    """Store + member + special order + one quote. Returns dict with so and versions."""
    store = new_store(name="SO Store")
    member = new_member(email="so@x.com", full_name="SO Member")
    so = new_special_order(store["id"], member["id"], "Custom sectional")
    quoted = quote(so["id"], quoted_price_cents, so["version"])
    return {"store": store, "member": member, "special_order": so,
            "quoted": quoted, "v_after_quote": quoted["version"]}


def setup_special_order_in_review(*, quoted_price_cents=50000):
    """Special order walked DRAFT → QUOTED → CUSTOMER_REVIEW."""
    ctx = setup_special_order_quoted(quoted_price_cents=quoted_price_cents)
    reviewed = submit_for_review(ctx["special_order"]["id"])
    ctx["reviewed"] = reviewed
    ctx["v_after_review"] = reviewed["version"]
    return ctx
