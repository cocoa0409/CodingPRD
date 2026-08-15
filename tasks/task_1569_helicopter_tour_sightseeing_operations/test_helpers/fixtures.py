"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
broken precondition fails loudly with "Setup failed" instead of a confusing
assertion deep in a test.

The standard environment mirrors the canonical operating picture used across
the PRD walkthroughs: one base (quiet hours 01:00-13:00 UTC, waiver WAV-1),
one SHORT 25-minute route at 25000 cents with 300 lb planned fuel, one QUIET
4-seat helicopter (empty 1500 lb, MTOW 2600 lb, CG envelope 52-57 in), and one
pilot.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_aircraft_payload,
    create_base_payload,
    create_booking_payload,
    create_complaint_payload,
    create_pilot_payload,
    create_route_payload,
    create_season_payload,
    create_weather_observation_payload,
    passenger_entry,
)
from .test_users import TEST_USERS, make_pilot_headers

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]        # disp-1
DISP2 = TEST_USERS["dispatcher_2_headers"]     # disp-2
AGENT = TEST_USERS["booking_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
REPORTER = TEST_USERS["community_reporter_headers"]


# ─── Tier 0: logical clock + single-resource creators ─────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server's logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, OPS))


def create_base(**overrides):
    return get_success_data(api_client.create_base(create_base_payload(**overrides), OPS))


def create_route(**overrides):
    return get_success_data(api_client.create_route(create_route_payload(**overrides), OPS))


def create_season(**overrides):
    return get_success_data(api_client.create_season(create_season_payload(**overrides), OPS))


def create_aircraft(**overrides):
    return get_success_data(api_client.create_aircraft(create_aircraft_payload(**overrides), OPS))


def create_pilot(**overrides):
    return get_success_data(api_client.create_pilot(create_pilot_payload(**overrides), OPS))


def get_flight(flight_id, headers=None):
    return get_success_data(api_client.get_flight(flight_id, headers or DISP))


def get_booking(booking_id, headers=None):
    return get_success_data(api_client.get_booking(booking_id, headers or AGENT))


def get_base(base_id, headers=None):
    return get_success_data(api_client.get_base(base_id, headers or DISP))


def get_route(route_id, headers=None):
    return get_success_data(api_client.get_route(route_id, headers or OPS))


def get_pilot(pilot_id, headers=None):
    return get_success_data(api_client.get_pilot(pilot_id, headers or DISP))


def get_complaint(complaint_id, headers=None):
    return get_success_data(api_client.get_complaint(complaint_id, headers or OFFICER))


def get_credit(credit_id, headers=None):
    return get_success_data(api_client.get_credit(credit_id, headers or AGENT))


def list_credits_for_booking(booking_id):
    data, _meta = validate_paginated(
        api_client.list_credits(AGENT, params={"booking_id": booking_id})
    )
    return data


def list_passengers_for_booking(booking_id):
    data, _meta = validate_paginated(
        api_client.list_passengers(AGENT, params={"booking_id": booking_id})
    )
    return data


def list_duty_days(pilot_id, duty_date=None, headers=None):
    params = {"pilot_id": pilot_id}
    if duty_date:
        params["duty_date"] = duty_date
    data, _meta = validate_paginated(
        api_client.list_duty_days(headers or DISP, params=params)
    )
    return data


# ─── Tier 1: environment + flight creation ────────────────────────────────────

def setup_ops_env(clock="2026-08-03T00:00:00Z", base_overrides=None,
                  route_overrides=None, aircraft_overrides=None,
                  pilot_overrides=None):
    """Pin the logical clock, then create base + route + aircraft + pilot.

    Returns {"base": ..., "route": ..., "aircraft": ..., "pilot": ...}.
    """
    set_clock(clock)
    base = create_base(**(base_overrides or {}))
    route = create_route(**(route_overrides or {}))
    aircraft = create_aircraft(**(aircraft_overrides or {}))
    pilot = create_pilot(**(pilot_overrides or {}))
    return {"base": base, "route": route, "aircraft": aircraft, "pilot": pilot}


def create_flight(env, departure_utc, *, route=None, aircraft=None, pilot=None,
                  dispatcher=None):
    """Schedule a flight inside an environment built by setup_ops_env."""
    route = route or env["route"]
    aircraft = aircraft or env["aircraft"]
    pilot = pilot or env["pilot"]
    payload = {
        "base_id": env["base"]["id"],
        "route_id": route["id"],
        "aircraft_id": aircraft["id"],
        "pilot_id": pilot["id"],
        "scheduled_departure_utc": departure_utc,
    }
    return get_success_data(
        api_client.create_flight(payload, dispatcher or DISP)
    )


# ─── Tier 2: bookings and passengers ──────────────────────────────────────────

def create_booking(flight_id, passengers, **overrides):
    """Create a HELD booking. `passengers` is a list of passenger_entry() dicts."""
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(flight_id, passengers, **overrides), AGENT
        )
    )


