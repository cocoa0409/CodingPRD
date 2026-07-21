"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion mismatches.

The harness restarts the server (empty DB) before every test, so every helper
here builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_product_payload,
    create_license_type_payload,
    create_license_sale_payload,
    create_guide_payload,
    create_charter_payload,
    create_booking_payload,
    create_tournament_payload,
    create_entry_payload,
    create_service_order_payload,
)
from .test_users import TEST_USERS

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Tier 0: logical clock ────────────────────────────────────
def set_clock(iso: str):
    """Advance the logical clock to `iso` (as ShopManager)."""
    return get_success_data(api_client.set_clock(iso, MANAGER))


# ─── Tier 1: single-entity creators ───────────────────────────
def new_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), CLERK))


def new_product(**overrides):
    return get_success_data(api_client.create_product(create_product_payload(**overrides), MANAGER))


def new_license_type(**overrides):
    return get_success_data(
        api_client.create_license_type(create_license_type_payload(**overrides), MANAGER)
    )


def issue_license(customer_id, license_type_id):
    return get_success_data(
        api_client.create_license_sale(
            create_license_sale_payload(customer_id, license_type_id), CLERK
        )
    )


def new_guide(**overrides):
    return get_success_data(api_client.create_guide(create_guide_payload(**overrides), MANAGER))


def new_charter(guide_id, **overrides):
    return get_success_data(
        api_client.create_charter(create_charter_payload(guide_id, **overrides), MANAGER)
    )


def new_booking(charter_id, customer_id, **overrides):
    return get_success_data(
        api_client.create_booking(create_booking_payload(charter_id, customer_id, **overrides), CLERK)
    )


def new_tournament(**overrides):
    return get_success_data(
        api_client.create_tournament(create_tournament_payload(**overrides), MANAGER)
    )


def new_service_order(customer_id, **overrides):
    return get_success_data(
        api_client.create_service_order(create_service_order_payload(customer_id, **overrides), CLERK)
    )


# ─── Tier 2: loyalty tier seeding ─────────────────────────────
def make_customer_at_tier(tier: str, **cust_overrides):
    """Register a customer and seed lifetime points via a manual adjustment so the
    derived loyalty_tier becomes `tier`. Returns the refreshed customer dict."""
    customer = new_customer(**cust_overrides)
    delta = {"BRONZE": 0, "SILVER": 500, "GOLD": 2000}[tier]
    if delta:
        customer = get_success_data(
            api_client.adjust_loyalty(
                customer["id"], {"points_delta": delta, "reason": "seed-tier"}, MANAGER
            )
        )
    return customer


# ─── Tier 3: charter / booking lifecycle shortcuts ────────────
def setup_licensed_customer(lt_overrides=None, cust_overrides=None):
    """Customer + license type + issued ACTIVE license. Returns (customer, lt, sale)."""
    customer = new_customer(**(cust_overrides or {}))
    lt = new_license_type(**(lt_overrides or {}))
    sale = issue_license(customer["id"], lt["id"])
    return customer, lt, sale


def create_paid_booking(charter_id, customer_id, seats=1):
    """Book seats then pay. Returns the PAID booking dict."""
    booking = new_booking(charter_id, customer_id, seats=seats)
    return get_success_data(api_client.pay_booking(booking["id"], CLERK))


def create_checked_in_booking(charter_id, customer_id, seats=1):
    """Book -> pay -> check in. Returns the CHECKED_IN booking dict."""
    booking = new_booking(charter_id, customer_id, seats=seats)
    get_success_data(api_client.pay_booking(booking["id"], CLERK))
    return get_success_data(api_client.checkin_booking(booking["id"], CLERK))


def create_completed_booking(charter_id, customer_id, seats=1):
    """Book -> pay -> check in -> complete. Returns the COMPLETED booking dict."""
    booking = create_checked_in_booking(charter_id, customer_id, seats=seats)
    return get_success_data(api_client.complete_booking(booking["id"], CLERK))


# ─── Tier 4: service-order lifecycle shortcuts ────────────────
def setup_service_order_in_progress(
    customer=None, product=None, base=2500, rate=30, estimated=100, stock=50
):
    """Open a SPOOLING order and walk it INTAKE -> DIAGNOSED -> IN_PROGRESS.

    Returns (customer, product, order) with quoted_cents pinned at DIAGNOSED.
    """
    if customer is None:
        customer = new_customer()
    if product is None:
        product = new_product(stock_qty=stock)
    order = new_service_order(
        customer["id"],
        product_id=product["id"],
        line_price_cents_per_meter=rate,
        estimated_line_meters=estimated,
        base_service_cents=base,
    )
    order = get_success_data(
        api_client.transition_service_order(order["id"], {"to_status": "DIAGNOSED"}, CLERK)
    )
    order = get_success_data(
        api_client.transition_service_order(order["id"], {"to_status": "IN_PROGRESS"}, CLERK)
    )
    return customer, product, order


def setup_service_order_ready(
    customer=None, product=None, base=2500, rate=30, estimated=100,
    actual=120, parts=800, line_units=2, stock=50,
):
    """Walk a SPOOLING order through to READY (final subtotal pinned, stock consumed).

    Returns (customer, product, order).
    """
    customer, product, order = setup_service_order_in_progress(
        customer=customer, product=product, base=base, rate=rate,
        estimated=estimated, stock=stock,
    )
    order = get_success_data(
        api_client.transition_service_order(
            order["id"],
            {"to_status": "READY", "actual_line_meters": actual,
             "parts_cents": parts, "line_units": line_units},
            CLERK,
        )
    )
    return customer, product, order


# ─── Tier 5: tournament lifecycle shortcuts ───────────────────
def setup_tournament_in_progress(**t_overrides):
    """Create a tournament and advance SCHEDULED -> OPEN -> IN_PROGRESS.

    Returns the IN_PROGRESS tournament dict.
    """
    tournament = new_tournament(**t_overrides)
    get_success_data(
        api_client.set_tournament_status(tournament["id"], {"status": "OPEN"}, MANAGER)
    )
    return get_success_data(
        api_client.set_tournament_status(tournament["id"], {"status": "IN_PROGRESS"}, MANAGER)
    )


def register_open_entry(tournament_id, customer_id):
    """Register a customer into an OPEN tournament. Returns the REGISTERED entry."""
    return get_success_data(
        api_client.create_entry(create_entry_payload(tournament_id, customer_id), CLERK)
    )
