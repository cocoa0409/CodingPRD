"""Composite setup helpers for the Trophy, Awards & Engraving API.

These encapsulate the multi-step preambles that most test claims require so tests can
focus on assertions. All setup uses get_success_data() (lenient) so a broken precondition
produces a clear "Setup step failed" error instead of a confusing assertion failure.

Identity threading: the Customer role is entity_backed, so every ownership-gated call on
an order uses make_customer_headers(customer["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_staff_headers,
    make_manager_headers,
    make_anonymous_headers,
)
from . import factories as f
from .constants import CLOCK_MONDAY

STAFF = make_staff_headers()
MANAGER = make_manager_headers()
ANON = make_anonymous_headers()


# ─── Atomic building blocks ───────────────────────────
def set_clock(to_iso8601=CLOCK_MONDAY):
    return get_success_data(api_client.set_clock(to_iso8601, ANON))


def create_active_rush_policy(**overrides):
    payload = f.create_rush_policy_payload(**overrides)
    return get_success_data(api_client.create_rush_policy(payload, MANAGER))


def register_customer(**overrides):
    payload = f.create_customer_payload(**overrides)
    return get_success_data(api_client.create_customer(payload, ANON))


def create_component(**overrides):
    payload = f.create_component_payload(**overrides)
    return get_success_data(api_client.create_component(payload, MANAGER))


def create_product(component_id, **overrides):
    payload = f.create_catalog_product_payload(_component_id=component_id, **overrides)
    return get_success_data(api_client.create_catalog_product(payload, MANAGER))


def create_promo(**overrides):
    payload = f.create_promo_code_payload(**overrides)
    return get_success_data(api_client.create_promo_code(payload, MANAGER))


def create_order(customer, **overrides):
    payload = f.create_order_payload(customer["id"], **overrides)
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.create_order(payload, headers))


def add_line(order, customer, catalog_product_id, **overrides):
    payload = f.create_line_payload(catalog_product_id, **overrides)
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.add_line(order["id"], payload, headers))


def add_approved_proof(line, customer, content_ref="X", proof_kind="TEXT"):
    """Create a proof, send it, and approve it. Returns the approved proof."""
    cust_headers = make_customer_headers(customer["id"])
    proof = get_success_data(
        api_client.create_proof(
            line["id"], f.create_proof_payload(proof_kind=proof_kind, content_ref=content_ref), STAFF
        )
    )
    get_success_data(api_client.send_proof(line["id"], proof["id"], STAFF))
    get_success_data(api_client.approve_proof(line["id"], proof["id"], cust_headers))
    return proof


def add_sent_proof(line, content_ref="X", proof_kind="TEXT"):
    """Create a proof and send it (leaves it SENT, not approved). Returns the proof."""
    proof = get_success_data(
        api_client.create_proof(
            line["id"], f.create_proof_payload(proof_kind=proof_kind, content_ref=content_ref), STAFF
        )
    )
    get_success_data(api_client.send_proof(line["id"], proof["id"], STAFF))
    return proof


def price(order, customer):
    headers = make_customer_headers(customer["id"])  # noqa: F841 (price is staff-only)
    return get_success_data(api_client.price_order(order["id"], STAFF))


def confirm(order, customer, expected_version):
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.confirm_order(
            order["id"], {"expected_order_version": expected_version}, headers
        )
    )


def pay(order, customer, amount_cents, kind):
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.create_payment(
            order["id"], f.create_payment_payload(amount_cents, kind), headers
        )
    )


# ─── Foundational scenario: clock + policy + component + product + customer ───
def setup_foundation(product_overrides=None, on_hand_qty=100, reorder_point=0,
                     with_policy=True, with_clock=True):
    """Build the shop's reference data: clock, active rush policy, one component, one
    product backed by that component, and a registered customer.

    Returns dict with keys: component, product, customer.
    """
    if with_clock:
        set_clock()
    if with_policy:
        create_active_rush_policy()
    component = create_component(on_hand_qty=on_hand_qty, reorder_point=reorder_point)
    product = create_product(component["id"], **(product_overrides or {}))
    customer = register_customer()
    return {"component": component, "product": product, "customer": customer}


# ─── Tier 1/2: order with one approved line, ready to price ───
def setup_order_with_approved_line(order_overrides=None, line_overrides=None,
                                   product_overrides=None, on_hand_qty=100,
                                   content_ref="X"):
    """Active foundation + a DRAFT order + one line with an APPROVED proof (not yet priced).

    Returns dict: component, product, customer, order, line, proof.
    """
    base = setup_foundation(product_overrides=product_overrides, on_hand_qty=on_hand_qty)
    order = create_order(base["customer"], **(order_overrides or {}))
    line = add_line(order, base["customer"], base["product"]["id"], **(line_overrides or {}))
    proof = add_approved_proof(line, base["customer"], content_ref=content_ref)
    base.update({"order": order, "line": line, "proof": proof})
    return base


# ─── Tier 1: priced order (with approved line) ───
def setup_priced_order(order_overrides=None, line_overrides=None, product_overrides=None,
                       on_hand_qty=100, content_ref="X"):
    """An order priced to PRICED with one APPROVED line. Returns dict including the
    re-read PRICED order under key 'order' and its version under 'priced_version'."""
    ctx = setup_order_with_approved_line(
        order_overrides=order_overrides, line_overrides=line_overrides,
        product_overrides=product_overrides, on_hand_qty=on_hand_qty, content_ref=content_ref,
    )
    priced = price(ctx["order"], ctx["customer"])
    ctx["order"] = priced
    ctx["priced_version"] = priced["version"]
    return ctx


# ─── Tier 3: confirmed order ───
def setup_confirmed_order(order_overrides=None, line_overrides=None, product_overrides=None,
                          on_hand_qty=100, content_ref="X"):
    """An order confirmed to CONFIRMED (invoice locked, components reserved). Returns dict
    with the re-read CONFIRMED 'order'."""
    ctx = setup_priced_order(
        order_overrides=order_overrides, line_overrides=line_overrides,
        product_overrides=product_overrides, on_hand_qty=on_hand_qty, content_ref=content_ref,
    )
    confirmed = confirm(ctx["order"], ctx["customer"], ctx["priced_version"])
    ctx["order"] = confirmed
    return ctx


# ─── Tier 3: in-production order with one line ───
def setup_in_production_order(order_overrides=None, line_overrides=None,
                              product_overrides=None, on_hand_qty=100,
                              pay_full=False, content_ref="X"):
    """A single-line order in IN_PRODUCTION, line ALLOCATED then engraved to ENGRAVING.
    Deposit (or full) is paid first. Returns dict with re-read 'order' and 'line'.
    """
    ctx = setup_confirmed_order(
        order_overrides=order_overrides, line_overrides=line_overrides,
        product_overrides=product_overrides, on_hand_qty=on_hand_qty, content_ref=content_ref,
    )
    order = ctx["order"]
    cust = ctx["customer"]
    invoice_total = order["invoice_total_cents"]
    if pay_full:
        pay(order, cust, invoice_total, "FULL")
    else:
        pay(order, cust, order["deposit_due_cents"], "DEPOSIT")
    started = get_success_data(api_client.start_production(order["id"], STAFF))
    # Engrave the line.
    engraved = get_success_data(api_client.engrave_line(ctx["line"]["id"], STAFF))
    ctx["order"] = started
    ctx["line"] = engraved
    return ctx


# ─── Tier 5: ready order (single line assembled) ───
def setup_ready_order(order_overrides=None, line_overrides=None, product_overrides=None,
                      on_hand_qty=100, pay_full=False, content_ref="X"):
    """A single-line order in READY (line ASSEMBLED, bubble-up fired). Returns dict with
    re-read 'order' and 'line'. If pay_full, the order is also PAID_IN_FULL."""
    ctx = setup_in_production_order(
        order_overrides=order_overrides, line_overrides=line_overrides,
        product_overrides=product_overrides, on_hand_qty=on_hand_qty,
        pay_full=pay_full, content_ref=content_ref,
    )
    assembled = get_success_data(api_client.assemble_line(ctx["line"]["id"], STAFF))
    ctx["line"] = assembled
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], STAFF))
    return ctx


# ─── Tier 5: fulfilled order (PICKUP handed off) ───
def setup_fulfilled_order(order_overrides=None, line_overrides=None, product_overrides=None,
                          on_hand_qty=100, content_ref="X"):
    """A single-line order fully FULFILLED via PICKUP hand-off (paid in full). Returns dict
    with re-read 'order', 'line', 'fulfillment'."""
    ctx = setup_ready_order(
        order_overrides=order_overrides, line_overrides=line_overrides,
        product_overrides=product_overrides, on_hand_qty=on_hand_qty,
        pay_full=True, content_ref=content_ref,
    )
    fulfillment = get_success_data(
        api_client.create_fulfillment(
            ctx["order"]["id"], f.create_fulfillment_payload("PICKUP"), STAFF
        )
    )
    get_success_data(api_client.hand_off(ctx["order"]["id"], fulfillment["id"], STAFF))
    ctx["fulfillment"] = get_success_data(
        api_client.get_order(ctx["order"]["id"], STAFF)
    )
    ctx["order"] = get_success_data(api_client.get_order(ctx["order"]["id"], STAFF))
    return ctx
