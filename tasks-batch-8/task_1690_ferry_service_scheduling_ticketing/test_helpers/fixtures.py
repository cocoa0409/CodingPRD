"""Composite setup helpers for the ferry service test suite.

Most interesting claims require the system to be in a specific state that
takes 8-15 API calls to reach (route -> vessel -> fare schedule draft ->
submit -> approve -> sailing -> crew to manning minimums -> clock -> open
booking -> customer -> booking). These helpers encapsulate those chains so
tests can focus on assertions. All helpers use get_success_data() so setup
failures surface as clear "Setup step failed" errors.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MANNING_TABLE
from .factories import (
    create_booking_payload,
    create_crew_assignment_payload,
    create_crew_member_payload,
    create_customer_payload,
    create_fare_schedule_payload,
    create_route_payload,
    create_sailing_payload,
    create_standby_entry_payload,
    create_vessel_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["scheduler_admin_headers"]
TERMINAL = TEST_USERS["terminal_agent_headers"]
CREW = TEST_USERS["crew_planner_headers"]


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tier 0/1: single-entity creators and atomic state transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4). Returns {current_utc}."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(create_route_payload(**overrides), ADMIN))


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, ADMIN))


def create_vessel(**overrides) -> dict:
    return get_success_data(api_client.create_vessel(create_vessel_payload(**overrides), ADMIN))


def create_fare_schedule(route_id: str, route_version: int = None, **overrides) -> dict:
    """Create a DRAFT fare schedule under a route (OCC-guarded on the route's
    version, PRD §2.9). Reads the live route version when not supplied."""
    if route_version is None:
        route_version = get_route(route_id)["version"]
    payload = create_fare_schedule_payload(
        expected_route_version=route_version, **overrides
    )
    return get_success_data(api_client.create_fare_schedule(route_id, payload, ADMIN))


def submit_fare_schedule(fare_schedule_id: str, fuel_price_index_cents: int = 200) -> dict:
    return get_success_data(
        api_client.submit_fare_schedule(
            fare_schedule_id, {"fuel_price_index_cents": fuel_price_index_cents}, ADMIN
        )
    )


def approve_fare_schedule(fare_schedule_id: str) -> dict:
    return get_success_data(api_client.approve_fare_schedule(fare_schedule_id, ADMIN))


def submit_and_approve(fare_schedule_id: str, fuel_price_index_cents: int = 200) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED. Returns the APPROVED schedule."""
    submit_fare_schedule(fare_schedule_id, fuel_price_index_cents)
    return approve_fare_schedule(fare_schedule_id)


def create_sailing(route_id: str, vessel_id: str, **overrides) -> dict:
    payload = create_sailing_payload(vessel_id=vessel_id, **overrides)
    return get_success_data(api_client.create_sailing(route_id, payload, ADMIN))


def get_sailing(sailing_id: str) -> dict:
    return get_success_data(api_client.get_sailing(sailing_id, ADMIN))


def open_sailing(sailing_id: str) -> dict:
    return get_success_data(api_client.open_booking(sailing_id, ADMIN))


def close_sailing(sailing_id: str) -> dict:
    return get_success_data(api_client.close_booking(sailing_id, ADMIN))


def begin_boarding(sailing_id: str) -> dict:
    return get_success_data(api_client.begin_boarding(sailing_id, TERMINAL))


def depart_sailing(sailing_id: str) -> dict:
    return get_success_data(api_client.depart_sailing(sailing_id, TERMINAL))


def complete_sailing(sailing_id: str) -> dict:
    return get_success_data(api_client.complete_sailing(sailing_id, TERMINAL))


def cancel_sailing(sailing_id: str, cancel_reason: str = "WEATHER") -> dict:
    return get_success_data(
        api_client.cancel_sailing(sailing_id, {"cancel_reason": cancel_reason}, ADMIN)
    )


