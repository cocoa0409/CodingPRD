"""Composite setup helpers for multi-step test prerequisites.

Most testable claims require the system to be in a state that takes 5-15 API
calls to reach (contract -> bid item -> activate -> work package -> mobilize ->
crew/equipment -> assignment -> in-progress -> clock -> activate assignment).
These helpers encapsulate those chains so tests focus on assertions.

All helpers use get_success_data() so a broken setup step fails loudly with a
clear "Setup step failed" message rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FIELD_CLOCK, WORK_START, WORK_END
from .factories import (
    create_assignment_payload,
    create_bid_item_payload,
    create_contract_payload,
    create_crew_payload,
    create_equipment_payload,
    create_inspection_payload,
    create_invoice_payload,
    create_material_issue_payload,
    create_outage_request_payload,
    create_production_entry_payload,
    create_safety_event_payload,
    create_stock_item_payload,
    create_storm_activation_payload,
    create_work_package_payload,
)
from .test_users import TEST_USERS

PM = TEST_USERS["contractor_pm_headers"]
FOREMAN = TEST_USERS["foreman_headers"]
INSPECTOR = TEST_USERS["utility_inspector_headers"]
DISPATCHER = TEST_USERS["utility_dispatcher_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


# --- Tier 1: contract + bid-item schedule ---

def create_draft_contract(**contract_overrides):
    """Create a contract in DRAFT. Returns the contract."""
    return get_success_data(
        api_client.create_contract(create_contract_payload(**contract_overrides), PM))


def setup_active_contract(contract_overrides=None, bid_item_overrides=None,
                          extra_bid_items=None):
    """DRAFT contract + one bid item (plus any extras) + transition to ACTIVE.

    Returns (contract, bid_items) where bid_items[0] is the primary item.
    """
    contract = create_draft_contract(**(contract_overrides or {}))
    bid_items = [get_success_data(api_client.create_bid_item(
        contract["id"], create_bid_item_payload(**(bid_item_overrides or {})), PM))]
    for extra in (extra_bid_items or []):
        bid_items.append(get_success_data(api_client.create_bid_item(
            contract["id"], create_bid_item_payload(**extra), PM)))
    contract = get_success_data(
        api_client.transition_contract(contract["id"], {"to": "ACTIVE"}, PM))
    return contract, bid_items


# --- Tier 2: work package + resources ---

def setup_mobilized_scenario(requires_outage=False, contract_overrides=None,
                             bid_item_overrides=None, wp_overrides=None,
                             crew_overrides=None, equipment_overrides=None):
    """ACTIVE contract + one bid item + MOBILIZED work package + crew + equipment.

    Returns dict(contract, bid_item, work_package, crew, equipment).
    """
    contract, bid_items = setup_active_contract(contract_overrides, bid_item_overrides)
    wp_payload = {"requires_outage": requires_outage}
    wp_payload.update(wp_overrides or {})
    work_package = get_success_data(api_client.create_work_package(
        contract["id"], create_work_package_payload(**wp_payload), PM))
    work_package = get_success_data(api_client.transition_work_package(
        work_package["id"], {"to": "MOBILIZED"}, PM))
    crew = get_success_data(api_client.create_crew(
        create_crew_payload(**(crew_overrides or {})), PM))
    equipment = get_success_data(api_client.create_equipment(
        create_equipment_payload(**(equipment_overrides or {})), PM))
    return {
        "contract": contract,
        "bid_item": bid_items[0],
        "work_package": work_package,
        "crew": crew,
        "equipment": equipment,
    }


def add_assignment(scenario, start_date=WORK_START, end_date=WORK_END,
                   crew=None, equipment=None):
    """Create a PLANNED assignment on the scenario's work package."""
    return get_success_data(api_client.create_assignment(
        scenario["work_package"]["id"],
        create_assignment_payload(
            (crew or scenario["crew"])["id"],
            (equipment or scenario["equipment"])["id"],
            start_date=start_date, end_date=end_date),
        FOREMAN))


# --- Tier 3: field scenario in IN_PROGRESS with an ACTIVE assignment ---

def setup_field_scenario(requires_outage=False, activate=True, clock=FIELD_CLOCK,
                         start_date=WORK_START, end_date=WORK_END, **kwargs):
    """Full field setup: ACTIVE contract + bid item + IN_PROGRESS work package +
    crew + equipment + assignment.

    With activate=True (default) the logical clock is set to `clock` and the
    assignment is transitioned to ACTIVE. The returned dict carries every
    entity; scenario["assignment"] holds the post-activation version.
    """
    scenario = setup_mobilized_scenario(requires_outage=requires_outage, **kwargs)
    scenario["assignment"] = add_assignment(scenario, start_date, end_date)
    scenario["work_package"] = get_success_data(api_client.transition_work_package(
        scenario["work_package"]["id"], {"to": "IN_PROGRESS"}, PM))
    if activate:
        set_logical_clock(clock)
        scenario["assignment"] = get_success_data(api_client.transition_assignment(
            scenario["assignment"]["id"], {"to": "ACTIVE"}, FOREMAN))
    return scenario


def set_logical_clock(to_iso8601):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PM))


# --- Tier 3 helpers: production, inspection, invoices (OCC-aware) ---

