"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state
across many API calls (order -> settle -> confirm -> route -> stop -> dispatch ->
complete -> file return -> approve ...). These helpers encapsulate those chains so
tests focus on assertions.

Uses get_success_data() (lenient 2xx validator) internally so a broken setup step
surfaces as a clear "Setup failed" rather than a confusing downstream assertion.

Identity threading: every ownership-gated Customer call uses make_customer_headers
with the real Customer.id, never the shared fallback constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_product_payload, create_customer_payload, create_order_payload,
    create_order_line_payload, create_financing_plan_payload, create_payment_payload,
    create_delivery_route_payload, create_delivery_stop_payload,
    create_protection_plan_payload, create_return_request_payload,
    STANDARD_FABRIC, VELVET_FABRIC, STD_SIZE, QUEEN_SIZE,
)
from .test_users import TEST_USERS, make_customer_headers

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]
DD = TEST_USERS["dispatcher_headers"]


# ─── Clock helper ─────────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the server's notion of current UTC time (StoreManager-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, SM))


# ─── Tier 0: base entities ────────────────────────────────────────────────
def create_product(**overrides):
    """Create a catalog product (StoreManager). Returns the product dict."""
    return get_success_data(api_client.create_product(create_product_payload(**overrides), SM))


def create_customer(**overrides):
    """Create a customer (SalesAssociate). Returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SA))


def create_sofa_product():
    """The canonical in-stock sofa: base 100000, STANDARD/STD, line_total 100000 at qty 1."""
    return create_product()


def create_route(**overrides):
    """Create an OPEN delivery route (DeliveryDispatcher). Returns the route dict."""
    return get_success_data(
        api_client.create_delivery_route(create_delivery_route_payload(**overrides), DD))


# ─── Tier 1: order construction / state progression ───────────────────────
def create_draft_order(customer_id, **order_overrides):
    """A fresh DRAFT/UNPAID order for the given customer."""
    return get_success_data(
        api_client.create_order(create_order_payload(customer_id, **order_overrides), SA))


def add_line(order_id, product_id, **line_overrides):
    """Add one ACTIVE configured line to a DRAFT order. Returns the line dict."""
    return get_success_data(api_client.create_order_line(
        create_order_line_payload(order_id, product_id, **line_overrides), SA))


def setup_order_with_line(product_id=None, customer_id=None, order_overrides=None,
                          line_overrides=None):
    """Customer + product (if not supplied) + DRAFT order + one ACTIVE line.

    Returns (customer, product, order, line).
    """
    product = (get_success_data(api_client.get_product(product_id, SA))
               if product_id else create_sofa_product())
    customer = (get_success_data(api_client.get_customer(customer_id, SA))
                if customer_id else create_customer())
    order = create_draft_order(customer["id"], **(order_overrides or {}))
    line = add_line(order["id"], product["id"], **(line_overrides or {}))
    return customer, product, order, line


def pay_in_full(order_id):
    """Settle an order outright. Returns the updated order dict."""
    return get_success_data(api_client.pay_in_full_order(order_id, SA))


def confirm(order_id):
    """Confirm a settled DRAFT order. Returns the updated order dict."""
    return get_success_data(api_client.confirm_order(order_id, SA))


def setup_confirmed_paid_order(product_id=None, customer_id=None, order_overrides=None,
                               line_overrides=None):
    """A CONFIRMED, PAID_IN_FULL order with one ACTIVE line.

    Returns (customer, product, order, line). The returned order reflects the
    confirm response (recomputed totals, earliest_schedulable_date set).
    """
    customer, product, order, line = setup_order_with_line(
        product_id=product_id, customer_id=customer_id,
        order_overrides=order_overrides, line_overrides=line_overrides)
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    return customer, product, confirmed, line


# ─── Tier 2: full delivery lifecycle (order -> DELIVERED) ──────────────────
def book_stop(route_id, order_id, route_version, **stop_overrides):
    """Book a DeliveryStop on a route for a confirmed order. Returns the stop dict."""
    return get_success_data(api_client.create_delivery_stop(
        create_delivery_stop_payload(route_id, order_id, route_version, **stop_overrides), DD))


def deliver_order(order_id, route=None, stop_overrides=None):
    """Drive a CONFIRMED order all the way to DELIVERED.

    Creates (or reuses) a route, books a stop, locks the route, dispatches and
    completes the stop. Completion bubbles the order to DELIVERED and stamps the
    line's delivered_on baseline. Returns (route, stop).
    """
    if route is None:
        route = create_route()
    stop = book_stop(route["id"], order_id, route["version"], **(stop_overrides or {}))
    get_success_data(api_client.lock_delivery_route(route["id"], DD))
    get_success_data(api_client.dispatch_delivery_stop(stop["id"], DD))
    get_success_data(api_client.complete_delivery_stop(stop["id"], DD))
    return route, stop


def setup_delivered_order(line_overrides=None, order_overrides=None, product_overrides=None,
                          customer_overrides=None, deliver_iso="2026-03-01T09:00:00Z"):
    """A fully delivered order (fulfillment_status DELIVERED) with one ACTIVE line.

    Returns (customer, product, order, line, route, stop). The order/line dicts are
    the pre-delivery snapshots; re-GET for current state if needed.

    Pins the clock to deliver_iso (defaulting to the route factory's default
    service_date, 2026-03-01) before creating the order so the order's
    created_at-date-based earliest_schedulable_date does not run ahead of the route's
    service_date (PRD §3.4 esd = created_at date + lead_days; §3.8 lead-time gate
    ERR_LEAD_TIME_NOT_MET). Without this, the order is created at real wall-clock time
    and the lead-time gate correctly rejects booking on the 2026-03-01 route.
    """
    set_clock(deliver_iso)
    product = create_sofa_product() if product_overrides is None else create_product(**product_overrides)
    customer = (create_customer(**customer_overrides) if customer_overrides
                else create_customer())
    order = create_draft_order(customer["id"], **(order_overrides or {}))
    line = add_line(order["id"], product["id"], **(line_overrides or {}))
    pay_in_full(order["id"])
    confirm(order["id"])
    route, stop = deliver_order(order["id"])
    return customer, product, order, line, route, stop


# ─── Tier 3: returns ──────────────────────────────────────────────────────
def file_return(order_line_id, customer_id, reason="CHANGED_MIND"):
    """File a ReturnRequest as the owning Customer (ownership-gated).

    Threads the real customer id through make_customer_headers. Returns the request.
    """
    return get_success_data(api_client.create_return_request(
        create_return_request_payload(order_line_id, reason=reason),
        make_customer_headers(customer_id)))


def setup_approved_return(reason="CHANGED_MIND", line_overrides=None,
                          product_overrides=None, deliver_iso="2026-03-01T09:00:00Z",
                          file_iso=None):
    """A delivered line with an APPROVED return (refund figures computed, not disbursed).

    Sets the clock to deliver_iso before delivery; if file_iso is given, advances the
    clock to it before filing. Returns (customer, product, order, line, return_request).
    """
    customer, product, order, line, route, stop = setup_delivered_order(
        line_overrides=line_overrides, product_overrides=product_overrides,
        deliver_iso=deliver_iso)
    if file_iso:
        set_clock(file_iso)
    ret = file_return(line["id"], customer["id"], reason=reason)
    approved = get_success_data(api_client.approve_return_request(ret["id"], SM))
    return customer, product, order, line, approved


# ─── Tier 4: financing lifecycle ──────────────────────────────────────────
def apply_financing(order_id, expected_order_version, **overrides):
    """Apply for a PENDING_APPROVAL FinancingPlan against an order. Returns the plan."""
    return get_success_data(api_client.create_financing_plan(
        create_financing_plan_payload(order_id, expected_order_version, **overrides), SA))


def setup_pending_financing_plan(plan_type="INSTALLMENT", term_months=12,
                                 customer_overrides=None, line_overrides=None):
    """A single-line order with a PENDING_APPROVAL plan (no snapshot yet).

    Default sofa line gives order_total 116802 (merch 100000 + threshold 7900 + tax).
    Returns (customer, product, order, line, plan).
    """
    product = create_sofa_product()
    customer = create_customer(**(customer_overrides or {}))
    order = create_draft_order(customer["id"])
    line = add_line(order["id"], product["id"], **(line_overrides or {}))
    fresh = get_success_data(api_client.get_order(order["id"], SA))
    plan = apply_financing(order["id"], fresh["version"],
                           plan_type=plan_type, term_months=term_months)
    return customer, product, order, line, plan


def setup_active_financing_plan(plan_type="INSTALLMENT", term_months=12,
                                customer_overrides=None, line_overrides=None):
    """A CURRENT (approved) financing plan; Order.payment_status == FINANCED.

    Returns (customer, product, order, line, plan) where plan reflects the approve
    response (financed_principal snapshotted, monthly schedule computed).
    """
    customer, product, order, line, plan = setup_pending_financing_plan(
        plan_type=plan_type, term_months=term_months,
        customer_overrides=customer_overrides, line_overrides=line_overrides)
    approved = get_success_data(api_client.approve_financing_plan(plan["id"], SM))
    return customer, product, order, line, approved


def post_payment(plan_id, amount_cents):
    """Post a payment against a plan. Returns the Payment row."""
    return get_success_data(api_client.create_payment(
        plan_id, create_payment_payload(amount_cents), SA))


def setup_plan_after_payments(amounts, plan_type="INSTALLMENT", term_months=12):
    """An approved plan with the given list of in-schedule payments posted.

    Returns (order, plan_id). Re-GET the plan for current computed fields.
    """
    customer, product, order, line, plan = setup_active_financing_plan(
        plan_type=plan_type, term_months=term_months)
    for amt in amounts:
        post_payment(plan["id"], amt)
    return order, plan["id"]
