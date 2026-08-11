"""Composite setup helpers for multi-step PRD workflows.

Every helper builds preconditions from scratch through the public API and
returns validated response data. Error-path probes stay in the tests.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import (
    CLOCK_2026_05_01_0900,
    DEFAULT_EVENT_DATE,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .test_users import TEST_USERS, make_customer_agent_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DEPOT_MGR = TEST_USERS["depot_manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CLERK_1 = TEST_USERS["billing_clerk_1_headers"]
CLERK_2 = TEST_USERS["billing_clerk_2_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


def agent(customer_id):
    """Entity-backed CustomerAgent headers threaded to the owning customer."""
    return make_customer_agent_headers(customer_id)


# --- Platform / network onboarding --------------------------------------------

def set_logical_clock(to_iso8601=CLOCK_2026_05_01_0900):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def make_depot(capacity=10, name="Depot"):
    return get_success_data(
        api_client.create_depot(factories.depot_payload(name, capacity), ADMIN)
    )


def make_customer(**overrides):
    return get_success_data(
        api_client.create_customer(factories.customer_payload(**overrides), ADMIN)
    )


def make_certification(customer_id, **overrides):
    return get_success_data(
        api_client.create_certification(
            customer_id, factories.certification_payload(**overrides), SAFETY
        )
    )


def make_active_book(payload=None):
    """Create a price book whose effective_from is already reached, so it is
    ACTIVE immediately (PRD §3.1)."""
    return get_success_data(
        api_client.create_price_book(payload or factories.full_book_payload(), ADMIN)
    )


def make_surge_window(depot_id, start_date, end_date, admission_policy, daily_pallet_cap=None):
    return get_success_data(
        api_client.create_surge_window(
            factories.surge_window_payload(
                depot_id, start_date, end_date, admission_policy, daily_pallet_cap
            ),
            ADMIN,
        )
    )


def make_slot(depot_id, date="2026-05-12", window_start="08:00", window_end="18:00", capacity_pallets=5):
    return get_success_data(
        api_client.create_delivery_slot(
            factories.slot_payload(depot_id, date, window_start, window_end, capacity_pallets),
            DISPATCHER,
        )
    )


def make_run(depot_id, run_date="2026-05-12", vehicle_label="TRUCK-1", max_pallets=5, ventilated_dry_ice_cap_lbs=0):
    return get_success_data(
        api_client.create_dispatch_run(
            factories.dispatch_run_payload(
                depot_id, run_date, vehicle_label, max_pallets, ventilated_dry_ice_cap_lbs
            ),
            DISPATCHER,
        )
    )


def make_route(customer_id, depot_id, weekday="MON", window_start="08:00", window_end="10:00", standing_lines=None):
    return get_success_data(
        api_client.create_route(
            factories.route_payload(
                customer_id, depot_id, weekday, window_start, window_end, standing_lines
            ),
            agent(customer_id),
        )
    )


# --- Order lifecycle ------------------------------------------------------------

def make_order(
    customer_id,
    depot_id,
    lines,
    channel="WILL_CALL",
    event_date=DEFAULT_EVENT_DATE,
    window_start=DEFAULT_WINDOW_START,
    window_end=DEFAULT_WINDOW_END,
):
    """Create a DRAFT/UNBILLED order (PRD §3.4)."""
    return get_success_data(
        api_client.create_order(
            factories.order_payload(
                customer_id, depot_id, lines, channel, event_date, window_start, window_end
            ),
            agent(customer_id),
        )
    )


def quote(order_id, customer_id):
    return get_success_data(api_client.quote_order(order_id, agent(customer_id)))


def reserve(order_id, customer_id, slot_id):
    return get_success_data(
        api_client.reserve_slot(order_id, {"delivery_slot_id": slot_id}, agent(customer_id))
    )


def confirm(order_id, customer_id):
    return get_success_data(api_client.confirm_order(order_id, agent(customer_id)))


def stage(order_id):
    return get_success_data(api_client.stage_order(order_id, DEPOT_MGR))


def mark_ready(order_id):
    return get_success_data(api_client.mark_ready_order(order_id, DEPOT_MGR))


def pickup(order_id, customer_id):
    return get_success_data(api_client.confirm_pickup(order_id, agent(customer_id)))


def quoted_order(customer_id, depot_id, lines, **kwargs):
    """Create + quote. Returns the QUOTED order."""
    order = make_order(customer_id, depot_id, lines, **kwargs)
    return quote(order["id"], customer_id)


def confirmed_order(customer_id, depot_id, lines, **kwargs):
    """Create + quote + confirm a will-call order. Returns CONFIRMED order."""
    order = quoted_order(customer_id, depot_id, lines, **kwargs)
    return confirm(order["id"], customer_id)


def staged_order(customer_id, depot_id, lines, **kwargs):
    """Create + quote + confirm + stage a will-call order."""
    order = confirmed_order(customer_id, depot_id, lines, **kwargs)
    return stage(order["id"])


def ready_order(customer_id, depot_id, lines, **kwargs):
    """Will-call order driven to READY_FOR_PICKUP."""
    order = staged_order(customer_id, depot_id, lines, **kwargs)
    return mark_ready(order["id"])


def picked_up_order(customer_id, depot_id, lines, **kwargs):
    """Full will-call lifecycle to PICKED_UP (PRD §3.7). Returns final order."""
    order = ready_order(customer_id, depot_id, lines, **kwargs)
    return pickup(order["id"], customer_id)


def confirmed_delivery_order(customer_id, depot_id, lines, slot_id, **kwargs):
    """DELIVERY order: create + quote + reserve-slot + confirm (PRD §3.5)."""
    order = quoted_order(customer_id, depot_id, lines, channel="DELIVERY", **kwargs)
    reserve(order["id"], customer_id, slot_id)
    return confirm(order["id"], customer_id)


def staged_delivery_order(customer_id, depot_id, lines, slot_id, **kwargs):
    """DELIVERY order driven to STAGED (assign-eligible, PRD §3.7)."""
    order = confirmed_delivery_order(customer_id, depot_id, lines, slot_id, **kwargs)
    return stage(order["id"])


# --- Holds ------------------------------------------------------------------------

def first_hold_id(order_id, headers=DEPOT_MGR):
    holds, _meta = _list(api_client.list_order_holds(order_id, headers))
    assert len(holds) >= 1, f"Expected at least one hold on order {order_id}"
    return holds[0]["id"]


# --- Invoices / payments ------------------------------------------------------------

def generate_invoice(customer_id, period_start, period_end, clerk_headers=CLERK_1):
    return get_success_data(
        api_client.generate_invoice(
            factories.invoice_generate_payload(customer_id, period_start, period_end),
            clerk_headers,
        )
    )


def issue_invoice(invoice_id, clerk_headers=CLERK_1):
    return get_success_data(api_client.issue_invoice(invoice_id, clerk_headers))


def issued_invoice(customer_id, period_start, period_end, clerk_headers=CLERK_1):
    """Generate + issue. Requires billable orders already present (PRD §3.8)."""
    invoice = generate_invoice(customer_id, period_start, period_end, clerk_headers)
    return issue_invoice(invoice["id"], clerk_headers)


def make_payment(customer_id, amount_cents, method="ACH", clerk_headers=CLERK_1):
    return get_success_data(
        api_client.create_payment(
            factories.payment_payload(customer_id, amount_cents, method), clerk_headers
        )
    )


def make_overdue_invoice(customer_id, depot_id, period_start, period_end, advance_to, clerk_headers=CLERK_1):
    """Issue an invoice, advance the logical clock past its due date, and run the
    ops checkpoint so the aging sweep moves it to OVERDUE (PRD §3.9 step 5).

    Caller must have created billable fulfilled orders first. Returns the
    OVERDUE invoice data."""
    invoice = issued_invoice(customer_id, period_start, period_end, clerk_headers)
    set_logical_clock(advance_to)
    run_ops(depot_id)
    return get_success_data(api_client.get_invoice(invoice["id"], clerk_headers))


# --- Ops checkpoint ------------------------------------------------------------------

def run_ops(depot_id):
    return get_success_data(api_client.run_ops(depot_id, ADMIN))


# --- Misc ----------------------------------------------------------------------------

def _list(response):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(response)


def get_depot(depot_id, headers=ADMIN):
    return get_success_data(api_client.get_depot(depot_id, headers))


def get_order(order_id, headers=ADMIN):
    return get_success_data(api_client.get_order(order_id, headers))


def get_customer(customer_id, headers=ADMIN):
    return get_success_data(api_client.get_customer(customer_id, headers))


def get_invoice(invoice_id, headers=CLERK_1):
    return get_success_data(api_client.get_invoice(invoice_id, headers))
