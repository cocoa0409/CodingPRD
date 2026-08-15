"""Composite setup helpers — multi-step PRD workflow preambles.

Fixtures use get_success_data() internally so a setup failure surfaces as a
clear "Setup step failed" assertion instead of a confusing downstream error.

Identity threading: flight logs are recorded with make_crew_member_headers(
crew_id) (the trip's VETTED PIC), and owner statement reads use
make_aircraft_owner_headers(owner_id) — never the shared fallback constants.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_aircraft_owner_payload,
    create_aircraft_payload,
    create_crew_member_payload,
    create_trip_request_payload,
    create_quote_leg_payload,
    create_aircraft_assignment_payload,
    create_crew_assignment_payload,
    create_maintenance_window_payload,
    create_passenger_payload,
    create_overflight_permit_payload,
    create_payment_payload,
    create_flight_log_payload,
    create_compliance_finding_payload,
    create_weather_advisory_payload,
)
from .test_users import (
    TEST_USERS,
    make_aircraft_owner_headers,
    make_crew_member_headers,
)

OPS_ADMIN = TEST_USERS["ops_admin_headers"]
SALES_AGENT = TEST_USERS["sales_agent_headers"]
DISPATCH_MANAGER = TEST_USERS["dispatch_manager_headers"]
MAINTENANCE_CONTROLLER = TEST_USERS["maintenance_controller_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime:
    """Parse a server-emitted ISO 8601 UTC timestamp. The server renders
    timestamps with three fractional digits (PRD section 2.5), e.g.
    '2026-08-10T10:00:00.000Z'; accept fractional seconds optionally."""
    return datetime.fromisoformat(
        ts.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Advance the logical clock (OpsAdmin-only test-driving capability)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS_ADMIN))


def create_owner(**overrides):
    return get_success_data(api_client.create_aircraft_owner(
        create_aircraft_owner_payload(**overrides), OPS_ADMIN))


def create_aircraft(owner_id, **overrides):
    return get_success_data(api_client.create_aircraft(
        create_aircraft_payload(owner_id, **overrides), OPS_ADMIN))


def create_crew(**overrides):
    return get_success_data(api_client.create_crew_member(
        create_crew_member_payload(**overrides), OPS_ADMIN))


def create_trip(**overrides):
    return get_success_data(api_client.create_trip_request(
        create_trip_request_payload(**overrides), SALES_AGENT))


def add_leg(trip_id, seq_no=1, block_minutes=60, leg_type="REVENUE", **overrides):
    return get_success_data(api_client.create_quote_leg(
        create_quote_leg_payload(
            trip_id, seq_no=seq_no, block_minutes=block_minutes, leg_type=leg_type, **overrides),
        SALES_AGENT))


def get_trip(trip_id):
    return get_success_data(api_client.get_trip_request(trip_id, OPS_ADMIN))


def quote_trip(trip_id):
    return get_success_data(api_client.quote_trip(trip_id, SALES_AGENT))


def book_trip(trip_id, deposit_cents):
    return get_success_data(api_client.book_trip(
        trip_id, {"deposit_cents": deposit_cents}, SALES_AGENT))


def post_payment(trip_id, amount_cents, payment_type="BALANCE"):
    return get_success_data(api_client.create_payment(
        create_payment_payload(trip_id, payment_type=payment_type, amount_cents=amount_cents),
        SALES_AGENT))


def cancel_trip(trip_id, reason="CUSTOMER"):
    return get_success_data(api_client.cancel_trip(trip_id, {"reason": reason}, SALES_AGENT))


def dispatch_trip(trip_id):
    return get_success_data(api_client.dispatch_trip(trip_id, DISPATCH_MANAGER))


def create_assignment(trip_id, aircraft_id):
    """Create a TENTATIVE assignment, OCC-checked against the trip's live version."""
    trip = get_trip(trip_id)
    return get_success_data(api_client.create_aircraft_assignment(
        create_aircraft_assignment_payload(trip_id, aircraft_id, trip["version"]),
        DISPATCH_MANAGER))


def confirm_assignment(assignment_id):
    return get_success_data(api_client.confirm_aircraft_assignment(assignment_id, DISPATCH_MANAGER))


def release_assignment(assignment_id):
    return get_success_data(api_client.release_aircraft_assignment(assignment_id, DISPATCH_MANAGER))


def create_crew_assignment(trip_id, crew_id, duty_role="PIC"):
    return get_success_data(api_client.create_crew_assignment(
        create_crew_assignment_payload(trip_id, crew_id, duty_role=duty_role),
        DISPATCH_MANAGER))


def vet_crew_assignment(crew_assignment_id):
    return get_success_data(api_client.vet_crew_assignment(crew_assignment_id, DISPATCH_MANAGER))


