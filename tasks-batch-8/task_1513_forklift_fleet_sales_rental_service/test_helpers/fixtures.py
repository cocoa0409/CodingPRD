"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build complete precondition chains —
customer onboarding, unit registration, quote lifecycle, rental lifecycle,
lease-to-settlement, reconditioning-to-listed — out of PRD-declared endpoints
only.

Identity threading: Technician is entity-backed, so service-call resolve calls
use make_technician_headers(technician["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_certification_payload,
    create_customer_payload,
    create_dispatch_payload,
    create_lease_contract_payload,
    create_lease_inspection_payload,
    create_operator_payload,
    create_quote_line_payload,
    create_quote_payload,
    create_reconditioning_order_payload,
    create_rental_contract_payload,
    create_service_call_payload,
    create_technician_payload,
    create_unit_payload,
)
from .test_users import TEST_USERS, make_technician_headers

FLEET = TEST_USERS["fleet_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]
RENTAL = TEST_USERS["rental_coordinator_headers"]
DISPATCH = TEST_USERS["service_dispatcher_headers"]
REGISTRAR = TEST_USERS["training_registrar_headers"]
LEASE = TEST_USERS["lease_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 0/1: single-entity creators
# ---------------------------------------------------------------------------

def make_customer(**overrides):
    """Create a customer. Defaults: credit_limit 10000000, discount 0."""
    resp = api_client.create_customer(create_customer_payload(**overrides), SALES)
    return get_success_data(resp)


def make_unit(**overrides):
    """Create a unit. Defaults: LP / RENTAL_FLEET, rates 15000/70000/210000,
    pm_interval 500. Fresh unit starts AVAILABLE / PM_OK at version 1."""
    resp = api_client.create_unit(create_unit_payload(**overrides), FLEET)
    return get_success_data(resp)


def make_technician(van_stock=None, **overrides):
    """Create an ACTIVE technician with the given initial van stock."""
    if van_stock is not None:
        overrides["van_stock"] = van_stock
    resp = api_client.create_technician(create_technician_payload(**overrides),
                                        DISPATCH)
    return get_success_data(resp)


def make_operator(customer_id, **overrides):
    resp = api_client.create_operator(create_operator_payload(customer_id, **overrides),
                                      REGISTRAR)
    return get_success_data(resp)


def make_certified_operator(customer_id, expires_at="2027-01-01T00:00:00Z",
                            cert_class="SIT_DOWN"):
    """Operator holding one ACTIVE certification. Returns (operator, cert)."""
    operator = make_operator(customer_id)
    cert = get_success_data(api_client.issue_certification(
        operator["id"],
        create_certification_payload(cert_class=cert_class, expires_at=expires_at),
        REGISTRAR))
    return operator, cert


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, SALES))


def get_unit(unit_id):
    return get_success_data(api_client.get_unit(unit_id, FLEET))


def get_quote(quote_id):
    return get_success_data(api_client.get_quote(quote_id, SALES))


def get_rental_contract(contract_id):
    return get_success_data(api_client.get_rental_contract(contract_id, RENTAL))


def get_service_call(call_id):
    return get_success_data(api_client.get_service_call(call_id, DISPATCH))


def get_technician(technician_id):
    return get_success_data(api_client.get_technician(technician_id, DISPATCH))


def get_lease_contract(lease_id):
    return get_success_data(api_client.get_lease_contract(lease_id, LEASE))


def set_clock(to_iso8601):
    """Advance the logical clock (FleetManager-only, PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, FLEET))


# ---------------------------------------------------------------------------
# Tier 2: quotes
# ---------------------------------------------------------------------------

def make_draft_quote(customer_id, lines=(), kind="NEW_CONFIG", unit_id=None,
                     valid_until="2026-09-01"):
    """DRAFT quote with the given (description, qty, unit_price_cents) lines."""
    payload = create_quote_payload(customer_id, kind=kind, valid_until=valid_until)
    if unit_id is not None:
        payload["unit_id"] = unit_id
    quote = get_success_data(api_client.create_quote(payload, SALES))
    for description, qty, unit_price_cents in lines:
        get_success_data(api_client.create_quote_line(
            quote["id"],
            create_quote_line_payload(description=description, qty=qty,
                                      unit_price_cents=unit_price_cents),
            SALES))
    return get_quote(quote["id"])


def make_submitted_quote(customer_id, lines=(("Line", 1, 5000),), **kwargs):
    """Quote walked DRAFT -> SUBMITTED."""
    quote = make_draft_quote(customer_id, lines=lines, **kwargs)
    return get_success_data(api_client.submit_quote(quote["id"], SALES))


# ---------------------------------------------------------------------------
# Tier 3: rental lifecycle
# ---------------------------------------------------------------------------

def make_rental_contract(customer_id, unit_id, start_date="2026-08-01",
                         end_date="2026-08-03"):
    """RESERVED rental contract. Reads the unit fresh to supply a current
    expected_unit_version (OCC, PRD §2.8)."""
    unit = get_unit(unit_id)
    payload = create_rental_contract_payload(
        unit_id, customer_id, unit["version"],
        start_date=start_date, end_date=end_date)
    contract = get_success_data(api_client.create_rental_contract(payload, RENTAL))
    return contract


def make_checked_out_contract(customer_id=None, unit=None, start_date="2026-08-01",
                              end_date="2026-08-03", customer_overrides=None,
                              unit_overrides=None):
    """Customer + unit + contract walked to ON_RENT.
    Returns (customer, unit_after_checkout, contract)."""
    if customer_id is None:
        customer_id = make_customer(**(customer_overrides or {}))["id"]
    if unit is None:
        unit = make_unit(**(unit_overrides or {}))
    contract = make_rental_contract(customer_id, unit["id"],
                                    start_date=start_date, end_date=end_date)
    contract = get_success_data(
        api_client.checkout_rental_contract(contract["id"], RENTAL))
    return get_customer(customer_id), get_unit(unit["id"]), contract


def make_returned_contract(return_date, return_hours, **kwargs):
    """Contract walked RESERVED -> ON_RENT -> RETURNED.
    Returns (customer, unit, contract)."""
    customer, unit, contract = make_checked_out_contract(**kwargs)
    contract = get_success_data(api_client.return_rental_contract(
        contract["id"], {"return_date": return_date, "return_hours": return_hours},
        RENTAL))
    return get_customer(customer["id"]), get_unit(unit["id"]), contract


# ---------------------------------------------------------------------------
# Tier 3: service calls
# ---------------------------------------------------------------------------

def make_service_call(unit_id, customer_id, required_parts=None, operator_id=None,
                      call_type="BREAKDOWN", priority="STANDARD"):
    """OPEN service call."""
    payload = create_service_call_payload(
        unit_id, customer_id, call_type=call_type, priority=priority,
        required_parts=required_parts if required_parts is not None else [])
    if operator_id is not None:
        payload["operator_id"] = operator_id
    return get_success_data(api_client.create_service_call(payload, DISPATCH))


def make_dispatched_call(unit_id, customer_id, technician_id,
                         scheduled_start="2026-08-02T10:00:00Z",
                         scheduled_end="2026-08-02T11:00:00Z", **call_kwargs):
    """Service call walked OPEN -> DISPATCHED. Returns the call."""
    call = make_service_call(unit_id, customer_id, **call_kwargs)
    return get_success_data(api_client.dispatch_service_call(
        call["id"],
        create_dispatch_payload(technician_id, scheduled_start=scheduled_start,
                                scheduled_end=scheduled_end),
        DISPATCH))


def resolve_call(call_id, technician_id, used_parts=None):
    """Resolve as the assigned technician (identity threading, PRD §2.1)."""
    return get_success_data(api_client.resolve_service_call(
        call_id, {"used_parts": used_parts or []},
        make_technician_headers(technician_id)))


# ---------------------------------------------------------------------------
# Tier 4/5: lease lifecycle through settlement
# ---------------------------------------------------------------------------

def make_lease(customer_id, unit_id, **overrides):
    """ACTIVE lease; the unit moves AVAILABLE -> ON_LEASE."""
    return get_success_data(api_client.create_lease_contract(
        create_lease_contract_payload(unit_id, customer_id, **overrides), LEASE))


def make_returned_lease(customer_id=None, unit=None, return_date="2026-08-01",
                        customer_overrides=None, unit_overrides=None,
                        lease_overrides=None):
    """Lease walked ACTIVE -> RETURNED (unit back AVAILABLE, disposition
    USED_SALE). Returns (customer, unit, lease)."""
    if customer_id is None:
        customer_id = make_customer(**(customer_overrides or {}))["id"]
    if unit is None:
        unit = make_unit(disposition="NEW_SALE", **(unit_overrides or {}))
    lease = make_lease(customer_id, unit["id"], **(lease_overrides or {}))
    lease = get_success_data(api_client.return_lease_contract(
        lease["id"], {"return_date": return_date}, LEASE))
    return get_customer(customer_id), get_unit(unit["id"]), lease


def make_lease_with_approved_inspection(inspection_overrides=None, **kwargs):
    """RETURNED lease plus one APPROVED inspection.
    Returns (customer, unit, lease, inspection)."""
    customer, unit, lease = make_returned_lease(**kwargs)
    inspection = get_success_data(api_client.create_lease_inspection(
        lease["id"],
        create_lease_inspection_payload(**(inspection_overrides or {})),
        LEASE))
    inspection = get_success_data(
        api_client.approve_inspection(inspection["id"], LEASE))
    return customer, unit, get_lease_contract(lease["id"]), inspection


def make_settled_lease(**kwargs):
    """Lease walked all the way to SETTLED.
    Returns (customer, unit, lease, inspection)."""
    customer, unit, lease, inspection = make_lease_with_approved_inspection(**kwargs)
    lease = get_success_data(api_client.settle_lease_contract(lease["id"], LEASE))
    return get_customer(customer["id"]), get_unit(unit["id"]), lease, inspection


# ---------------------------------------------------------------------------
# Tier 5: reconditioning / resale pipeline
# ---------------------------------------------------------------------------

def make_listed_unit(listing_price_cents=2500000, unit_overrides=None):
    """USED_SALE unit walked through reconditioning with QC PASS -> LISTED.
    Returns (unit, reconditioning_order)."""
    unit = make_unit(disposition="USED_SALE", **(unit_overrides or {}))
    order = get_success_data(api_client.create_reconditioning_order(
        create_reconditioning_order_payload(unit["id"], notes="full recon"), FLEET))
    order = get_success_data(api_client.complete_reconditioning_order(
        order["id"], {"qc_result": "PASS",
                      "listing_price_cents": listing_price_cents}, FLEET))
    return get_unit(unit["id"]), order


def make_sold_unit(listing_price_cents=2500000):
    """LISTED unit sold via a USED_UNIT_SALE quote -> SOLD.
    Returns (customer, unit, quote)."""
    customer = make_customer()
    make_certified_operator(customer["id"])
    unit, _order = make_listed_unit(listing_price_cents=listing_price_cents)
    quote = make_submitted_quote(
        customer["id"], lines=(("Used truck as-listed", 1, listing_price_cents),),
        kind="USED_UNIT_SALE", unit_id=unit["id"])
    quote = get_success_data(api_client.accept_quote(quote["id"], SALES))
    return get_customer(customer["id"]), get_unit(unit["id"]), quote
