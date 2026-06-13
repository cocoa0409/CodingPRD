"""Composite setup helpers.

These encapsulate the multi-step preambles that the bakery workflow requires to
reach a given order/payment/reservation state. Each test that needs a specific
state imports the matching helper rather than re-inventing the chain inline.

The harness re-launches the API server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.
All setup calls use get_success_data() (lenient) so a setup misstep surfaces as
a clear "Setup failed" rather than a confusing assertion failure.

Identity threading: the Customer role is entity_backed, so every ownership-gated
call uses make_customer_headers(customer["id"]). The opaque operator roles
(BakeryStaff, DeliveryDispatcher, BakeryManager) use the shared headers.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_staff_headers,
    make_dispatcher_headers,
    make_manager_headers,
)
from . import factories as F


MANAGER = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANON = {"X-User-Role": "Anonymous"}

_email_counter = itertools.count(1)


def unique_email(prefix="cust") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


# ---------------------------------------------------------------------------
# Primitive setup
# ---------------------------------------------------------------------------
def set_clock(now_iso="2026-06-01T00:00:00Z"):
    """Pin the server clock for deterministic lead-time/cutoff behavior."""
    return get_success_data(api_client.set_clock({"now_iso8601": now_iso}, MANAGER))


def create_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(F.product_payload(**overrides), MANAGER))


def create_option(option_code, surcharge_cents, **overrides) -> dict:
    return get_success_data(
        api_client.create_option(F.option_payload(option_code, surcharge_cents, **overrides), MANAGER)
    )


def create_production_day(**overrides) -> dict:
    return get_success_data(api_client.create_production_day(F.production_day_payload(**overrides), MANAGER))


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(F.route_payload(**overrides), MANAGER))


def create_customer(email=None, full_name="Test Customer", **overrides) -> dict:
    email = email or unique_email()
    return get_success_data(
        api_client.create_customer(F.customer_payload(email, full_name, **overrides), ANON)
    )


def grant_credit(customer_id, delta_cents, reason="grant") -> dict:
    return get_success_data(
        api_client.adjust_credit(customer_id, F.credit_adjustment_payload(delta_cents, reason), MANAGER)
    )


def create_order(customer, product, production_day, **overrides) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.create_order(
            F.order_payload(customer["id"], product["id"], production_day["id"], **overrides), headers
        )
    )


def add_line(order, customer, units=1, selected_option_codes=None, requested_dietary_codes=None) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.add_line(
            order["id"],
            F.line_payload(units, selected_option_codes, requested_dietary_codes),
            headers,
        )
    )


def quote(order, customer, manager_override_token=None) -> dict:
    headers = make_customer_headers(customer["id"])
    payload = {}
    if manager_override_token is not None:
        payload["manager_override_token"] = manager_override_token
    return get_success_data(api_client.quote_order(order["id"], payload, headers))


def pay_deposit(order, customer) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.post_payment(order["id"], F.deposit_payment_payload(), headers))


def post_proof(order, image_ref="proof") -> dict:
    return get_success_data(api_client.post_proof(order["id"], F.proof_payload(image_ref), STAFF))


def approve_proof(order, proof, customer) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.approve_proof(order["id"], proof["id"], {}, headers))


def request_changes(order, proof, customer, change_note="please revise") -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.request_changes(order["id"], proof["id"], {"change_note": change_note}, headers)
    )


def read_order(order_id, customer) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.get_order(order_id, headers))


def pay_balance(order, customer, applied_credit_cents=0) -> dict:
    """Capture the balance with the order's CURRENT version (re-read first)."""
    headers = make_customer_headers(customer["id"])
    fresh = get_success_data(api_client.get_order(order["id"], headers))
    payload = F.balance_payment_payload(fresh["version"], applied_credit_cents)
    return get_success_data(api_client.post_balance_payment(order["id"], payload, headers))


def create_slot(order, customer, fulfillment_mode="PICKUP", route_id=None, window_start_min=None) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(
        api_client.create_slot(
            order["id"], F.slot_payload(fulfillment_mode, route_id, window_start_min), headers
        )
    )


def commit_slot(order, reservation, customer) -> dict:
    """Commit a reservation using the order's CURRENT version (re-read first)."""
    headers = make_customer_headers(customer["id"])
    fresh = get_success_data(api_client.get_order(order["id"], headers))
    return get_success_data(
        api_client.commit_slot(order["id"], reservation["id"], F.commit_payload(fresh["version"]), DISPATCHER)
    )


# ---------------------------------------------------------------------------
# Tier 1/2: Catalog setup
# ---------------------------------------------------------------------------
def setup_catalog(product_overrides=None, pday_overrides=None, options=None):
    """Clock + product + production day + customer; optionally a set of options.

    `options` is a list of (option_code, surcharge_cents, kwargs) tuples.
    Returns dict with keys: product, production_day, customer.
    """
    set_clock()
    for opt in (options or []):
        code, surcharge = opt[0], opt[1]
        kw = opt[2] if len(opt) > 2 else {}
        create_option(code, surcharge, **kw)
    product = create_product(**(product_overrides or {}))
    production_day = create_production_day(**(pday_overrides or {}))
    customer = create_customer()
    return {"product": product, "production_day": production_day, "customer": customer}