def create_vetted_crew(trip_id, crew_id, duty_role="PIC"):
    """Create a crew assignment and vet it. Returns the vetted assignment."""
    ca = create_crew_assignment(trip_id, crew_id, duty_role=duty_role)
    return vet_crew_assignment(ca["id"])


def add_passenger(trip_id, full_name="Pax One", date_of_birth="1980-01-01"):
    return get_success_data(api_client.create_passenger(
        create_passenger_payload(trip_id, full_name=full_name, date_of_birth=date_of_birth),
        SALES_AGENT))


def screen_passenger(passenger_id, outcome="CLEARED"):
    return get_success_data(api_client.screen_passenger(
        passenger_id, {"outcome": outcome}, COMPLIANCE_OFFICER))


def create_permit(trip_id, country_code="MX", permit_type="LANDING", required=True):
    return get_success_data(api_client.create_overflight_permit(
        create_overflight_permit_payload(
            trip_id, country_code=country_code, permit_type=permit_type, required=required),
        SALES_AGENT))


def decide_permit(permit_id, decision="GRANTED"):
    return get_success_data(api_client.decide_overflight_permit(
        permit_id, {"decision": decision}, COMPLIANCE_OFFICER))


def create_window(aircraft_id, window_type="ANNUAL",
                  starts_at="2026-08-05T00:00:00Z", ends_at="2026-08-05T06:00:00Z"):
    return get_success_data(api_client.create_maintenance_window(
        create_maintenance_window_payload(
            aircraft_id, window_type=window_type, starts_at=starts_at, ends_at=ends_at),
        MAINTENANCE_CONTROLLER))


def complete_window(window_id):
    return get_success_data(api_client.complete_maintenance_window(window_id, MAINTENANCE_CONTROLLER))


def cancel_window(window_id):
    return get_success_data(api_client.cancel_maintenance_window(window_id, MAINTENANCE_CONTROLLER))


def ground_aircraft(aircraft_id):
    return get_success_data(api_client.ground_aircraft(aircraft_id, COMPLIANCE_OFFICER))


def return_to_service(aircraft_id):
    return get_success_data(api_client.return_aircraft_to_service(aircraft_id, COMPLIANCE_OFFICER))


def create_finding(subject_type, subject_id, finding_code="OPSPEC-A001", grounding=True, notes="finding"):
    return get_success_data(api_client.create_compliance_finding(
        create_compliance_finding_payload(
            subject_type, subject_id, finding_code=finding_code, grounding=grounding, notes=notes),
        COMPLIANCE_OFFICER))


def resolve_finding(finding_id):
    return get_success_data(api_client.resolve_compliance_finding(finding_id, COMPLIANCE_OFFICER))


def create_advisory(station_icao="KLAX", severity="SIGMET",
                    starts_at="2026-08-03T00:00:00Z", ends_at="2026-08-05T00:00:00Z"):
    return get_success_data(api_client.create_weather_advisory(
        create_weather_advisory_payload(
            station_icao=station_icao, severity=severity, starts_at=starts_at, ends_at=ends_at),
        DISPATCH_MANAGER))


def post_flight_log(trip_id, leg_id, actual_block_minutes, departed_at, arrived_at, crew_id):
    """Record a flight log as the trip's VETTED PIC (identity-bound write)."""
    return get_success_data(api_client.create_flight_log(
        create_flight_log_payload(
            trip_id, leg_id, actual_block_minutes=actual_block_minutes,
            departed_at=departed_at, arrived_at=arrived_at),
        make_crew_member_headers(crew_id)))


def issue_statement(statement_id):
    return get_success_data(api_client.issue_owner_statement(statement_id, OPS_ADMIN))


def list_owner_statements(owner_id, as_owner=False):
    """List an owner's statements; as_owner=True authenticates as the owner itself."""
    headers = make_aircraft_owner_headers(owner_id) if as_owner else OPS_ADMIN
    rows, _meta = validate_paginated(api_client.list_owner_statements(owner_id, headers))
    return rows


# ---------------------------------------------------------------------------
# Tier 2/3: sales-pipeline and operations-chain composites
# ---------------------------------------------------------------------------

def setup_quoted_trip(legs=((60, "REVENUE", False),), category="LIGHT_JET",
                      departure_at="2026-08-10T10:00:00Z", passenger_count=0,
                      international=False, origin_icao="KLAX", destination_icao="KTEB",
                      customer_name="Cust One"):
    """Create trip + legs + run quote pricing. Returns (trip_data, [leg_data, ...]).

    legs is a tuple/list of (block_minutes, leg_type, fuel_stop) triples.
    """
    trip = create_trip(customer_name=customer_name, requested_category=category,
                       origin_icao=origin_icao, destination_icao=destination_icao,
                       departure_at=departure_at, passenger_count=passenger_count,
                       international=international)
    leg_rows = []
    for idx, (minutes, leg_type, fuel_stop) in enumerate(legs, start=1):
        leg_rows.append(add_leg(trip["id"], seq_no=idx, block_minutes=minutes,
                                leg_type=leg_type, fuel_stop=fuel_stop))
    return quote_trip(trip["id"]), leg_rows