def fresh_assignment_version(assignment_id):
    """Current Assignment.version (needed for the production-report OCC field)."""
    return get_success_data(api_client.get_assignment(assignment_id, FOREMAN))["version"]


def fresh_work_package_version(work_package_id):
    """Current WorkPackage.version (needed for the invoice-create OCC field)."""
    return get_success_data(api_client.get_work_package(work_package_id, PM))["version"]


def report_production(assignment_id, bid_item_id, work_date, quantity_reported):
    """Post a production entry using the assignment's freshly read version."""
    version = fresh_assignment_version(assignment_id)
    return get_success_data(api_client.create_production_entry(
        assignment_id,
        create_production_entry_payload(bid_item_id, work_date,
                                        quantity_reported, version),
        FOREMAN))


def schedule_inspection(work_package_id, production_entry_id,
                        standard_code="UTIL-OH-1.0"):
    """Schedule a SCHEDULED inspection on a production entry."""
    return get_success_data(api_client.create_inspection(
        work_package_id,
        create_inspection_payload(production_entry_id, standard_code),
        INSPECTOR))


def submit_inspection_result(inspection_id, result):
    """Submit PASS/FAIL on a scheduled inspection. Returns the inspection."""
    return get_success_data(
        api_client.submit_inspection(inspection_id, {"result": result}, INSPECTOR))


def inspect_entry(work_package_id, production_entry_id, result,
                  standard_code="UTIL-OH-1.0"):
    """Schedule an inspection on the entry and submit the result."""
    inspection = schedule_inspection(work_package_id, production_entry_id,
                                     standard_code)
    return submit_inspection_result(inspection["id"], result)


def accept_entry(work_package_id, production_entry_id):
    """Drive a production entry to ACCEPTED via a passed inspection."""
    return inspect_entry(work_package_id, production_entry_id, "PASS")


def fail_entry(work_package_id, production_entry_id):
    """Drive a production entry to REWORK_REQUIRED via a failed inspection."""
    return inspect_entry(work_package_id, production_entry_id, "FAIL")


def create_draft_invoice(work_package_id, period_start, period_end):
    """Create a DRAFT invoice using the work package's freshly read version."""
    version = fresh_work_package_version(work_package_id)
    return get_success_data(api_client.create_invoice(
        work_package_id,
        create_invoice_payload(period_start, period_end, version),
        PM))


def transition_invoice_to(invoice_id, to, headers):
    """Transition an invoice, asserting success. Returns the invoice."""
    return get_success_data(api_client.transition_invoice(invoice_id, {"to": to}, headers))


# --- Tier 4: stock ---

def setup_stock_item(contract_id, initial_on_hand=0, **overrides):
    """Register a stock item under the contract. Returns the stock item."""
    return get_success_data(api_client.create_stock_item(
        contract_id,
        create_stock_item_payload(initial_on_hand=initial_on_hand, **overrides),
        DISPATCHER))


def receive_stock(stock_item_id, quantity):
    """Record a receipt of `quantity` against the stock item."""
    return get_success_data(api_client.create_stock_receipt(
        stock_item_id, {"quantity": quantity}, DISPATCHER))


def issue_material(work_package_id, stock_item_id, quantity_issued):
    """Issue material from stock to the work package. Returns the issue (OPEN)."""
    return get_success_data(api_client.create_material_issue(
        work_package_id,
        create_material_issue_payload(stock_item_id, quantity_issued),
        FOREMAN))


# --- Tier 4: storm duty ---

def setup_storm_activation(contract_id, crew_id, kind="STANDBY",
                           activation_date="2026-08-05"):
    """Place a crew on storm duty. Returns the ACTIVE activation."""
    return get_success_data(api_client.create_storm_activation(
        contract_id,
        create_storm_activation_payload(crew_id, kind=kind,
                                        activation_date=activation_date),
        DISPATCHER))


# --- Tier 4: outages ---

def request_outage(work_package_id, circuit_id, window_start, window_end):
    """Request an outage window. Returns the REQUESTED outage."""
    return get_success_data(api_client.create_outage_request(
        work_package_id,
        create_outage_request_payload(circuit_id, window_start, window_end),
        PM))


def approve_outage(outage_request_id):
    """Approve a REQUESTED/CHANGE_REQUESTED outage. Returns the outage."""
    return get_success_data(api_client.decide_outage_request(
        outage_request_id, {"decision": "APPROVED"}, DISPATCHER))


def setup_approved_outage(work_package_id, circuit_id, window_start, window_end):
    """Request + approve an outage window. Returns the APPROVED outage."""
    outage = request_outage(work_package_id, circuit_id, window_start, window_end)
    return approve_outage(outage["id"])


# --- Tier 5: suspension ---

def suspend_contract_via_incident(scenario, severity="FATAL", crew_id=None):
    """Log a serious INCIDENT on the scenario's work package, suspending the
    contract per PRD §2.10. Returns the created safety event."""
    payload = create_safety_event_payload(
        kind="INCIDENT", severity=severity,
        description="Contact with energized conductor")
    if crew_id:
        payload["crew_id"] = crew_id
    return get_success_data(api_client.create_safety_event(
        scenario["work_package"]["id"], payload, SAFETY))
