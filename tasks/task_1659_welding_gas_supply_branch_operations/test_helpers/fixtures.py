"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains —
accounts, catalog stock, cylinder float, contract price books, order
lifecycle, rental lifecycle, billing runs — out of PRD-declared endpoints
only (PRD §4).

All roles are opaque staff identities (PRD §2.1), so the shared role headers
are used directly for every call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cylinder_asset_payload,
    create_customer_payload,
    create_delivery_route_payload,
    create_enrollment_payload,
    create_machine_payload,
    create_order_payload,
    create_price_book_payload,
    create_product_payload,
    create_rental_agreement_payload,
    create_repair_ticket_payload,
    create_training_class_payload,
)
from .test_users import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
TRAINER = TEST_USERS["trainer_headers"]
TECH = TEST_USERS["service_tech_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (BranchManager-only, PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, MANAGER))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def make_customer(**overrides):
    """Open a customer account (CounterRep). Defaults: terms CASH."""
    resp = api_client.create_customer(create_customer_payload(**overrides),
                                      COUNTER)
    return get_success_data(resp)


def make_product(stock=None, **overrides):
    """Register a product (BranchManager); optionally receive `stock` units."""
    product = get_success_data(
        api_client.create_product(create_product_payload(**overrides), MANAGER))
    if stock:
        product = get_success_data(
            api_client.receive_stock(product["id"], {"qty": stock}, MANAGER))
    return product


def make_cylinder(**overrides):
    """Register a cylinder into the float; it arrives FULL (PRD §3.2)."""
    return get_success_data(api_client.create_cylinder_asset(
        create_cylinder_asset_payload(**overrides), MANAGER))


def make_machine(**overrides):
    """Register a rental weld machine; it starts AVAILABLE (PRD §3.2)."""
    return get_success_data(
        api_client.create_machine(create_machine_payload(**overrides), MANAGER))


def make_route(**overrides):
    """Plan a delivery route; it starts PLANNED with reserved_units 0."""
    return get_success_data(api_client.create_delivery_route(
        create_delivery_route_payload(**overrides), COUNTER))


def make_training_class(**overrides):
    """Schedule a class (Trainer); it starts SCHEDULED with seats_booked 0."""
    return get_success_data(api_client.create_training_class(
        create_training_class_payload(**overrides), TRAINER))


def make_enrollment(class_id, customer_id, **overrides):
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(class_id, customer_id, **overrides), TRAINER))


def make_repair_ticket(customer_id, **overrides):
    return get_success_data(api_client.create_repair_ticket(
        create_repair_ticket_payload(customer_id, **overrides), TECH))


# ---------------------------------------------------------------------------
# Tier 1: readers (lenient)
# ---------------------------------------------------------------------------

def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, COUNTER))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, COUNTER))


def get_cylinder(asset_id):
    return get_success_data(api_client.get_cylinder_asset(asset_id, COUNTER))


def get_machine(machine_id):
    return get_success_data(api_client.get_machine(machine_id, COUNTER))


def get_rental(agreement_id):
    return get_success_data(api_client.get_rental_agreement(agreement_id,
                                                            COUNTER))


def get_route(route_id):
    return get_success_data(api_client.get_delivery_route(route_id, COUNTER))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, COUNTER))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, COUNTER))


def get_class(class_id):
    return get_success_data(api_client.get_training_class(class_id, TRAINER))


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, TRAINER))


def get_ticket(ticket_id):
    return get_success_data(api_client.get_repair_ticket(ticket_id, TECH))


def get_float_summary():
    return get_success_data(api_client.get_float_summary(COUNTER))


# ---------------------------------------------------------------------------
# Tier 2: price books
# ---------------------------------------------------------------------------

def make_active_contract_book(customer_id, link=True, **book_overrides):
    """Create + activate a CONTRACT price book for the customer, then attach
    it to the account via the update path (the only way to link a book after
    creation, PRD §3.1). Returns the ACTIVE book."""
    payload = create_price_book_payload(scope="CONTRACT",
                                        customer_id=customer_id,
                                        **book_overrides)
    book = get_success_data(api_client.create_price_book(payload, MANAGER))
    book = get_success_data(api_client.activate_price_book(book["id"], MANAGER))
    if link:
        get_success_data(api_client.update_customer(
            customer_id, {"price_book_id": book["id"]}, COUNTER))
    return book


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle
# ---------------------------------------------------------------------------