def setup_draft_order(product_overrides=None, pday_overrides=None, options=None):
    """Catalog + a DRAFT order. Returns (order, customer, product, production_day)."""
    ctx = setup_catalog(product_overrides, pday_overrides, options)
    order = create_order(ctx["customer"], ctx["product"], ctx["production_day"])
    return order, ctx["customer"], ctx["product"], ctx["production_day"]


# ---------------------------------------------------------------------------
# Tier 1/3: Order lifecycle progression
# ---------------------------------------------------------------------------
def setup_quoted_order(units=1, selected_option_codes=None, requested_dietary_codes=None,
                       product_overrides=None, pday_overrides=None, options=None):
    """DRAFT -> add one line -> QUOTED. Returns (order, customer, product, production_day)."""
    order, customer, product, pday = setup_draft_order(product_overrides, pday_overrides, options)
    add_line(order, customer, units, selected_option_codes, requested_dietary_codes)
    quote(order, customer)
    return order, customer, product, pday


def setup_deposit_paid_order(units=1, **kwargs):
    """QUOTED -> DEPOSIT_PAID. Returns (order, customer, product, production_day)."""
    order, customer, product, pday = setup_quoted_order(units=units, **kwargs)
    pay_deposit(order, customer)
    return order, customer, product, pday


def setup_proof_pending_order(units=1, image_ref="p1", **kwargs):
    """DEPOSIT_PAID -> first proof posted (PROOF_PENDING).
    Returns (order, customer, proof, product, production_day)."""
    order, customer, product, pday = setup_deposit_paid_order(units=units, **kwargs)
    proof = post_proof(order, image_ref)
    return order, customer, proof, product, pday


def setup_proof_approved_order(units=1, image_ref="p1", **kwargs):
    """PROOF_PENDING -> proof approved (PROOF_APPROVED, lines locked, final priced).
    Returns (order, customer, proof, product, production_day)."""
    order, customer, proof, product, pday = setup_proof_pending_order(units=units, image_ref=image_ref, **kwargs)
    approve_proof(order, proof, customer)
    return order, customer, proof, product, pday


def setup_paid_in_full_order(units=1, applied_credit_cents=0, **kwargs):
    """PROOF_APPROVED + balance captured (PAID_IN_FULL).
    Returns (order, customer, proof, product, production_day)."""
    order, customer, proof, product, pday = setup_proof_approved_order(units=units, **kwargs)
    pay_balance(order, customer, applied_credit_cents)
    return order, customer, proof, product, pday


def setup_committed_pickup_order(units=1, **kwargs):
    """Full path to PROOF_APPROVED + PAID_IN_FULL + a COMMITTED PICKUP reservation.
    Returns (order, customer, reservation, product, production_day)."""
    order, customer, proof, product, pday = setup_paid_in_full_order(units=units, **kwargs)
    reservation = create_slot(order, customer, "PICKUP")
    commit_slot(order, reservation, customer)
    return order, customer, reservation, product, pday


def setup_committed_delivery_order(window_start_min, route, units=1, **kwargs):
    """Full path to a COMMITTED DELIVERY reservation on `route` at window_start_min.
    Returns (order, customer, reservation, product, production_day)."""
    order, customer, proof, product, pday = setup_paid_in_full_order(units=units, **kwargs)
    reservation = create_slot(order, customer, "DELIVERY", route_id=route["id"],
                              window_start_min=window_start_min)
    commit_slot(order, reservation, customer)
    return order, customer, reservation, product, pday


def setup_fulfilled_order(units=1, **kwargs):
    """Drive an order all the way to terminal FULFILLED.
    Returns (order, customer, reservation, product, production_day)."""
    order, customer, reservation, product, pday = setup_committed_pickup_order(units=units, **kwargs)
    get_success_data(api_client.start_production(order["id"], {}, STAFF))
    get_success_data(api_client.mark_ready(order["id"], {}, STAFF))
    get_success_data(api_client.fulfill(order["id"], {}, STAFF))
    return order, customer, reservation, product, pday


# ---------------------------------------------------------------------------
# Tier 4: Capacity targeting — pre-commit units onto a production day
# ---------------------------------------------------------------------------
def commit_units_on_day(production_day, customer, product, units):
    """Drive one fresh order to a COMMITTED PICKUP reservation against
    `production_day` carrying `units` units, raising units_committed by `units`.
    Reuses the same product and customer. Returns (order, reservation)."""
    order = create_order(customer, product, production_day)
    add_line(order, customer, units)
    quote(order, customer)
    pay_deposit(order, customer)
    proof = post_proof(order, "cap")
    approve_proof(order, proof, customer)
    pay_balance(order, customer, 0)
    reservation = create_slot(order, customer, "PICKUP")
    commit_slot(order, reservation, customer)
    return order, reservation