def confirm_booking(booking_id, card_amount_cents):
    return get_success_data(
        api_client.confirm_booking(
            booking_id, {"card_amount_cents": card_amount_cents}, AGENT
        )
    )


def cancel_booking(booking_id):
    return get_success_data(
        api_client.booking_event(booking_id, {"event_type": "CANCEL"}, AGENT)
    )


def apply_credit(booking_id, credit_id):
    return get_success_data(
        api_client.apply_credit(booking_id, {"credit_id": credit_id}, AGENT)
    )


def sign_waiver(passenger_id, waiver_version):
    return get_success_data(
        api_client.passenger_event(
            passenger_id,
            {"event_type": "SIGN_WAIVER", "waiver_version": waiver_version},
            AGENT,
        )
    )


def complete_briefing(passenger_id):
    return get_success_data(
        api_client.passenger_event(
            passenger_id, {"event_type": "COMPLETE_BRIEFING"}, AGENT
        )
    )


def check_in_passenger(passenger_id, actual_weight_lb, seat_number):
    return get_success_data(
        api_client.passenger_event(
            passenger_id,
            {
                "event_type": "CHECK_IN",
                "actual_weight_lb": actual_weight_lb,
                "seat_number": seat_number,
            },
            AGENT,
        )
    )


def check_in_booking(booking_id, actual_weight_lb, waiver_version="WAV-1",
                     first_seat=0):
    """Sign + brief + check in every passenger of a booking, in pax_index order.

    `actual_weight_lb` is either a scalar applied to every passenger or a list
    parallel to the booking's passengers. Returns the passenger list.
    """
    passengers = list_passengers_for_booking(booking_id)
    if not isinstance(actual_weight_lb, (list, tuple)):
        actual_weight_lb = [actual_weight_lb] * len(passengers)
    for i, pax in enumerate(passengers):
        sign_waiver(pax["id"], waiver_version)
        complete_briefing(pax["id"])
        check_in_passenger(pax["id"], actual_weight_lb[i], first_seat + i)
    return list_passengers_for_booking(booking_id)


# ─── Tier 3: flight lifecycle shortcuts ───────────────────────────────────────

def pilot_ack(flight_id, pilot_id):
    """PILOT_ACK self-transition; the entity-backed pilot acks their own flight."""
    return get_success_data(
        api_client.flight_event(
            flight_id, {"event_type": "PILOT_ACK"}, make_pilot_headers(pilot_id)
        )
    )


def open_boarding(flight_id, dispatcher=None):
    return get_success_data(
        api_client.flight_event(
            flight_id, {"event_type": "OPEN_BOARDING"}, dispatcher or DISP
        )
    )


def close_manifest(flight_id, dispatcher=None):
    """Close the manifest from BOARDING, capturing the OCC version first."""
    flight = get_flight(flight_id)
    return get_success_data(
        api_client.close_manifest(
            flight_id,
            {"expected_flight_version": flight["version"]},
            dispatcher or DISP,
        )
    )


def dispatch_flight(flight_id, dispatcher=None):
    return get_success_data(
        api_client.flight_event(
            flight_id, {"event_type": "DISPATCH"}, dispatcher or DISP2
        )
    )


def complete_flight(flight_id, dispatcher=None):
    return get_success_data(
        api_client.flight_event(
            flight_id, {"event_type": "COMPLETE"}, dispatcher or DISP2
        )
    )


