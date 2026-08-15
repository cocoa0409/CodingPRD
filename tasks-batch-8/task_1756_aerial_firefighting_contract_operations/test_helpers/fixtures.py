"""Composite setup helpers.

Every test starts against a freshly restarted server (empty database, logical
clock at the PRD default 2026-08-01T00:00:00Z), so these helpers build complete
precondition chains out of PRD-declared endpoints only. Setup calls use
get_success_data() so failures surface as clear "Setup step failed" errors.

Identity threading: Pilot calls are entity-backed by CrewMember — every
ownership-gated call (launch, arrive, flight-log, drop) uses
make_pilot_headers(crew_member_id). Finance segregation threads explicit
operator ids (cf_1 / af_1) via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_agency_record_payload,
    create_aircraft_payload,
    create_assignment_payload,
    create_availability_period_payload,
    create_carding_inspection_payload,
    create_contract_payload,
    create_crew_member_payload,
    create_dispatch_order_payload,
    create_flight_log_payload,
    create_incident_payload,
    create_invoice_payload,
    create_retardant_load_payload,
)
from .test_users import (
    TEST_USERS,
    make_agency_finance_headers,
    make_carrier_finance_headers,
    make_pilot_headers,
)

OPS = TEST_USERS["carrier_ops_headers"]
DISPATCH = TEST_USERS["agency_dispatcher_headers"]
INSPECTOR = TEST_USERS["carding_inspector_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creation
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_contract(**overrides):
    """Create a contract (born DRAFT). Returns the contract."""
    return get_success_data(api_client.create_contract(
        create_contract_payload(**overrides), OPS))


def create_active_contract(**overrides):
    """Create a contract and activate it. Returns the ACTIVE contract."""
    contract = create_contract(**overrides)
    return get_success_data(api_client.activate_contract(contract["id"], OPS))


def get_contract(contract_id):
    return get_success_data(api_client.get_contract(contract_id, OPS))


def add_aircraft(contract_id, **overrides):
    """Register an aircraft (born UNCARDED). Returns the aircraft."""
    return get_success_data(api_client.create_aircraft(
        create_aircraft_payload(contract_id, **overrides), OPS))


def get_aircraft(aircraft_id):
    return get_success_data(api_client.get_aircraft(aircraft_id, OPS))


def add_crew_member(contract_id, **overrides):
    """Register a crew member (born UNCARDED, AVAILABLE). Returns the member."""
    return get_success_data(api_client.create_crew_member(
        create_crew_member_payload(contract_id, **overrides), OPS))


def get_crew_member(crew_member_id):
    return get_success_data(api_client.get_crew_member(crew_member_id, OPS))


def create_incident(**overrides):
    """Report an incident (born REPORTED). Returns the incident."""
    return get_success_data(api_client.create_incident(
        create_incident_payload(**overrides), DISPATCH))


# ---------------------------------------------------------------------------
# Tier 1: carding program
# ---------------------------------------------------------------------------

def schedule_inspection(subject_aircraft_id=None, subject_crew_member_id=None,
                        scheduled_for=None, valid_days=None, notes=None):
    """Schedule a carding inspection for exactly one subject. Returns it."""
    kwargs = {}
    if scheduled_for is not None:
        kwargs["scheduled_for"] = scheduled_for
    if valid_days is not None:
        kwargs["valid_days"] = valid_days
    if notes is not None:
        kwargs["notes"] = notes
    return get_success_data(api_client.create_carding_inspection(
        create_carding_inspection_payload(
            subject_aircraft_id=subject_aircraft_id,
            subject_crew_member_id=subject_crew_member_id,
            **kwargs),
        INSPECTOR))


def complete_inspection(inspection_id, result="PASSED",
                        completed_at=None):
    """Complete a SCHEDULED inspection. Returns the completed inspection."""
    return get_success_data(api_client.complete_carding_inspection(
        inspection_id,
        {"result": result,
         "completed_at": completed_at or D["INSPECTION_COMPLETED_AT"]},
        INSPECTOR))


def card_aircraft(aircraft_id, scheduled_for=None, completed_at=None,
                  valid_days=None):
    """Run a passing inspection on the aircraft. Returns refreshed aircraft."""
    insp = schedule_inspection(subject_aircraft_id=aircraft_id,
                               scheduled_for=scheduled_for,
                               valid_days=valid_days)
    complete_inspection(insp["id"], result="PASSED", completed_at=completed_at)
    return get_aircraft(aircraft_id)


def card_crew_member(crew_member_id, scheduled_for=None, completed_at=None,
                     valid_days=None):
    """Run a passing inspection on the crew member. Returns refreshed member."""
    insp = schedule_inspection(subject_crew_member_id=crew_member_id,
                               scheduled_for=scheduled_for,
                               valid_days=valid_days)
    complete_inspection(insp["id"], result="PASSED", completed_at=completed_at)
    return get_crew_member(crew_member_id)


# ---------------------------------------------------------------------------
# Tier 2: contract workspace (active contract + carded aircraft + carded pilot)
# ---------------------------------------------------------------------------

def setup_carded_pair(contract_overrides=None, aircraft_overrides=None,
                      pilot_name="Pat Reed", pilot_models=None,
                      aircraft_card_days=None):
    """ACTIVE contract + one CARDED aircraft + one CARDED PIC pilot + incident.

    Returns a workspace dict: contract, aircraft, pilot, incident.
    """
    contract = create_active_contract(**(contract_overrides or {}))
    aircraft = add_aircraft(contract["id"], **(aircraft_overrides or {}))
    pilot = add_crew_member(
        contract["id"],
        full_name=pilot_name,
        qualified_aircraft_models=(
            pilot_models if pilot_models is not None else [D["AIRCRAFT_MODEL"]]),
    )
    aircraft = card_aircraft(aircraft["id"], valid_days=aircraft_card_days)
    pilot = card_crew_member(pilot["id"])
    incident = create_incident()
    return {"contract": contract, "aircraft": aircraft, "pilot": pilot,
            "incident": incident}


def add_carded_pilot(contract_id, full_name="Sam Ortiz", models=None):
    """Register and card a second PIC pilot on the same contract."""
    pilot = add_crew_member(
        contract_id,
        full_name=full_name,
        qualified_aircraft_models=(
            models if models is not None else [D["AIRCRAFT_MODEL"]]),
    )
    return card_crew_member(pilot["id"])


# ---------------------------------------------------------------------------
# Tier 3: dispatch orders and assignments (OCC-threaded)
# ---------------------------------------------------------------------------

def place_order(contract_id, incident_id, aircraft_quantity=1,
                required_model=None, order_number=None):
    """Place a resource order (born PLACED). Returns the order."""
    kwargs = {"aircraft_quantity": aircraft_quantity}
    if required_model is not None:
        kwargs["required_model"] = required_model
    if order_number is not None:
        kwargs["order_number"] = order_number
    return get_success_data(api_client.create_dispatch_order(
        create_dispatch_order_payload(contract_id, incident_id, **kwargs),
        DISPATCH))


def accept_order(order_id):
    return get_success_data(api_client.accept_dispatch_order(order_id, OPS))


def get_order(order_id):
    return get_success_data(api_client.get_dispatch_order(order_id, OPS))


def setup_accepted_order(ws, quantity=1, required_model=None,
                         order_number=None):
    """Place + accept an order against the workspace contract/incident."""
    order = place_order(ws["contract"]["id"], ws["incident"]["id"],
                        aircraft_quantity=quantity,
                        required_model=required_model,
                        order_number=order_number)
    return accept_order(order["id"])


def create_assignment(order_id, aircraft_id, pilot_id, planned_start,
                      planned_end):
    """Create an assignment, threading the order's current version (OCC)."""
    version = get_order(order_id)["version"]
    return get_success_data(api_client.create_assignment(
        order_id,
        create_assignment_payload(aircraft_id, pilot_id, planned_start,
                                  planned_end, version),
        OPS))


