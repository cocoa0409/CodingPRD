"""Composite setup helpers.

Every helper builds its preconditions from scratch against PRD-declared endpoints
(the harness restarts the server before each test, so the DB always starts empty
with the clock at its 2026-07-01T00:00:00Z startup default). Helpers use the
lenient get_success_data() so setup failures surface as clear "Setup failed"
errors rather than confusing assertion failures.

Identity threading: after registering an entity-backed principal (Customer /
FitSpecialist), ownership-gated calls use make_<role>_headers(entity_id) with the
real id — never the shared fallback constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_fit_specialist_headers,
    make_anonymous_headers,
)
from . import factories

SM = TEST_USERS["store_manager_headers"]

_email_counter = itertools.count(1)


def unique_email(prefix="user"):
    return f"{prefix}{next(_email_counter)}@example.com"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, SM))


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
def register_customer(api, **overrides):
    if "email" not in overrides:
        overrides["email"] = unique_email("cust")
    payload = factories.register_customer_payload(**overrides)
    return get_success_data(api.register_customer(payload, make_anonymous_headers()))


def seed_loyalty(api, customer_id, delta_points):
    return get_success_data(
        api.adjust_customer_loyalty(customer_id, {"delta_points": delta_points}, SM)
    )


def adjust_wallet(api, customer_id, delta_cents):
    return get_success_data(
        api.adjust_customer_wallet(customer_id, {"delta_cents": delta_cents}, SM)
    )


def suspend_customer(api, customer_id):
    return get_success_data(
        api.set_customer_status(customer_id, {"to_status": "SUSPENDED"}, SM)
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
def create_product(api, **overrides):
    payload = factories.create_product_payload(**overrides)
    return get_success_data(api.create_product(payload, SM))


def create_variant(api, product_id, **overrides):
    payload = factories.create_variant_payload(**overrides)
    return get_success_data(api.create_variant(product_id, payload, SM))


def create_product_and_variant(api, product_overrides=None, variant_overrides=None):
    product = create_product(api, **(product_overrides or {}))
    variant = create_variant(api, product["id"], **(variant_overrides or {}))
    return product, variant


# ---------------------------------------------------------------------------
# Specialists & appointments
# ---------------------------------------------------------------------------
def create_specialist(api, **overrides):
    payload = factories.create_specialist_payload(**overrides)
    return get_success_data(api.create_specialist(payload, SM))


def book_appointment(api, customer_id, specialist_id, start_at, end_at, **overrides):
    payload = factories.create_appointment_payload(specialist_id, start_at, end_at, **overrides)
    return get_success_data(
        api.create_appointment(payload, make_customer_headers(customer_id))
    )


def confirm_appointment(api, appointment_id):
    """Confirm as StoreManager (a shared confirm actor)."""
    return get_success_data(
        api.transition_appointment(appointment_id, {"action": "CONFIRM"}, SM)
    )


def book_and_confirm_appointment(api, customer_id, specialist_id, start_at, end_at, **overrides):
    appt = book_appointment(api, customer_id, specialist_id, start_at, end_at, **overrides)
    confirm_appointment(api, appt["id"])
    return get_success_data(api.get_appointment(appt["id"], SM))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
def open_order(api, customer_id):
    return get_success_data(api.create_order(make_customer_headers(customer_id)))


def add_line(api, order_id, customer_id, variant_id, quantity=1):
    payload = factories.add_line_payload(variant_id, quantity)
    return get_success_data(
        api.add_order_line(order_id, payload, make_customer_headers(customer_id))
    )


def checkout(api, order_id, customer_id, **payload):
    return get_success_data(
        api.checkout_order(order_id, payload, make_customer_headers(customer_id))
    )


def order_transition(api, order_id, action, customer_id=None):
    """CAPTURE/PICK/SHIP/DELIVER are StoreManager ops; CANCEL may be Customer."""
    if action == "CANCEL" and customer_id is not None:
        headers = make_customer_headers(customer_id)
    else:
        headers = SM
    return get_success_data(api.transition_order(order_id, {"action": action}, headers))


def drive_order_to_delivered(api, order_id, customer_id):
    order_transition(api, order_id, "CAPTURE")
    order_transition(api, order_id, "PICK")
    order_transition(api, order_id, "SHIP")
    return order_transition(api, order_id, "DELIVER")


def setup_order_with_line(api, product_overrides=None, variant_overrides=None, quantity=1,
                          customer_overrides=None):
    """Registered customer + product + variant + open order + one line.

    Returns a dict: customer, product, variant, order, line.
    """
    customer = register_customer(api, **(customer_overrides or {}))
    product, variant = create_product_and_variant(api, product_overrides, variant_overrides)
    order = open_order(api, customer["id"])
    line = add_line(api, order["id"], customer["id"], variant["id"], quantity)
    return {
        "customer": customer,
        "product": product,
        "variant": variant,
        "order": order,
        "line": line,
    }


def setup_delivered_order(api, product_overrides=None, variant_overrides=None, quantity=1,
                          customer_overrides=None, checkout_payload=None):
    """Full order lifecycle through DELIVERED, ready for returns.

    Returns a dict: customer, product, variant, order (delivered), line.
    """
    ctx = setup_order_with_line(api, product_overrides, variant_overrides, quantity,
                                customer_overrides)
    checkout(api, ctx["order"]["id"], ctx["customer"]["id"], **(checkout_payload or {}))
    drive_order_to_delivered(api, ctx["order"]["id"], ctx["customer"]["id"])
    ctx["order"] = get_success_data(api.get_order(ctx["order"]["id"], SM))
    return ctx


# ---------------------------------------------------------------------------
# Subscriptions & box shipments
# ---------------------------------------------------------------------------
def create_subscription(api, customer_id, plan_tier, **overrides):
    payload = factories.create_subscription_payload(plan_tier, **overrides)
    return get_success_data(
        api.create_subscription(payload, make_customer_headers(customer_id))
    )


def curate_shipment(api, subscription_id, expected_version, item_variant_ids,
                    specialist_id=None):
    """Curate a box. Defaults to StoreManager; pass specialist_id to act as a
    FitSpecialist (both are permitted curation actors)."""
    payload = factories.curate_shipment_payload(expected_version, item_variant_ids)
    headers = make_fit_specialist_headers(specialist_id) if specialist_id else SM
    return get_success_data(api.create_shipment(subscription_id, payload, headers))


def set_subscription_status(api, subscription_id, customer_id, to_status):
    return get_success_data(
        api.set_subscription_status(
            subscription_id, {"to_status": to_status}, make_customer_headers(customer_id)
        )
    )


def setup_curated_box(api, plan_tier="ESSENTIALS", variant_overrides=None,
                      product_overrides=None, num_items=1, customer_overrides=None):
    """Registered customer + ACTIVE subscription + one product + N variants + a
    CURATED box holding all of them.

    Returns a dict: customer, product, variants (list), subscription, shipment.
    """
    customer = register_customer(api, **(customer_overrides or {}))
    product = create_product(api, **(product_overrides or {}))
    variants = []
    base_size = (variant_overrides or {}).get("size_code", 22)
    for i in range(num_items):
        vo = dict(variant_overrides or {})
        vo["size_code"] = base_size + i * 2
        variants.append(create_variant(api, product["id"], **vo))
    subscription = create_subscription(api, customer["id"], plan_tier)
    shipment = curate_shipment(
        api, subscription["id"], subscription["version"],
        [v["id"] for v in variants],
    )
    return {
        "customer": customer,
        "product": product,
        "variants": variants,
        "subscription": subscription,
        "shipment": shipment,
    }