def setup_booked_trip(pay_in_full=True, deposit_cents=None, **kwargs):
    """Quoted trip then booked. When pay_in_full, also posts the BALANCE remainder.
    Returns (trip_data_after_payments, legs)."""
    trip, legs = setup_quoted_trip(**kwargs)
    deposit = deposit_cents if deposit_cents is not None else trip["deposit_required_cents"]
    trip = book_trip(trip["id"], deposit)
    if pay_in_full:
        remaining = trip["quoted_total_cents"] - trip["collected_cents"]
        if remaining > 0:
            post_payment(trip["id"], remaining)
            trip = get_trip(trip["id"])
    return trip, legs


def setup_trip_with_confirmed_aircraft(owner_overrides=None, aircraft_overrides=None, **trip_kwargs):
    """Owner + aircraft + booked trip + CONFIRMED assignment.

    Returns dict(owner, aircraft, trip, legs, assignment).
    """
    owner = create_owner(**(owner_overrides or {}))
    aircraft = create_aircraft(owner["id"], **(aircraft_overrides or {}))
    trip, legs = setup_booked_trip(**trip_kwargs)
    assignment = confirm_assignment(create_assignment(trip["id"], aircraft["id"])["id"])
    return {"owner": owner, "aircraft": aircraft, "trip": get_trip(trip["id"]),
            "legs": legs, "assignment": assignment}


def setup_dispatch_ready(owner_overrides=None, aircraft_overrides=None,
                         crew_overrides=None, with_crew=True, screen=True,
                         grant_permits=True, **trip_kwargs):
    """Confirmed trip + VETTED PIC + screened manifest (+ GRANTED permit if
    international). Returns dict(owner, aircraft, crew, trip, legs, assignment,
    crew_assignment, passengers, permits)."""
    ctx = setup_trip_with_confirmed_aircraft(
        owner_overrides=owner_overrides, aircraft_overrides=aircraft_overrides, **trip_kwargs)
    crew = create_crew(**(crew_overrides or {}))
    ctx["crew"] = crew
    ctx["crew_assignment"] = (
        create_vetted_crew(ctx["trip"]["id"], crew["id"]) if with_crew else None)
    passengers = []
    for i in range(ctx["trip"]["passenger_count"]):
        pax = add_passenger(ctx["trip"]["id"], full_name=f"Pax {i + 1}")
        if screen:
            pax = screen_passenger(pax["id"], "CLEARED")
        passengers.append(pax)
    ctx["passengers"] = passengers
    permits = []
    if ctx["trip"]["international"]:
        permit = create_permit(ctx["trip"]["id"])
        if grant_permits:
            permit = decide_permit(permit["id"], "GRANTED")
        permits.append(permit)
    ctx["permits"] = permits
    return ctx


def setup_dispatched_trip(**kwargs):
    """Dispatch-ready chain driven through dispatch. Trip is DISPATCHED,
    aircraft IN_TRIP. Same return shape as setup_dispatch_ready."""
    ctx = setup_dispatch_ready(**kwargs)
    ctx["trip"] = dispatch_trip(ctx["trip"]["id"])
    return ctx


def setup_completed_trip(actual_minutes=None, **kwargs):
    """Full lifecycle: dispatched trip + exactly one flight log per leg, posted
    by the VETTED PIC. Trip is COMPLETED and the settlement cascade has run.

    actual_minutes: per-leg actual block minutes (defaults to each leg's
    planned block_minutes). Returns the dispatch context plus
    flight_logs / trip (re-read) / aircraft (re-read) / statements.
    """
    ctx = setup_dispatched_trip(**kwargs)
    legs = ctx["legs"]
    actuals = actual_minutes or [leg["block_minutes"] for leg in legs]
    departed = _parse(ctx["trip"]["departure_at"])
    logs = []
    for leg, actual in zip(legs, actuals):
        arrived = departed + timedelta(minutes=int(actual))
        logs.append(post_flight_log(
            ctx["trip"]["id"], leg["id"], int(actual),
            _iso(departed), _iso(arrived), ctx["crew"]["id"]))
        departed = arrived + timedelta(minutes=30)
    ctx["flight_logs"] = logs
    ctx["trip"] = get_trip(ctx["trip"]["id"])
    ctx["aircraft"] = get_success_data(api_client.get_aircraft(ctx["aircraft"]["id"], OPS_ADMIN))
    ctx["statements"] = list_owner_statements(ctx["owner"]["id"])
    return ctx
