"""Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because each test runs against a freshly restarted server with an
empty database. Helpers use get_success_data() so setup failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_owner_payload,
    create_aircraft_payload,
    create_agreement_payload,
    create_budget_payload,
    create_expense_payload,
    create_crew_payload,
    create_trip_payload,
    create_assignment_payload,
    create_program_payload,
    create_event_payload,
    create_filing_payload,
    create_contract_payload,
    create_statement_payload,
)
from .test_users import TEST_USERS, make_owner_headers, make_operator_headers

AE = TEST_USERS["account_executive_headers"]
FO = TEST_USERS["flight_ops_headers"]
MP = TEST_USERS["maintenance_planner_headers"]
FC = TEST_USERS["finance_controller_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["contracts_manager_headers"]
PA = TEST_USERS["platform_admin_headers"]


# ─── Tier 1: single-entity creation ───────────────────

def create_owner(**overrides) -> dict:
    """Onboard an owner (PRD §3.1). Returns the Owner resource."""
    return get_success_data(
        api_client.create_owner(create_owner_payload(**overrides), AE)
    )


def create_aircraft(owner_id, tail_number="N100JX", **overrides) -> dict:
    """Register an aircraft under an owner (PRD §3.1)."""
    payload = create_aircraft_payload(owner_id, tail_number=tail_number, **overrides)
    return get_success_data(api_client.create_aircraft(payload, AE))


def setup_owner_and_aircraft(tail_number="N100JX", owner_overrides=None, aircraft_overrides=None):
    """Owner + one registered aircraft. Returns (owner, aircraft)."""
    owner = create_owner(**(owner_overrides or {}))
    aircraft = create_aircraft(owner["id"], tail_number=tail_number, **(aircraft_overrides or {}))
    return owner, aircraft


# ─── Tier 1: agreement lifecycle ──────────────────────

def create_agreement(owner_id, aircraft_id, **terms) -> dict:
    """Create a management agreement (starts PENDING, PRD §3.1)."""
    return get_success_data(
        api_client.create_agreement(
            create_agreement_payload(owner_id, aircraft_id, **terms), AE
        )
    )


def setup_pending_agreement(tail_number="N100JX", terms=None) -> dict:
    """Owner + aircraft + PENDING agreement.

    Returns {"owner", "aircraft", "agreement"}.
    """
    owner, aircraft = setup_owner_and_aircraft(tail_number=tail_number)
    agreement = create_agreement(owner["id"], aircraft["id"], **(terms or {}))
    return {"owner": owner, "aircraft": aircraft, "agreement": agreement}


def setup_active_agreement(tail_number="N100JX", terms=None) -> dict:
    """Owner + aircraft + ACTIVE agreement (PRD §3.1).

    Returns {"owner", "aircraft", "agreement"} where agreement is the
    post-activation representation (its version already reflects activation).
    """
    scenario = setup_pending_agreement(tail_number=tail_number, terms=terms)
    activated = get_success_data(
        api_client.activate_agreement(scenario["agreement"]["id"], AE)
    )
    scenario["agreement"] = activated
    return scenario


# ─── Tier 2: crew qualification ───────────────────────

def create_crew_member(aircraft_id, **overrides) -> dict:
    """Hire a crew member (starts HIRED, PRD §3.3)."""
    return get_success_data(
        api_client.create_crew_member(create_crew_payload(aircraft_id, **overrides), FO)
    )


def qualify_crew_member(aircraft_id, full_name="Pat Captain", crew_role="CAPTAIN",
                        hire_date="2026-01-15", training_hours=30) -> dict:
    """Hire → begin-training → complete-training. Returns QUALIFIED crew member."""
    crew = create_crew_member(
        aircraft_id, full_name=full_name, crew_role=crew_role, hire_date=hire_date
    )
    get_success_data(api_client.begin_training(crew["id"], FO))
    return get_success_data(
        api_client.complete_training(
            crew["id"],
            {"training_hours": training_hours, "check_ride_passed": True},
            FO,
        )
    )


def setup_qualified_crew_pair(aircraft_id):
    """One QUALIFIED CAPTAIN + one QUALIFIED FIRST_OFFICER (PRD §3.4 gate 4).

    Returns (captain, first_officer).
    """
    captain = qualify_crew_member(
        aircraft_id, full_name="Pat Captain", crew_role="CAPTAIN",
        hire_date="2026-01-15", training_hours=30,
    )
    first_officer = qualify_crew_member(
        aircraft_id, full_name="Sam Officer", crew_role="FIRST_OFFICER",
        hire_date="2026-02-01", training_hours=28,
    )
    return captain, first_officer


# ─── Tier 2: compliance ───────────────────────────────

def create_filing(aircraft_id, **overrides) -> dict:
    """Draft a compliance filing (starts DRAFT, PRD §3.6)."""
    return get_success_data(
        api_client.create_filing(create_filing_payload(aircraft_id, **overrides), CO)
    )


def file_accepted_insurance(aircraft_id, valid_until="2027-01-01",
                            reference_no="COI-1001", authority="Avemco") -> dict:
    """Draft → file → record-decision ACCEPTED. Returns the ACCEPTED filing."""
    filing = create_filing(
        aircraft_id, filing_kind="INSURANCE_COI", authority=authority,
        reference_no=reference_no, valid_until=valid_until,
    )
    get_success_data(api_client.file_filing(filing["id"], {}, CO))
    return get_success_data(
        api_client.record_decision(filing["id"], {"outcome": "ACCEPTED"}, CO)
    )


# ─── Tier 2: trips ────────────────────────────────────

def create_trip(aircraft_id, trip_use="OWNER_USE", departure_at="2026-08-06T08:00:00Z",
                block_hours_est=3.0, charter_quote_cents=None,
                depart_icao="KTEB", arrive_icao="KPBI", as_owner_id=None) -> dict:
    """Request a trip (PRD §3.4). OWNER_USE auto-approves; CHARTER stays REQUESTED."""
    payload = create_trip_payload(
        aircraft_id, trip_use=trip_use, departure_at=departure_at,
        block_hours_est=block_hours_est, depart_icao=depart_icao, arrive_icao=arrive_icao,
    )
    if charter_quote_cents is not None:
        payload["charter_quote_cents"] = charter_quote_cents
    headers = make_owner_headers(as_owner_id) if as_owner_id else FO
    return get_success_data(api_client.create_trip(payload, headers))


def approve_charter_trip(trip_id, owner_id) -> dict:
    """Owner approves a REQUESTED charter trip (owner-scoped, PRD §3.4)."""
    return get_success_data(api_client.approve_trip(trip_id, make_owner_headers(owner_id)))


def assign_duty(trip_id, crew_member_id, duty_role, duty_start_at, duty_end_at) -> dict:
    """Assign crew to a trip with a duty window (PRD §3.3)."""
    return get_success_data(
        api_client.create_assignment(
            create_assignment_payload(
                trip_id, crew_member_id, duty_role=duty_role,
                duty_start_at=duty_start_at, duty_end_at=duty_end_at,
            ),
            FO,
        )
    )


def schedule_trip(trip_id) -> dict:
    """Schedule an APPROVED trip (PRD §3.4 five gates)."""
    return get_success_data(api_client.schedule_trip(trip_id, FO))


def complete_trip(trip_id, block_hours_actual) -> dict:
    """Complete a SCHEDULED trip with actual block hours (PRD §3.4)."""
    return get_success_data(
        api_client.complete_trip(trip_id, {"block_hours_actual": block_hours_actual}, FO)
    )


def setup_scheduled_trip(aircraft_id, owner_id, captain, first_officer,
                         trip_use="OWNER_USE", departure_at="2026-08-06T08:00:00Z",
                         block_hours_est=3.0, charter_quote_cents=None,
                         pic_window=("2026-08-06T06:00:00Z", "2026-08-06T12:00:00Z"),
                         sic_window=None,
                         depart_icao="KTEB", arrive_icao="KPBI") -> dict:
    """Create → (owner-approve if CHARTER) → assign PIC/SIC → schedule.

    Returns the SCHEDULED trip. Caller must ensure the scheduling gates are
    satisfied (ACTIVE agreement, current insurance, no overdue maintenance).
    """
    sic_window = sic_window or pic_window
    trip = create_trip(
        aircraft_id, trip_use=trip_use, departure_at=departure_at,
        block_hours_est=block_hours_est, charter_quote_cents=charter_quote_cents,
        depart_icao=depart_icao, arrive_icao=arrive_icao,
    )
    if trip_use == "CHARTER":
        trip = approve_charter_trip(trip["id"], owner_id)
    assign_duty(trip["id"], captain["id"], "PIC", *pic_window)
    assign_duty(trip["id"], first_officer["id"], "SIC", *sic_window)
    return schedule_trip(trip["id"])


def setup_completed_trip(aircraft_id, owner_id, captain, first_officer,
                         block_hours_actual, **kwargs) -> dict:
    """Full trip lifecycle through COMPLETED (PRD §3.4). Returns the trip."""
    trip = setup_scheduled_trip(
        aircraft_id, owner_id, captain, first_officer, **kwargs
    )
    return complete_trip(trip["id"], block_hours_actual)


# ─── Tier 2: dispatch-ready aircraft ──────────────────

def setup_dispatch_ready(tail_number="N100JX", terms=None,
                         insurance_valid_until="2027-01-01") -> dict:
    """ACTIVE agreement + QUALIFIED crew pair + ACCEPTED INSURANCE_COI.

    This satisfies scheduling gates (1) agreement, (3) insurance, and (4) crew
    complement for any trip once PIC/SIC are assigned (PRD §3.4).
    Returns {"owner", "aircraft", "agreement", "captain", "first_officer", "filing"}.
    """
    scenario = setup_active_agreement(tail_number=tail_number, terms=terms)
    captain, first_officer = setup_qualified_crew_pair(scenario["aircraft"]["id"])
    filing = file_accepted_insurance(
        scenario["aircraft"]["id"], valid_until=insurance_valid_until,
    )
    scenario.update({
        "captain": captain,
        "first_officer": first_officer,
        "filing": filing,
    })
    return scenario


# ─── Tier 2: expenses and statements ──────────────────

def post_expense(aircraft_id, category="FUEL", amount_cents=250000,
                 service_date="2026-08-05", paid_date="2026-08-07",
                 vendor_name="Meridian Fuel", tax_use="OWNER_USE",
                 trip_id=None) -> dict:
    """Post an expense (starts POSTED, PRD §3.8). paid_date/trip_id omitted when None."""
    payload = create_expense_payload(
        aircraft_id, category=category, amount_cents=amount_cents,
        service_date=service_date, vendor_name=vendor_name, tax_use=tax_use,
    )
    if paid_date is not None:
        payload["paid_date"] = paid_date
    if trip_id is not None:
        payload["trip_id"] = trip_id
    return get_success_data(api_client.create_expense(payload, FC))


def generate_statement(aircraft_id, period="2026-08", preparer_user_id="ae-1") -> dict:
    """Generate (or recompute) the monthly statement (PRD §3.8).

    Uses an explicit AccountExecutive X-User-ID so the prepared_by_user_id is
    controllable for segregation-of-duties scenarios.
    """
    headers = make_operator_headers(preparer_user_id, "AccountExecutive")
    return get_success_data(
        api_client.create_statement(create_statement_payload(aircraft_id, period=period), headers)
    )


def certify_statement(statement_id, certifier_user_id="fc-1") -> dict:
    """Certify a DRAFT statement as a FinanceController (PRD §3.8)."""
    headers = make_operator_headers(certifier_user_id, "FinanceController")
    return get_success_data(api_client.certify_statement(statement_id, headers))


def setup_certified_statement(scenario, period="2026-08",
                              preparer_user_id="ae-1", certifier_user_id="fc-1"):
    """Generate a statement and certify it with a different user id.

    Returns the CERTIFIED statement. Callers post expenses BEFORE calling so
    the certification staleness gate is satisfied (PRD §3.8).
    """
    statement = generate_statement(
        scenario["aircraft"]["id"], period=period, preparer_user_id=preparer_user_id
    )
    return certify_statement(statement["id"], certifier_user_id=certifier_user_id)


# ─── Tier 2: budgets ──────────────────────────────────

def create_budget(aircraft_id, **overrides) -> dict:
    """Draft an annual budget (starts DRAFT, PRD §3.2)."""
    return get_success_data(
        api_client.create_budget(create_budget_payload(aircraft_id, **overrides), AE)
    )


def setup_approved_budget(aircraft_id, owner_id, **overrides) -> dict:
    """Draft → submit → owner-approve. Returns the APPROVED budget (PRD §3.2)."""
    budget = create_budget(aircraft_id, **overrides)
    get_success_data(api_client.submit_budget(budget["id"], AE))
    return get_success_data(
        api_client.approve_budget(budget["id"], make_owner_headers(owner_id))
    )


# ─── Tier 2: maintenance programs and events ──────────

def create_program(aircraft_id, **overrides) -> dict:
    """Quote an hourly-cost maintenance program (starts QUOTED, PRD §3.5)."""
    return get_success_data(
        api_client.create_program(create_program_payload(aircraft_id, **overrides), MP)
    )


def setup_enrolled_program(aircraft_id, rate_per_hour_cents=15000,
                           program_name="JetCare hourly") -> dict:
    """Quote → enroll. Returns the ENROLLED program (PRD §3.5)."""
    program = create_program(
        aircraft_id, program_name=program_name, rate_per_hour_cents=rate_per_hour_cents
    )
    return get_success_data(api_client.enroll_program(program["id"], MP))


def create_event(aircraft_id, **overrides) -> dict:
    """Create a base maintenance event forecast (starts FORECAST, PRD §3.5)."""
    return get_success_data(
        api_client.create_event(create_event_payload(aircraft_id, **overrides), MP)
    )


# ─── Tier 2: vendor contracts ─────────────────────────

def create_contract(aircraft_id, **overrides) -> dict:
    """Draft a vendor contract (starts DRAFT, PRD §3.7)."""
    return get_success_data(
        api_client.create_contract(create_contract_payload(aircraft_id, **overrides), CM)
    )


# ─── Tier 5: termination / records handover ───────────

def give_notice(agreement_id, owner_id=None) -> dict:
    """Give termination notice against an ACTIVE agreement (PRD §3.9).

    Passes owner_id to act as the Owner; otherwise acts as AccountExecutive.
    """
    headers = make_owner_headers(owner_id) if owner_id else AE
    return get_success_data(api_client.give_termination_notice(agreement_id, headers))


def release_records(agreement_id, record_ids) -> dict:
    """Release a batch of maintenance/compliance records (PRD §3.9)."""
    return get_success_data(
        api_client.release_records(agreement_id, {"record_ids": record_ids}, AE)
    )


def setup_termination_pending(tail_number="N100JX", with_filing=True,
                              with_event=False) -> dict:
    """ACTIVE agreement + optional records → termination notice.

    Returns scenario dict with "owner", "aircraft", "agreement" (now
    TERMINATION_PENDING) plus optional "filing" / "event".
    """
    scenario = setup_active_agreement(tail_number=tail_number)
    aircraft_id = scenario["aircraft"]["id"]
    if with_filing:
        scenario["filing"] = file_accepted_insurance(aircraft_id)
    if with_event:
        scenario["event"] = create_event(aircraft_id)
    scenario["agreement"] = give_notice(
        scenario["agreement"]["id"], owner_id=scenario["owner"]["id"]
    )
    return scenario


# ─── Logical clock ────────────────────────────────────

def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (PRD §2.5)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PA)
    )
