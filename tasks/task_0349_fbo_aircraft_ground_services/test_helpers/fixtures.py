"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Every test runs against a freshly re-launched, empty server, so each fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.

Role usage mirrors the PRD §2.1 RBAC matrix:
  - BillingClerk creates operators and fuel contracts.
  - OpsDispatcher creates aircraft, spots, visits, parking assignments, slots; runs visit transitions.
  - FuelTech creates / dispatches / completes fuel orders and posts into-plane tickets.
  - LineManager voids invoices.
The Operator role is entity_backed; ownership-gated Operator calls use make_operator_headers.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_operator_payload,
    create_aircraft_payload,
    create_fuel_contract_payload,
    create_service_visit_payload,
    create_parking_spot_payload,
    create_parking_assignment_payload,
    create_fuel_order_payload,
    create_into_plane_ticket_payload,
    create_ramp_service_payload,
    create_deice_service_payload,
    create_ramp_slot_payload,
    occupy_payload,
)
from .test_users import TEST_USERS

OPS = TEST_USERS["ops_dispatcher_headers"]
FUEL = TEST_USERS["fuel_tech_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
LINE = TEST_USERS["line_manager_headers"]


# ─── Tier 0: primitive creators ───────────────────────────────────────

def create_operator(**overrides) -> dict:
    """Create an ACTIVE operator. Returns the operator record."""
    return get_success_data(api_client.create_operator(create_operator_payload(**overrides), BILLING))


def create_aircraft(operator_id, **overrides) -> dict:
    """Create an aircraft under an operator (default MID JET_A, mtow 30000)."""
    return get_success_data(
        api_client.create_aircraft(create_aircraft_payload(operator_id, **overrides), OPS)
    )


def create_fuel_contract(operator_id, **overrides) -> dict:
    """Create an ACTIVE fuel contract (default JET_A base 520, tankering 30)."""
    return get_success_data(
        api_client.create_fuel_contract(create_fuel_contract_payload(operator_id, **overrides), BILLING)
    )


def create_parking_spot(**overrides) -> dict:
    """Create an AVAILABLE parking spot (default HEAVY TIE_DOWN)."""
    return get_success_data(api_client.create_parking_spot(create_parking_spot_payload(**overrides), OPS))


def create_visit(operator_id, aircraft_id, **overrides) -> dict:
    """Create a SCHEDULED service visit."""
    return get_success_data(
        api_client.create_service_visit(
            create_service_visit_payload(operator_id, aircraft_id, **overrides), OPS
        )
    )


# ─── Tier 1: operator + aircraft + contract bundle ────────────────────

def setup_operator_aircraft_contract(aircraft_overrides=None, contract_overrides=None):
    """ACTIVE operator + one aircraft + one ACTIVE contract.

    Returns (operator, aircraft, contract). The most common base for fuel tests.
    """
    operator = create_operator()
    aircraft = create_aircraft(operator["id"], **(aircraft_overrides or {}))
    contract = create_fuel_contract(operator["id"], **(contract_overrides or {}))
    return operator, aircraft, contract


# ─── Tier 2: visits in various states ─────────────────────────────────

def setup_on_ground_visit(operator_id, aircraft_id, visit_overrides=None) -> dict:
    """Create a visit and move it SCHEDULED → ON_GROUND. Returns the ON_GROUND visit."""
    visit = create_visit(operator_id, aircraft_id, **(visit_overrides or {}))
    api_client.arrive_service_visit(visit["id"], OPS)
    return get_success_data(api_client.get_service_visit(visit["id"], OPS))


def setup_servicing_visit(operator_id, aircraft_id, spot_overrides=None, visit_overrides=None):
    """Create a visit, arrive, occupy a spot, and start servicing → SERVICING.

    Returns (visit, spot, assignment). Occupy uses the freshly captured assignment version.
    """
    visit = create_visit(operator_id, aircraft_id, **(visit_overrides or {}))
    api_client.arrive_service_visit(visit["id"], OPS)
    spot = create_parking_spot(**(spot_overrides or {}))
    assignment = get_success_data(
        api_client.create_parking_assignment(
            create_parking_assignment_payload(visit["id"], spot["id"]), OPS
        )
    )
    occupied = get_success_data(
        api_client.occupy_parking_assignment(
            assignment["id"], occupy_payload(assignment["version"]), OPS
        )
    )
    api_client.start_servicing_service_visit(visit["id"], OPS)
    visit = get_success_data(api_client.get_service_visit(visit["id"], OPS))
    return visit, spot, occupied


# ─── Tier 3: fuel-order lifecycle shortcuts ───────────────────────────

def create_requested_fuel_order(visit_id, aircraft_id, contract_id, **order_overrides) -> dict:
    """Create a REQUESTED fuel order. Returns the order record."""
    return get_success_data(
        api_client.create_fuel_order(
            create_fuel_order_payload(visit_id, aircraft_id, contract_id, **order_overrides), FUEL
        )
    )


def create_dispatched_fuel_order(visit_id, aircraft_id, contract_id, **order_overrides) -> dict:
    """Create + dispatch a fuel order → DISPATCHED (prices it). Parent visit must be ON_GROUND/SERVICING."""
    order = create_requested_fuel_order(visit_id, aircraft_id, contract_id, **order_overrides)
    return get_success_data(api_client.dispatch_fuel_order(order["id"], FUEL))


def create_fueled_fuel_order(visit_id, aircraft_id, contract_id, **order_overrides) -> dict:
    """Create + dispatch + complete-fueling → FUELED (ledger-sync on JET_A non-tankering)."""
    order = create_dispatched_fuel_order(visit_id, aircraft_id, contract_id, **order_overrides)
    return get_success_data(api_client.complete_fueling_fuel_order(order["id"], FUEL))


# ─── Tier 4: into-plane reconciliation helpers ────────────────────────

def post_into_plane_ticket(fuel_order_id, delivered_gallons) -> dict:
    """Post an into-plane ticket against a FUELED order. Returns the ticket record."""
    return get_success_data(
        api_client.create_into_plane_ticket(
            create_into_plane_ticket_payload(fuel_order_id, delivered_gallons), FUEL
        )
    )


# ─── Tier 5: departed visit with an issued invoice ────────────────────

def setup_departed_visit_with_invoice(order_overrides=None, ticket_delivered=None,
                                      contract_overrides=None, aircraft_overrides=None,
                                      visit_overrides=None):
    """Full single-fuel-line lifecycle through DEPARTED with an ISSUED Invoice.

    Sequence: operator → aircraft → contract → visit → arrive → occupy a spot →
    start-servicing → release the spot → fuel order (dispatch → complete-fueling) →
    [optional into-plane ticket] → mark-ready → depart.

    The PRD gates mark-ready (SERVICING → READY_FOR_DEPARTURE) on the visit being in
    SERVICING (PRD §3.3), which in turn requires the visit to have passed through an
    OCCUPIED parking assignment (start-servicing precondition). To keep the resulting
    invoice a pure single fuel line, the spot is RELEASED right after start-servicing
    so no OCCUPIED assignment contributes a parking line at depart (PRD §3.7 sums only
    OCCUPIED assignment fees).

    Returns (operator, aircraft, contract, visit, order, invoice).
    """
    operator, aircraft, contract = setup_operator_aircraft_contract(
        aircraft_overrides=aircraft_overrides, contract_overrides=contract_overrides
    )
    # Build a SERVICING visit (arrive → occupy → start-servicing), then release the
    # occupation so the departed invoice carries only the fuel line.
    visit, _spot, assignment = setup_servicing_visit(
        operator["id"], aircraft["id"], visit_overrides=visit_overrides
    )
    get_success_data(api_client.release_parking_assignment(assignment["id"], OPS))
    order = create_fueled_fuel_order(visit["id"], aircraft["id"], contract["id"], **(order_overrides or {}))
    if ticket_delivered is not None:
        post_into_plane_ticket(order["id"], ticket_delivered)
    api_client.mark_ready_service_visit(visit["id"], OPS)
    api_client.depart_service_visit(visit["id"], OPS)
    invoice = _get_invoice_for_visit(visit["id"])
    visit = get_success_data(api_client.get_service_visit(visit["id"], OPS))
    order = get_success_data(api_client.get_fuel_order(order["id"], FUEL))
    operator = get_success_data(api_client.get_operator(operator["id"], BILLING))
    return operator, aircraft, contract, visit, order, invoice


def _get_invoice_for_visit(visit_id) -> dict:
    """Read the single invoice for a visit via GET /invoices?service_visit_id=."""
    data, _ = _list_invoices_for_visit(visit_id)
    assert data, f"Setup failed: no invoice found for visit {visit_id}"
    return data[0]


def _list_invoices_for_visit(visit_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(api_client.list_invoices(BILLING, params={"service_visit_id": visit_id}))


def get_invoice_for_visit(visit_id) -> dict:
    """Public accessor: read the invoice generated for a departed visit."""
    return _get_invoice_for_visit(visit_id)


# ─── Tier 6: ramp-slot lifecycle ──────────────────────────────────────

def setup_approved_slot(operator_id, aircraft_id, pad_overrides=None, slot_overrides=None,
                        visit_overrides=None):
    """Create a SCHEDULED visit + RAMP pad + REQUESTED slot, then approve → APPROVED.

    Returns (visit, pad, slot). Slot defaults to window [10:00, 11:00) on 2026-06-14.
    """
    visit = create_visit(operator_id, aircraft_id, **(visit_overrides or {}))
    pad = create_parking_spot(**{"label": "PAD-1", "spot_type": "RAMP", "max_weight_class": "HEAVY",
                                 **(pad_overrides or {})})
    slot_defaults = {
        "window_start_utc": "2026-06-14T10:00:00.000Z",
        "window_end_utc": "2026-06-14T11:00:00.000Z",
    }
    slot_defaults.update(slot_overrides or {})
    slot = get_success_data(
        api_client.create_ramp_slot(
            create_ramp_slot_payload(visit["id"], pad["id"], **slot_defaults), OPS
        )
    )
    approved = get_success_data(api_client.approve_ramp_slot(slot["id"], OPS))
    return visit, pad, approved


def setup_revoked_slot(operator_id, aircraft_id, **overrides):
    """Approved slot then revoked → REVOKED. Returns (visit, pad, slot)."""
    visit, pad, slot = setup_approved_slot(operator_id, aircraft_id, **overrides)
    revoked = get_success_data(api_client.revoke_ramp_slot(slot["id"], OPS))
    return visit, pad, revoked


# ─── Tier 7: ramp service in progress (DE_ICE or flat) ────────────────

def setup_in_progress_ramp_service(operator_id, aircraft_id, service_type="GPU",
                                   deice_kwargs=None, spot_overrides=None, visit_overrides=None):
    """SERVICING visit + one IN_PROGRESS ramp service.

    Returns (visit, spot, service). For DE_ICE supply deice_kwargs with the fluid fields.
    """
    visit, spot, _assignment = setup_servicing_visit(
        operator_id, aircraft_id, spot_overrides=spot_overrides, visit_overrides=visit_overrides
    )
    if service_type == "DE_ICE":
        payload = create_deice_service_payload(visit["id"], **(deice_kwargs or {}))
    else:
        payload = create_ramp_service_payload(visit["id"], service_type=service_type)
    service = get_success_data(api_client.create_ramp_service(payload, OPS))
    service = get_success_data(api_client.start_ramp_service(service["id"], LINE))
    visit = get_success_data(api_client.get_service_visit(visit["id"], OPS))
    return visit, spot, service
