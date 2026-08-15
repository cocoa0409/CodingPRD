"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a fresh server
using only PRD-declared endpoints, and uses get_success_data() so a setup
failure surfaces as a clear "Setup step failed" message. Helpers that hit
OCC-guarded writes (line add, confirm) re-read the contract for the live
version first, mirroring the client discipline of PRD §2.7.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_accessory_kit_payload,
    create_contract_payload,
    create_customer_payload,
    create_equipment_line_payload,
    create_equipment_unit_payload,
    create_incident_payload,
    create_kit_line_payload,
    create_permit_payload,
    create_service_visit_payload,
    create_site_payload,
    create_telemetry_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_claims_assessor_headers,
    make_customer_headers,
    make_depot_manager_headers,
    make_field_technician_headers,
)

SALES = TEST_USERS["sales_engineer_headers"]
DEPOT = TEST_USERS["depot_manager_headers"]
DISPATCH = TEST_USERS["fleet_dispatcher_headers"]
CLAIMS = TEST_USERS["claims_assessor_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
TECH = TEST_USERS["field_technician_headers"]


# ─── Tier 0: single-resource creation ────────────────────

def create_customer(**overrides) -> dict:
    res = api_client.create_customer(create_customer_payload(**overrides), SALES)
    return get_success_data(res, 201)


def create_site(customer_id, **overrides) -> dict:
    res = api_client.create_site(create_site_payload(customer_id, **overrides), SALES)
    return get_success_data(res, 201)


def create_equipment_unit(**overrides) -> dict:
    res = api_client.create_equipment_unit(create_equipment_unit_payload(**overrides), DEPOT)
    return get_success_data(res, 201)


def create_accessory_kit(**overrides) -> dict:
    res = api_client.create_accessory_kit(create_accessory_kit_payload(**overrides), DEPOT)
    return get_success_data(res, 201)


def create_contract(customer_id, site_id, **overrides) -> dict:
    res = api_client.create_contract(
        create_contract_payload(customer_id, site_id, **overrides), SALES
    )
    return get_success_data(res, 201)


def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (PRD §2.5)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(res, 200)


# ─── Tier 1: contract state progression ──────────────────

def get_contract(contract_id) -> dict:
    return get_success_data(api_client.get_contract(contract_id, SALES), 200)


def run_size_load(contract_id, sizing_method="NAMEPLATE_SUM") -> dict:
    res = api_client.size_load(contract_id, {"sizing_method": sizing_method}, SALES)
    return get_success_data(res, 200)


def add_equipment_line(contract_id, unit_id) -> dict:
    """OCC-guarded line add: re-reads the contract for the live version."""
    version = get_contract(contract_id)["version"]
    res = api_client.add_line(
        contract_id, create_equipment_line_payload(unit_id, version), SALES
    )
    return get_success_data(res, 201)


def add_kit_line(contract_id, kit_id, quantity=1) -> dict:
    version = get_contract(contract_id)["version"]
    res = api_client.add_line(
        contract_id, create_kit_line_payload(kit_id, version, quantity), SALES
    )
    return get_success_data(res, 201)


def quote_contract(contract_id) -> dict:
    return get_success_data(api_client.quote_contract(contract_id, SALES), 200)


def revise_contract(contract_id) -> dict:
    return get_success_data(api_client.revise_contract(contract_id, SALES), 200)


def confirm_contract(contract_id, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = get_contract(contract_id)["version"]
    res = api_client.confirm_contract(
        contract_id, {"expected_rental_contract_version": expected_version}, SALES
    )
    return get_success_data(res, 200)


def cancel_contract(contract_id, headers=None) -> dict:
    return get_success_data(
        api_client.cancel_contract(contract_id, headers or SALES), 200
    )


def mobilize_contract(contract_id) -> dict:
    return get_success_data(api_client.mobilize_contract(contract_id, DEPOT), 200)


def start_rental(contract_id) -> dict:
    return get_success_data(api_client.start_rental(contract_id, DEPOT), 200)


def off_hire_contract(contract_id, headers=None) -> dict:
    return get_success_data(
        api_client.off_hire_contract(contract_id, headers or SALES), 200
    )


def close_contract(contract_id) -> dict:
    return get_success_data(api_client.close_contract(contract_id, SALES), 200)


def get_unit(unit_id) -> dict:
    return get_success_data(api_client.get_equipment_unit(unit_id, DEPOT), 200)


def get_site(site_id) -> dict:
    return get_success_data(api_client.get_site(site_id, DEPOT), 200)


def get_line(line_id) -> dict:
    return get_success_data(api_client.get_rental_line(line_id, SALES), 200)


def get_permit(permit_id) -> dict:
    return get_success_data(api_client.get_permit(permit_id, SALES), 200)


def get_visit(visit_id) -> dict:
    return get_success_data(api_client.get_service_visit(visit_id, DISPATCH), 200)


def get_incident(incident_id) -> dict:
    return get_success_data(api_client.get_incident(incident_id, CLAIMS), 200)


def off_hire_line(line_id, headers=None) -> dict:
    return get_success_data(api_client.off_hire_line(line_id, headers or SALES), 200)


def return_line(line_id) -> dict:
    return get_success_data(api_client.return_line(line_id, DEPOT), 200)


# ─── Tier 2: contract hierarchy composites ───────────────

def setup_draft_contract(
    customer_overrides=None,
    site_overrides=None,
    unit_overrides=None,
    contract_overrides=None,
    sizing_method="NAMEPLATE_SUM",
    with_kit=False,
    kit_overrides=None,
    kit_quantity=1,
    extra_unit_overrides=None,
) -> dict:
    """Customer + site + unit + contract, sized, with an EQUIPMENT line
    (optionally a kit line and further EQUIPMENT lines), still in DRAFT."""
    customer = create_customer(**(customer_overrides or {}))
    site = create_site(customer["id"], **(site_overrides or {}))
    unit = create_equipment_unit(**(unit_overrides or {}))
    contract = create_contract(
        customer["id"], site["id"], **(contract_overrides or {})
    )
    bundle = {
        "customer": customer,
        "site": site,
        "unit": unit,
        "contract": contract,
        "line": None,
        "kit": None,
        "kit_line": None,
        "extra_units": [],
        "extra_lines": [],
    }
    if sizing_method is not None:
        bundle["contract"] = run_size_load(contract["id"], sizing_method)
    bundle["line"] = add_equipment_line(contract["id"], unit["id"])
    for spec in (extra_unit_overrides or []):
        extra_unit = create_equipment_unit(**spec)
        bundle["extra_units"].append(extra_unit)
        bundle["extra_lines"].append(add_equipment_line(contract["id"], extra_unit["id"]))
    if with_kit:
        kit = create_accessory_kit(**(kit_overrides or {}))
        bundle["kit"] = kit
        bundle["kit_line"] = add_kit_line(contract["id"], kit["id"], kit_quantity)
    bundle["contract"] = get_contract(contract["id"])
    return bundle


def setup_quoted_contract(**kwargs) -> dict:
    """Draft composite driven through DRAFT -> QUOTED."""
    bundle = setup_draft_contract(**kwargs)
    bundle["contract"] = quote_contract(bundle["contract"]["id"])
    return bundle


def setup_confirmed_contract(**kwargs) -> dict:
    """Quoted composite driven through QUOTED -> CONFIRMED."""
    bundle = setup_quoted_contract(**kwargs)
    bundle["contract"] = confirm_contract(bundle["contract"]["id"])
    return bundle


def setup_on_rent_contract(clock_after_start=None, **kwargs) -> dict:
    """Full chain through CONFIRMED -> MOBILIZING -> ON_RENT: lines activate,
    the unit deploys to the contract site. Optionally advances the clock."""
    bundle = setup_confirmed_contract(**kwargs)
    cid = bundle["contract"]["id"]
    bundle["contract"] = mobilize_contract(cid)
    bundle["contract"] = start_rental(cid)
    if clock_after_start is not None:
        set_logical_clock(clock_after_start)
    return bundle


# ─── Tier 3: permits, visits, telemetry, incidents ───────

def create_permit_for_contract(contract_id, permit_type="EMISSIONS") -> dict:
    res = api_client.create_permit(
        create_permit_payload(contract_id, permit_type), SALES
    )
    return get_success_data(res, 201)


def submit_permit(permit_id) -> dict:
    return get_success_data(api_client.submit_permit(permit_id, SALES), 200)


def decide_permit(permit_id, outcome) -> dict:
    res = api_client.record_permit_decision(permit_id, {"outcome": outcome}, SALES)
    return get_success_data(res, 200)


def approve_permit(contract_id, permit_type="EMISSIONS") -> dict:
    """Permit through DRAFT -> SUBMITTED -> APPROVED."""
    permit = create_permit_for_contract(contract_id, permit_type)
    submit_permit(permit["id"])
    return decide_permit(permit["id"], "APPROVED")


def create_visit(contract_id, visit_type, **overrides) -> dict:
    """Schedule a non-emergency visit as the dispatcher. An emergency
    request must instead be posted directly by the owning Customer."""
    res = api_client.create_service_visit(
        create_service_visit_payload(contract_id, visit_type, **overrides), DISPATCH
    )
    return get_success_data(res, 201)


def request_emergency_visit(contract_id, customer_id) -> dict:
    res = api_client.create_service_visit(
        create_service_visit_payload(contract_id, "EMERGENCY"),
        make_customer_headers(customer_id),
    )
    return get_success_data(res, 201)


def dispatch_visit(visit_id, technician_id) -> dict:
    res = api_client.dispatch_visit(
        visit_id, {"assigned_technician_id": technician_id}, DISPATCH
    )
    return get_success_data(res, 200)


def arrive_visit(visit_id, technician_id) -> dict:
    res = api_client.arrive_visit(
        visit_id, make_field_technician_headers(technician_id)
    )
    return get_success_data(res, 200)


def complete_visit(visit_id, technician_id) -> dict:
    res = api_client.complete_visit(
        visit_id, make_field_technician_headers(technician_id)
    )
    return get_success_data(res, 200)


def post_telemetry(contract_id, event_type, value, unit_id=None, recorded_at=None) -> dict:
    overrides = {}
    if unit_id is not None:
        overrides["equipment_unit_id"] = unit_id
    if recorded_at is not None:
        overrides["recorded_at"] = recorded_at
    res = api_client.create_telemetry_event(
        create_telemetry_event_payload(contract_id, event_type, value, **overrides), TECH
    )
    return get_success_data(res, 201)


def report_incident(contract_id, unit_id, incident_type, as_customer_id=None, **overrides) -> dict:
    """Report an incident; as the owning Customer when as_customer_id is
    given, otherwise as the sales desk (PRD §3.8)."""
    headers = make_customer_headers(as_customer_id) if as_customer_id else SALES
    res = api_client.create_incident(
        create_incident_payload(contract_id, unit_id, incident_type, **overrides), headers
    )
    return get_success_data(res, 201)


def assess_incident(incident_id, assessed_charge_cents, assessor_id="claims-1") -> dict:
    res = api_client.assess_incident(
        incident_id,
        {"assessed_charge_cents": assessed_charge_cents},
        make_claims_assessor_headers(assessor_id),
    )
    return get_success_data(res, 200)


def waive_incident(incident_id, user_id) -> dict:
    res = api_client.waive_incident(incident_id, make_depot_manager_headers(user_id))
    return get_success_data(res, 200)


# ─── Tier 4: lifecycle-targeting composites ──────────────

def setup_off_hire_contract(off_hire_clock="2026-09-04T00:00:00Z", **kwargs) -> dict:
    """ON_RENT composite taken to OFF_HIRE at the given logical time
    (day 3 of the default window: FINAL accrual horizon [start, now))."""
    bundle = setup_on_rent_contract(clock_after_start=off_hire_clock, **kwargs)
    bundle["contract"] = off_hire_contract(bundle["contract"]["id"])
    return bundle


def setup_reported_incident(incident_type="DAMAGE", assess_charge=None,
                            assessor_id="claims-1", **kwargs) -> dict:
    """ON_RENT composite plus a reported incident; optionally assessed."""
    bundle = setup_on_rent_contract(**kwargs)
    incident = report_incident(
        bundle["contract"]["id"], bundle["unit"]["id"], incident_type,
        as_customer_id=bundle["customer"]["id"],
        **({"spill_volume_liters": 25} if incident_type == "SPILL" else {"notes": "cracked bracket"}),
    )
    bundle["incident"] = incident
    if assess_charge is not None:
        bundle["incident"] = assess_incident(incident["id"], assess_charge, assessor_id)
    return bundle


def setup_closed_contract(**kwargs) -> dict:
    """Full lifecycle through OFF_HIRE -> CLOSED (no open incidents)."""
    bundle = setup_off_hire_contract(**kwargs)
    bundle["contract"] = close_contract(bundle["contract"]["id"])
    return bundle