def launch_assignment(assignment_id, pilot_id):
    """Launch as the assigned pilot (entity-backed identity)."""
    return get_success_data(api_client.launch_assignment(
        assignment_id, make_pilot_headers(pilot_id)))


def arrive_assignment(assignment_id, pilot_id):
    return get_success_data(api_client.arrive_assignment(
        assignment_id, make_pilot_headers(pilot_id)))


def release_assignment(assignment_id, reason="AGENCY"):
    return get_success_data(api_client.release_assignment(
        assignment_id, {"release_reason": reason}, DISPATCH))


def demobilize_assignment(assignment_id):
    return get_success_data(api_client.demobilize_assignment(assignment_id, OPS))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_assignment(assignment_id, OPS))


def setup_on_incident(ws=None, planned_start="2026-08-02T08:00:00Z",
                      planned_end="2026-08-02T10:00:00Z", quantity=1,
                      order_number=None, required_model=None,
                      **pair_kwargs):
    """Full chain: carded workspace + ACCEPTED order + ON_INCIDENT assignment.

    Returns the workspace dict extended with ``order`` and ``assignment``.
    """
    if ws is None:
        ws = setup_carded_pair(**pair_kwargs)
    order = setup_accepted_order(ws, quantity=quantity,
                                 required_model=required_model,
                                 order_number=order_number)
    assignment = create_assignment(order["id"], ws["aircraft"]["id"],
                                   ws["pilot"]["id"], planned_start, planned_end)
    launch_assignment(assignment["id"], ws["pilot"]["id"])
    assignment = arrive_assignment(assignment["id"], ws["pilot"]["id"])
    ws["order"] = order
    ws["assignment"] = assignment
    return ws