def carry_flight_to_manifest_closed(flight_id, pilot_id, dispatcher=None):
    """PILOT_ACK (while SCHEDULED) -> OPEN_BOARDING -> close-manifest."""
    pilot_ack(flight_id, pilot_id)
    open_boarding(flight_id, dispatcher=dispatcher)
    return close_manifest(flight_id, dispatcher=dispatcher)


def fly_empty_flight(flight_id, pilot_id, *, depart_at, complete_at,
                     creator_dispatcher=None, dispatch_dispatcher=None):
    """Walk a zero-passenger flight to COMPLETED.

    ack (SCHEDULED) -> open boarding -> close manifest -> clock to depart_at ->
    DISPATCH -> clock to complete_at -> COMPLETE. Returns the COMPLETED flight.
    """
    carry_flight_to_manifest_closed(
        flight_id, pilot_id, dispatcher=creator_dispatcher
    )
    set_clock(depart_at)
    dispatch_flight(flight_id, dispatcher=dispatch_dispatcher)
    set_clock(complete_at)
    return complete_flight(flight_id, dispatcher=dispatch_dispatcher)


# ─── Tier 4: threshold / accumulation setups ──────────────────────────────────

def setup_pilot_at_scheduled_minutes(route_duration_min, legs, departures,
                                     clock="2026-08-03T00:00:00Z"):
    """Environment with one pilot holding `legs` flights of one route.

    Returns (env, flights). Used to place flight_minutes_scheduled at an exact
    cumulative value (e.g. 240 + 240 == 480) before a boundary probe.
    """
    env = setup_ops_env(
        clock=clock,
        route_overrides={
            "route_code": "RD",
            "tier": "STANDARD",
            "duration_minutes": route_duration_min,
            "base_seat_price_cents": 10000,
            "fuel_required_lb": 400,
        },
    )
    flights = [create_flight(env, dep) for dep in departures]
    return env, flights


def setup_completed_flight(base_overrides=None, route_overrides=None,
                           departure="2026-08-03T14:00:00Z",
                           depart_at="2026-08-03T14:00:00Z",
                           complete_at="2026-08-03T15:00:00Z",
                           clock="2026-08-03T00:00:00Z"):
    """Environment plus one zero-passenger COMPLETED flight.

    Returns (env, completed_flight). Used by complaint auto-match / quota tests
    that need a flown flight in the match pool.
    """
    env = setup_ops_env(
        clock=clock,
        base_overrides=base_overrides,
        route_overrides=route_overrides,
    )
    flight = create_flight(env, departure, dispatcher=DISP)
    completed = fly_empty_flight(
        flight["id"], env["pilot"]["id"],
        depart_at=depart_at, complete_at=complete_at,
        creator_dispatcher=DISP, dispatch_dispatcher=DISP2,
    )
    return env, completed


# ─── Tier 5: complaints and credits ───────────────────────────────────────────

def file_complaint(base_id, zone, observed_at, **overrides):
    return get_success_data(
        api_client.create_complaint(
            create_complaint_payload(base_id, zone, observed_at, **overrides),
            REPORTER,
        )
    )


def complaint_event(complaint_id, event_type, **fields):
    payload = {"event_type": event_type}
    payload.update(fields)
    return get_success_data(
        api_client.complaint_event(complaint_id, payload, OFFICER)
    )


def substantiate_complaint(complaint_id):
    """LOGGED -> UNDER_REVIEW -> SUBSTANTIATED."""
    complaint_event(complaint_id, "REVIEW")
    return complaint_event(complaint_id, "SUBSTANTIATE")


def mint_credit_via_ops_cancellation(paid_cents=25000, passenger_weight=150):
    """Create a flight + CONFIRMED booking, CANCEL_OPS the flight, return the
    minted RebookingCredit (face value paid_cents + credits_applied_cents).

    Returns (env, flight, booking, credit).
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-04T14:00:00Z")
    booking = create_booking(
        flight["id"], [passenger_entry("PZ", passenger_weight)]
    )
    confirm_booking(booking["id"], paid_cents)
    get_success_data(
        api_client.flight_event(
            flight["id"], {"event_type": "CANCEL_OPS", "reason": "manual"}, DISP
        )
    )
    credits = list_credits_for_booking(booking["id"])
    assert len(credits) == 1, "Setup failed: expected exactly one minted credit"
    return env, flight, booking, credits[0]