def make_order(customer_id, lines, **overrides):
    """Create a DRAFT order. `lines` is a list of {product_id, qty} dicts."""
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, lines, **overrides), COUNTER))


def confirm_order(order_id):
    return get_success_data(api_client.confirm_order(order_id, COUNTER))


def stage_order(order_id):
    return get_success_data(api_client.stage_order(order_id, COUNTER))


def pay_order(order_id, amount_cents):
    return get_success_data(
        api_client.pay_order(order_id, {"amount_cents": amount_cents}, COUNTER))


def fulfill_order(order_id, headers=COUNTER, **payload):
    return get_success_data(api_client.fulfill_order(order_id, payload, headers))


def make_confirmed_order(customer_id, product_id, qty, **order_overrides):
    """DRAFT order walked to CONFIRMED (pricing snapshot taken)."""
    order = make_order(customer_id, [{"product_id": product_id, "qty": qty}],
                       **order_overrides)
    return confirm_order(order["id"])


def make_staged_cash_order(customer_id, product_id, qty, pay=True,
                           **order_overrides):
    """CASH order walked to STAGED; when `pay` is true it is paid in full at
    the confirmed total first (payment before fulfillment, PRD §3.4)."""
    order = make_confirmed_order(customer_id, product_id, qty, **order_overrides)
    if pay:
        order = pay_order(order["id"], order["total_cents"])
    return stage_order(order["id"])


def make_fulfilled_net30_order(customer_id, product_id, qty,
                               **order_overrides):
    """NET30 order walked DRAFT -> CONFIRMED -> STAGED -> FULFILLED, which
    posts its ORDER invoice (PRD §3.4). Returns the fulfilled order (its
    invoice_id is set)."""
    order = make_confirmed_order(customer_id, product_id, qty, **order_overrides)
    order = stage_order(order["id"])
    return fulfill_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 4: rentals and billing
# ---------------------------------------------------------------------------

def make_demurrage_rental(customer_id, asset_id=None, start_date="2026-08-01",
                          grace_days=5, **overrides):
    """Open a cylinder DEMURRAGE agreement (cylinder FULL -> OUT). Creates a
    fresh cylinder when asset_id is not given."""
    if asset_id is None:
        asset_id = make_cylinder()["id"]
    payload = create_rental_agreement_payload(
        customer_id, item_type="CYLINDER", cylinder_asset_id=asset_id,
        rate_plan="DEMURRAGE", start_date=start_date, grace_days=grace_days,
        **overrides)
    return get_success_data(api_client.create_rental_agreement(payload, COUNTER))


def make_machine_rental(customer_id, machine_id, rate_plan="DAILY",
                        start_date="2026-08-01", **overrides):
    """Open a machine rental (machine AVAILABLE -> RENTED)."""
    payload = create_rental_agreement_payload(
        customer_id, item_type="MACHINE", machine_id=machine_id,
        rate_plan=rate_plan, start_date=start_date, **overrides)
    return get_success_data(api_client.create_rental_agreement(payload, COUNTER))


def run_billing_cycle():
    """Run the monthly rental billing cycle (BranchManager, PRD §3.6)."""
    return get_success_data(api_client.run_rental_billing_cycle(MANAGER))


def get_fresh_customer_version(customer_id):
    """Read the customer's current version for the OCC payment token."""
    return get_customer(customer_id)["version"]


def get_fresh_rental_version(agreement_id):
    """Read the agreement's current version for the OCC waiver token."""
    return get_rental(agreement_id)["version"]


def apply_payment(customer_id, amount_cents):
    """Apply a payment with a freshly-read expected_customer_version."""
    version = get_fresh_customer_version(customer_id)
    return get_success_data(api_client.apply_payment(
        customer_id, {"amount_cents": amount_cents,
                      "expected_customer_version": version}, COUNTER))