# ---------------------------------------------------------------------------
# Tier 4: sorties, duty days, retardant
# ---------------------------------------------------------------------------

def log_sortie(assignment_id, pilot_id, logged_date, hobbs_start, hobbs_stop):
    """Append a flight log as the owning pilot. Returns the FlightLog."""
    return get_success_data(api_client.create_flight_log(
        assignment_id,
        create_flight_log_payload(logged_date, hobbs_start, hobbs_stop),
        make_pilot_headers(pilot_id)))


def list_duty_days(crew_member_id, params=None):
    return get_success_data(api_client.list_crew_duty_days(
        crew_member_id, OPS, params=params))


def request_load(assignment_id, gallons=700, requested_at=None):
    return get_success_data(api_client.create_retardant_load(
        assignment_id,
        create_retardant_load_payload(gallons=gallons,
                                      requested_at=requested_at),
        OPS))


def complete_load(load_id, loaded_at):
    return get_success_data(api_client.load_retardant_load(
        load_id, {"loaded_at": loaded_at}, OPS))


def drop_load(load_id, dropped_at):
    return get_success_data(api_client.drop_retardant_load(
        load_id, {"dropped_at": dropped_at}, OPS))


# ---------------------------------------------------------------------------
# Tier 5: invoicing and reconciliation
# ---------------------------------------------------------------------------

def create_draft_invoice(contract_id, period_start, period_end):
    """Create a DRAFT invoice, threading the contract's current version (OCC)."""
    version = get_contract(contract_id)["version"]
    return get_success_data(api_client.create_invoice(
        contract_id,
        create_invoice_payload(period_start, period_end, version),
        make_carrier_finance_headers("cf_1")))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(
        invoice_id, TEST_USERS["carrier_finance_headers"]))


def list_line_items(invoice_id, params=None):
    return get_success_data(api_client.list_invoice_line_items(
        invoice_id, TEST_USERS["carrier_finance_headers"], params=params))


def submit_invoice(invoice_id, submitted_by="cf_1", advance_clock_to=None):
    """Advance the clock past the billing period (if given) and submit."""
    if advance_clock_to is not None:
        set_clock(advance_clock_to)
    return get_success_data(api_client.submit_invoice(
        invoice_id, make_carrier_finance_headers(submitted_by)))


def import_agency_record(contract_id, assignment_id, record_date,
                         agency_flight_hours_tenths, imported_by="af_1"):
    return get_success_data(api_client.create_agency_record(
        create_agency_record_payload(contract_id, assignment_id, record_date,
                                     agency_flight_hours_tenths),
        make_agency_finance_headers(imported_by)))


def setup_submitted_invoice(ws=None, log_overrides=None, period="2026-08-02",
                            submit_clock="2026-08-09T00:00:00Z", **pair_kwargs):
    """Full chain through a SUBMITTED invoice covering one 5.0 h flight day.

    Workspace: carded pair + ON_INCIDENT assignment + one 5.0 h sortie logged
    on ``period`` (50 tenths, 1,500,000 cents at the default rate), then a
    DRAFT invoice for [period, period] submitted by CarrierFinance cf_1 after
    the clock advances past the period.

    Returns the workspace dict extended with ``order``, ``assignment``,
    ``flight_log`` and ``invoice``.
    """
    if ws is None:
        ws = setup_on_incident(**pair_kwargs)
    log_kwargs = {"logged_date": period, "hobbs_start": 0.0, "hobbs_stop": 5.0}
    if log_overrides:
        log_kwargs.update(log_overrides)
    flight_log = log_sortie(ws["assignment"]["id"], ws["pilot"]["id"],
                            **log_kwargs)
    invoice = create_draft_invoice(ws["contract"]["id"], period, period)
    invoice = submit_invoice(invoice["id"], submitted_by="cf_1",
                             advance_clock_to=submit_clock)
    ws["flight_log"] = flight_log
    ws["invoice"] = invoice
    return ws


def setup_availability_invoice(contract_id, aircraft_id,
                               service_date="2026-08-03",
                               available_start="2026-08-03T07:00:00Z",
                               available_end="2026-08-03T16:30:00Z"):
    """Post one availability period and open a DRAFT invoice covering it."""
    period = get_success_data(api_client.create_availability_period(
        contract_id,
        create_availability_period_payload(
            aircraft_id, service_date=service_date,
            available_start=available_start, available_end=available_end),
        OPS))
    invoice = create_draft_invoice(contract_id, service_date, service_date)
    return period, invoice
