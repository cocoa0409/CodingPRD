"""Dispatch: fleet guards, capacity, SLA window, leg creation side effects."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    confirm_trip,
    create_aircraft,
    create_trip,
    dispatch_trip,
    get_aircraft,
    get_trip_legs,
    set_clock,
    setup_active_card,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]


def test_pax_exceeds_aircraft_capacity(api):
    """PRD §3.6: "A third check compares `pax_count` against the chosen aircraft's
    `seats`; when the passenger count exceeds the seat count the dispatch is rejected
    with `ERR_PAX_EXCEEDS_CAPACITY` (HTTP 422)."

    Design: Corner/validations/pax_exceeds_aircraft_capacity
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "VAL2"})
    aircraft = create_aircraft(tail_number="N555LT", seats=6)
    trip = create_trip(card["id"], member["id"], pax_count=10)
    confirm_trip(trip["id"], member["id"])
    resp = api.dispatch_trip(trip["id"], {"dispatched_aircraft_id": aircraft["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_PAX_EXCEEDS_CAPACITY, expected_status=422)


def test_no_aircraft_available_dispatch_fails(api):
    """PRD §3.6: "The fleet guard requires at least one aircraft with a compatible
    category — either the requested category or one reachable via the swap ratios — in
    `AVAILABLE` status; an empty eligible set rejects with `ERR_NO_AIRCRAFT_AVAILABLE`
    (HTTP 422)."
    PRD §2.5: "Identifiers supplied in the request body rather than the path (such as
    `program_id` when purchasing a card, or `dispatched_aircraft_id` at dispatch) are
    validated after path resolution and fail with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)
    when they do not resolve."

    Design: Corner/validations/no_aircraft_available_dispatch_fails
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "VAL3"})
    trip = create_trip(card["id"], member["id"])
    confirm_trip(trip["id"], member["id"])
    resp = api.dispatch_trip(trip["id"], {"dispatched_aircraft_id": NON_EXISTENT_UUID}, OPS)
    actual = validate_error_is_one_of(
        resp, [ApiErrorId.ERR_NO_AIRCRAFT_AVAILABLE, ApiErrorId.ERR_REFERENCE_NOT_FOUND]
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({actual})"


def test_dispatch_creates_planned_legs(api):
    """PRD §3.6: "Successful dispatch moves the trip from `CONFIRMED` to `DISPATCHED` and
    fans out several effects: the chosen aircraft transitions from `AVAILABLE` to
    `IN_SERVICE`; `sla_met` records whether dispatch occurred within the availability
    window of the requested departure; `swap_applied` records whether the dispatched
    aircraft's category differs from `requested_category`; and the trip's `TripLeg`
    records come into existence in `PLANNED` status — one leg (`leg_seq` 1, outbound) for
    a one-way trip, two legs (`leg_seq` 1 outbound, `leg_seq` 2 return) for a round-trip."

    Design: Corner/state_machines/side_effect_trip_dispatch_creates_legs
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "SM4"})
    aircraft = create_aircraft(tail_number="N222LT")
    trip = create_trip(
        card["id"], member["id"],
        trip_kind="ROUND_TRIP",
        requested_departure_utc="2026-06-15T15:00:00Z",
        requested_return_utc="2026-06-17T15:00:00Z",
    )
    confirm_trip(trip["id"], member["id"])
    data = dispatch_trip(trip["id"], aircraft["id"])
    assert data["trip_status"] == "DISPATCHED"
    legs = get_trip_legs(trip["id"])
    assert len(legs) == 2, f"round-trip dispatch must create exactly 2 legs, got {len(legs)}"
    for leg in legs:
        assert leg["leg_status"] == "PLANNED", (
            f"new legs must be PLANNED, got {leg['leg_status']}"
        )
    ac = get_aircraft(aircraft["id"])
    assert ac["aircraft_status"] == "IN_SERVICE", (
        f"dispatched aircraft must be IN_SERVICE, got {ac['aircraft_status']}"
    )


def test_dispatch_after_availability_window_rejected(api):
    """PRD §3.6: "The temporal guard requires dispatch to occur within the program's
    `availability_window_hours` of `requested_departure_utc`; missing the window rejects
    with `ERR_SLA_WINDOW_MISSED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/sla_window_availability_availability_window_hours
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "OVL2"})
    aircraft = create_aircraft(tail_number="N800LT")
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-06-15T15:00:00Z")
    confirm_trip(trip["id"], member["id"])
    # 33 hours after the requested departure — past the 24-hour availability window.
    set_clock("2026-06-17T00:00:00Z")
    resp = api.dispatch_trip(trip["id"], {"dispatched_aircraft_id": aircraft["id"]}, OPS)
    validate_error(resp, ApiErrorId.ERR_SLA_WINDOW_MISSED, expected_status=422)


def test_dispatch_within_availability_window_sets_sla_met(api):
    """PRD §3.6: "Successful dispatch moves the trip from `CONFIRMED` to `DISPATCHED` and
    fans out several effects: the chosen aircraft transitions from `AVAILABLE` to
    `IN_SERVICE`; `sla_met` records whether dispatch occurred within the availability
    window of the requested departure; `swap_applied` records whether the dispatched
    aircraft's category differs from `requested_category`; and the trip's `TripLeg`
    records come into existence in `PLANNED` status — one leg (`leg_seq` 1, outbound) for
    a one-way trip, two legs (`leg_seq` 1 outbound, `leg_seq` 2 return) for a round-trip."

    Design: Difficulty/resource_temporal_overlap/sla_window_availability_availability_window_hours
    """
    _, member, card = setup_active_card(program_overrides={"program_code": "OVL2B"})
    aircraft = create_aircraft(tail_number="N801LT")
    trip = create_trip(card["id"], member["id"],
                       requested_departure_utc="2026-06-15T15:00:00Z")
    confirm_trip(trip["id"], member["id"])
    # 19 hours after the requested departure — inside the 24-hour window.
    set_clock("2026-06-16T10:00:00Z")
    resp = api.dispatch_trip(trip["id"], {"dispatched_aircraft_id": aircraft["id"]}, OPS)
    data = validate_success(resp, expected_status=200)
    assert data["trip_status"] == "DISPATCHED"
    assert data["sla_met"] is True, (
        f"dispatch 19h after request with a 24h window must set sla_met true, "
        f"got {data['sla_met']}"
    )
