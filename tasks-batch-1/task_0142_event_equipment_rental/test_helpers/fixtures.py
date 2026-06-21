"""Composite setup helpers.

Each helper builds a slice of system state from scratch (the server is reset
before every test) using only PRD-declared endpoints, and returns the created
entities so tests can focus on the assertion under test.

All helpers use get_success_data() (lenient 2xx) so a setup failure surfaces
as a clear "Setup step failed" message rather than a confusing assertion.

Identity threading: a Customer's X-User-ID must equal the Customer entity id for
ownership-gated calls. Every helper that creates a customer then acts on that
customer's order/venue threads make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_catalog_item_payload,
    create_customer_payload,
    create_venue_payload,
    create_certificate_payload,
    create_order_payload,
    add_line_payload,
    create_crew_payload,
    create_delivery_run_payload,
    create_weather_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_rental_agent_headers,
)

AGENT = TEST_USERS["rental_agent_headers"]


# ─── Tier 0: single-entity creation ───────────────────

def create_catalog_item(**overrides) -> dict:
    """Create a CatalogItem (as RentalAgent). Returns the item."""
    resp = api_client.create_catalog_item(create_catalog_item_payload(**overrides), AGENT)
    return get_success_data(resp)


def create_customer(**overrides) -> dict:
    """Register a Customer (as RentalAgent). Returns the customer."""
    resp = api_client.create_customer(create_customer_payload(**overrides), AGENT)
    return get_success_data(resp)


def create_venue(customer_id, **overrides) -> dict:
    """Register a Venue owned by customer_id (acting as that customer). Returns venue."""
    headers = make_customer_headers(customer_id)
    resp = api_client.create_venue(create_venue_payload(customer_id, **overrides), headers)
    return get_success_data(resp)


def create_crew(**overrides) -> dict:
    """Create a delivery Crew (as RentalAgent). Returns the crew."""
    resp = api_client.create_crew(create_crew_payload(**overrides), AGENT)
    return get_success_data(resp)


def create_weather_event(**overrides) -> dict:
    """Post a WeatherEvent (as RentalAgent). Returns the event."""
    resp = api_client.create_weather_event(create_weather_event_payload(**overrides), AGENT)
    return get_success_data(resp)


def create_draft_order(customer_id, **overrides) -> dict:
    """Create a DRAFT order for customer_id (acting as that customer)."""
    headers = make_customer_headers(customer_id)
    resp = api_client.create_order(create_order_payload(customer_id, **overrides), headers)
    return get_success_data(resp)


def add_line(order_id, item_id, quantity, customer_id) -> dict:
    """Add a line to a DRAFT order (acting as the owning customer)."""
    headers = make_customer_headers(customer_id)
    resp = api_client.add_line(order_id, add_line_payload(item_id, quantity), headers)
    return get_success_data(resp)


# ─── Tier 1: certificate lifecycle ────────────────────

def submit_certificate(venue_id, customer_id, **overrides) -> dict:
    """Submit a COI for a venue (acting as the owning customer). Returns the cert."""
    headers = make_customer_headers(customer_id)
    resp = api_client.create_certificate(venue_id, create_certificate_payload(**overrides), headers)
    return get_success_data(resp)


def approve_certificate(venue_id, certificate_id) -> dict:
    """Approve a SUBMITTED COI (as RentalAgent). Returns the cert."""
    resp = api_client.approve_certificate(venue_id, certificate_id, AGENT)
    return get_success_data(resp)


def setup_venue_with_approved_coi(customer_id, coverage_start, coverage_end,
                                  zone="LOCAL", **venue_overrides):
    """Customer-owned venue + APPROVED COI covering [coverage_start, coverage_end].
    Returns (venue, certificate)."""
    venue = create_venue(customer_id, delivery_zone=zone, **venue_overrides)
    cert = submit_certificate(
        venue["id"], customer_id,
        coverage_start=coverage_start, coverage_end=coverage_end,
    )
    cert = approve_certificate(venue["id"], cert["id"])
    return venue, cert


# ─── Tier 2: order assembly + confirm ─────────────────

def setup_order_with_line(item_overrides=None, order_overrides=None, quantity=1,
                          customer_overrides=None):
    """WILL_CALL DRAFT order with one line. Returns (item, customer, order, line).

    The order is left in DRAFT; the caller confirms when ready (the line-add
    bumps the order version, so the caller reads order["version"] from the
    returned line's parent — use confirm_order helper which re-reads version).
    """
    item = create_catalog_item(**(item_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    order = create_draft_order(customer["id"], **(order_overrides or {}))
    line = add_line(order["id"], item["id"], quantity, customer["id"])
    return item, customer, order, line


def confirm_order(order_id, customer_id):
    """Read the order's current version, then confirm (acting as owning customer).
    Returns the confirmed order."""
    headers = make_customer_headers(customer_id)
    current = get_success_data(api_client.get_order(order_id, headers))
    resp = api_client.confirm_order(
        order_id, {"expected_order_version": current["version"]}, headers
    )
    return get_success_data(resp)


def setup_confirmed_will_call_order(item_overrides=None, order_overrides=None,
                                    quantity=1, customer_overrides=None):
    """WILL_CALL order confirmed (booking_status=CONFIRMED, settlement_status=
    DEPOSIT_HELD). Returns (item, customer, order_confirmed, line)."""
    item, customer, order, line = setup_order_with_line(
        item_overrides, order_overrides, quantity, customer_overrides
    )
    confirmed = confirm_order(order["id"], customer["id"])
    return item, customer, confirmed, line


def setup_delivery_order_with_line(zone="LOCAL", item_overrides=None,
                                   order_overrides=None, quantity=1,
                                   with_approved_coi=False,
                                   coverage_start="2026-08-01T00:00:00.000Z",
                                   coverage_end="2026-08-31T00:00:00.000Z"):
    """DELIVERY DRAFT order with one line + customer-owned venue.
    Optionally attach an APPROVED COI over the given coverage window.
    Returns (item, customer, venue, order, line)."""
    item = create_catalog_item(**(item_overrides or {}))
    customer = create_customer()
    if with_approved_coi:
        venue, _ = setup_venue_with_approved_coi(
            customer["id"], coverage_start, coverage_end, zone=zone
        )
    else:
        venue = create_venue(customer["id"], delivery_zone=zone)
    oo = {"fulfillment": "DELIVERY", "venue_id": venue["id"]}
    oo.update(order_overrides or {})
    order = create_draft_order(customer["id"], **oo)
    line = add_line(order["id"], item["id"], quantity, customer["id"])
    return item, customer, venue, order, line


# ─── Tier 3: delivery-run scheduling / completion ─────

def schedule_run(order_id, crew_id, leg, window_start, window_end) -> dict:
    """Schedule a DeliveryRun (as RentalAgent). Returns the run."""
    resp = api_client.create_delivery_run(
        create_delivery_run_payload(
            order_id, crew_id, leg=leg, window_start=window_start, window_end=window_end
        ),
        AGENT,
    )
    return get_success_data(resp)


def complete_run(run_id) -> dict:
    """Mark a SCHEDULED run COMPLETED via attempt(outcome=SUCCESS). Returns run."""
    resp = api_client.attempt_delivery_run(run_id, {"outcome": "SUCCESS"}, AGENT)
    return get_success_data(resp)


def fail_run(run_id) -> dict:
    """Mark a SCHEDULED run FAILED (-> ATTEMPTED). Returns run."""
    resp = api_client.attempt_delivery_run(run_id, {"outcome": "FAILED"}, AGENT)
    return get_success_data(resp)


def reschedule_run(run_id, window_start, window_end) -> dict:
    """Reschedule an ATTEMPTED run to a new window. Returns run."""
    resp = api_client.reschedule_delivery_run(
        run_id, {"window_start": window_start, "window_end": window_end}, AGENT
    )
    return get_success_data(resp)


# ─── Tier 4: order lifecycle shortcuts ────────────────

def fulfill_order(order_id) -> dict:
    """Advance a CONFIRMED order to FULFILLED (as RentalAgent). Returns order."""
    return get_success_data(api_client.fulfill_order(order_id, AGENT))


def return_order(order_id) -> dict:
    """Advance a FULFILLED order to RETURNED (as RentalAgent). Returns order."""
    return get_success_data(api_client.return_order(order_id, AGENT))


def setup_returned_will_call_order(item_overrides=None, quantity=5,
                                   order_overrides=None):
    """WILL_CALL order driven through confirm -> fulfill -> return
    (booking_status=RETURNED, settlement_status=DEPOSIT_HELD).
    Returns (item, customer, order_returned, line)."""
    item, customer, confirmed, line = setup_confirmed_will_call_order(
        item_overrides, order_overrides, quantity
    )
    fulfill_order(confirmed["id"])
    returned = return_order(confirmed["id"])
    return item, customer, returned, line


# ─── Tier 5: deposit settlement ───────────────────────

def settle_deposit(order_id, disposition, expected_order_version,
                   forfeit_amount_cents=None, reason=None) -> dict:
    """Settle the held deposit (as DepositAdjuster). Returns the order."""
    payload = {
        "disposition": disposition,
        "expected_order_version": expected_order_version,
    }
    if forfeit_amount_cents is not None:
        payload["forfeit_amount_cents"] = forfeit_amount_cents
    if reason is not None:
        payload["reason"] = reason
    resp = api_client.settle_deposit(order_id, payload, TEST_USERS["deposit_adjuster_headers"])
    return get_success_data(resp)


def get_order_as_agent(order_id) -> dict:
    """Read an order as RentalAgent (no ownership gate)."""
    return get_success_data(api_client.get_order(order_id, AGENT))


def get_ledger_entries(order_id) -> list:
    """Read the deposit ledger entries for an order (as RentalAgent)."""
    body = api_client.get_deposit_ledger(order_id, AGENT)
    data = get_success_data(body)
    return data