def create_customer(fare_class: str = "STANDARD", **overrides) -> dict:
    payload = create_customer_payload(fare_class=fare_class, **overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def create_crew_member(credential_class: str = "CAPTAIN", **overrides) -> dict:
    payload = create_crew_member_payload(credential_class=credential_class, **overrides)
    return get_success_data(api_client.create_crew_member(payload, CREW))


def get_crew_member(crew_member_id: str) -> dict:
    return get_success_data(api_client.get_crew_member(crew_member_id, CREW))


def create_crew_assignment(
    crew_member_id: str,
    sailing_id: str,
    shift_start: str = "2026-09-01T08:00:00Z",
    shift_end: str = "2026-09-01T16:00:00Z",
) -> dict:
    payload = create_crew_assignment_payload(
        crew_member_id=crew_member_id, shift_start=shift_start, shift_end=shift_end
    )
    return get_success_data(api_client.create_crew_assignment(sailing_id, payload, CREW))


def get_crew_assignment(assignment_id: str) -> dict:
    return get_success_data(api_client.get_crew_assignment(assignment_id, CREW))


def create_booking(
    sailing_id: str,
    customer: dict,
    passenger_count: int = 1,
    has_vehicle: bool = False,
    vehicle_length_feet=None,
    extra: dict = None,
) -> dict:
    """Create a booking as its owning customer (ownership-gated call threads
    the customer's real id through X-User-ID)."""
    payload = create_booking_payload(
        customer_id=customer["id"],
        passenger_count=passenger_count,
        has_vehicle=has_vehicle,
    )
    if vehicle_length_feet is not None:
        payload["vehicle_length_feet"] = vehicle_length_feet
    if extra:
        payload.update(extra)
    return get_success_data(
        api_client.create_booking(sailing_id, payload, make_customer_headers(customer["id"]))
    )


def confirm_booking(booking_id: str, customer: dict) -> dict:
    return get_success_data(
        api_client.confirm_booking(booking_id, make_customer_headers(customer["id"]))
    )


def get_booking(booking_id: str) -> dict:
    return get_success_data(api_client.get_booking(booking_id, ADMIN))


def join_standby(
    sailing_id: str,
    customer: dict,
    has_vehicle: bool = False,
    vehicle_length_feet=None,
    passenger_count: int = 1,
    priority_class: str = "STANDARD",
) -> dict:
    payload = create_standby_entry_payload(
        customer_id=customer["id"],
        has_vehicle=has_vehicle,
        passenger_count=passenger_count,
        priority_class=priority_class,
    )
    if vehicle_length_feet is not None:
        payload["vehicle_length_feet"] = vehicle_length_feet
    return get_success_data(
        api_client.join_standby_queue(
            sailing_id, payload, make_customer_headers(customer["id"])
        )
    )


def get_standby_entry(entry_id: str) -> dict:
    return get_success_data(api_client.get_standby_entry(entry_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2/3: crewing and bookable-sailing composites
# ---------------------------------------------------------------------------

def crew_sailing_to_class_minimum(sailing_id: str, crew_class: str, shift_date: str) -> dict:
    """Create and assign exactly the class-minimum crew complement (PRD §2.8)
    for a sailing, using fresh crew members with shifts on shift_date
    (08:00-16:00). Returns {"members": {credential: [member, ...]},
    "assignments": [assignment, ...]}."""
    members = {"CAPTAIN": [], "DECK": [], "ENGINE": []}
    assignments = []
    for credential, needed in MANNING_TABLE[crew_class].items():
        for _ in range(needed):
            member = create_crew_member(
                credential_class=credential, full_name=_uniq(credential.title())
            )
            assignment = create_crew_assignment(
                member["id"],
                sailing_id,
                shift_start=f"{shift_date}T08:00:00Z",
                shift_end=f"{shift_date}T16:00:00Z",
            )
            members[credential].append(member)
            assignments.append(assignment)
    return {"members": members, "assignments": assignments}


def setup_open_sailing(
    *,
    deck_feet: int = 200,
    passenger_capacity: int = 600,
    crew_class: str = "MEDIUM",
    season: str = "OFF_PEAK",
    departure_time: str = "2026-09-01T10:00:00Z",
    effective_from: str = "2026-08-01T00:00:00Z",
    effective_to: str = "2026-11-01T00:00:00Z",
    fuel_price_index_cents: int = 200,
    clock: str = "2026-08-15T00:00:00Z",
    route_overrides: dict = None,
    rate_overrides: dict = None,
    open_it: bool = True,
) -> dict:
    """Full chain: route -> vessel -> fare schedule (submitted + approved) ->
    sailing -> crew to class minimums -> (optional) clock set -> open booking.

    Returns {"route", "vessel", "fare_schedule", "sailing", "crew"}. The
    returned sailing reflects the state after open-booking when open_it is
    true (reserved_deck_allotment_feet pinned)."""
    route = create_route(**(route_overrides or {}))
    vessel = create_vessel(
        vehicle_deck_linear_feet=deck_feet,
        passenger_capacity=passenger_capacity,
        crew_class=crew_class,
    )
    fare_schedule = create_fare_schedule(
        route["id"],
        season=season,
        effective_from=effective_from,
        effective_to=effective_to,
        **(rate_overrides or {}),
    )
    fare_schedule = submit_and_approve(fare_schedule["id"], fuel_price_index_cents)
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time=departure_time, season=season
    )
    crew = crew_sailing_to_class_minimum(sailing["id"], crew_class, departure_time[:10])
    if clock is not None:
        set_clock(clock)
    if open_it:
        sailing = open_sailing(sailing["id"])
    return {
        "route": route,
        "vessel": vessel,
        "fare_schedule": fare_schedule,
        "sailing": sailing,
        "crew": crew,
    }


def setup_sailing_with_confirmed_booking(
    *,
    passenger_count: int = 1,
    has_vehicle: bool = True,
    vehicle_length_feet: int = 18,
    fare_class: str = "STANDARD",
    fuel_price_index_cents: int = 350,
    **sailing_kwargs,
) -> dict:
    """setup_open_sailing + one customer + one CONFIRMED booking.
    Returns the setup dict plus "customer" and "booking"."""
    setup = setup_open_sailing(fuel_price_index_cents=fuel_price_index_cents, **sailing_kwargs)
    customer = create_customer(fare_class=fare_class)
    booking = create_booking(
        setup["sailing"]["id"],
        customer,
        passenger_count=passenger_count,
        has_vehicle=has_vehicle,
        vehicle_length_feet=vehicle_length_feet if has_vehicle else None,
    )
    booking = confirm_booking(booking["id"], customer)
    setup.update({"customer": customer, "booking": booking})
    return setup


def setup_two_open_sailings(fuel_price_index_cents: int = 350) -> dict:
    """One route/vessel with TWO crewed OPEN_FOR_BOOKING OFF_PEAK sailings
    (2026-09-01 and 2026-09-02 departures) under one EFFECTIVE schedule.
    Used by rebook flows that need a target sailing. Returns the setup dict
    with "sailing" (first) and "sailing2" (second)."""
    setup = setup_open_sailing(fuel_price_index_cents=fuel_price_index_cents)
    sailing2 = create_sailing(
        setup["route"]["id"],
        setup["vessel"]["id"],
        departure_time="2026-09-02T10:00:00Z",
        season="OFF_PEAK",
    )
    crew_sailing_to_class_minimum(sailing2["id"], "MEDIUM", "2026-09-02")
    sailing2 = open_sailing(sailing2["id"])
    setup["sailing2"] = sailing2
    return setup
