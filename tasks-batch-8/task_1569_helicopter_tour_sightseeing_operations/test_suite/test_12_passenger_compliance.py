"""Passenger waiver/briefing/check-in chain, seat numbers, uniqueness."""
from test_helpers import (
    ApiErrorId,
    check_in_passenger,
    complete_briefing,
    confirm_booking,
    create_booking,
    create_flight,
    get_booking,
    is_valid_uuid,
    list_passengers_for_booking,
    passenger_entry,
    setup_ops_env,
    sign_waiver,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_aircraft_payload,
    create_pilot_payload,
    create_route_payload,
)
from test_helpers.fixtures import create_aircraft, create_pilot, create_route

AGENT = TEST_USERS["booking_agent_headers"]
OPS = TEST_USERS["ops_admin_headers"]


def _confirmed_single_pax_booking(api, waiver="WAV-1", weight=150):
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", weight)])
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    pax = list_passengers_for_booking(booking["id"])[0]
    return env, flight, booking, pax


def test_sign_waiver_version_stale_rejected(api):
    """PRD §3.6: "Signing the waiver presents a `waiver_version` that must
    equal the booking's `waiver_version_pinned` — a mismatch means the base
    has rotated waiver text since the booking was created and is rejected
    with `ERR_WAIVER_VERSION_STALE`; a match sets `waiver_signed` true and
    records the version into `waiver_version_signed`."

    Design: Corner/validations/sign_waiver_version_stale_rejected
    """
    env = setup_ops_env(base_overrides={"current_waiver_version": "WAV-9"})
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])
    pax = list_passengers_for_booking(booking["id"])[0]

    resp = api.passenger_event(
        pax["id"], {"event_type": "SIGN_WAIVER", "waiver_version": "WAV-0"}, AGENT
    )
    validate_error(resp, ApiErrorId.ERR_WAIVER_VERSION_STALE)

    signed = sign_waiver(pax["id"], "WAV-9")
    assert signed["waiver_signed"] is True
    assert signed["waiver_version_signed"] == "WAV-9"


def test_check_in_requires_waiver_then_briefing(api):
    """PRD §3.6: "Check-in is the scale-and-seat moment, allowed while the
    booking is CONFIRMED or CHECKED_IN, with its guards evaluated in order:
    the waiver must be signed (`ERR_WAIVER_NOT_SIGNED`), the briefing
    completed (`ERR_BRIEFING_INCOMPLETE`), and the presented `seat_number`
    must lie within the aircraft's seat range — from 0 up to but not
    including `seat_capacity` — and not already be held by another checked-in
    passenger on the same flight (`ERR_SEAT_NUMBER_TAKEN`)."
    PRD §3.6: "A successful check-in records the scale-measured
    `actual_weight_lb` and the `seat_number`, flips `checked_in` true, and —
    when this was the booking's last unchecked passenger — automatically
    moves the booking CONFIRMED → CHECKED_IN."

    Design: Corner/validations/check_in_requires_waiver_then_briefing
    """
    env, flight, booking, pax = _confirmed_single_pax_booking(api)

    resp = api.passenger_event(
        pax["id"],
        {"event_type": "CHECK_IN", "actual_weight_lb": 150, "seat_number": 0},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_SIGNED)

    sign_waiver(pax["id"], "WAV-1")
    resp = api.passenger_event(
        pax["id"],
        {"event_type": "CHECK_IN", "actual_weight_lb": 150, "seat_number": 0},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_BRIEFING_INCOMPLETE)

    complete_briefing(pax["id"])
    checked = check_in_passenger(pax["id"], 150, 0)
    assert checked["checked_in"] is True
    # Last-passenger check-in auto-flips the booking.
    assert get_booking(booking["id"])["status"] == "CHECKED_IN"


def test_seat_number_taken_rejected(api):
    """PRD §3.6: "the presented `seat_number` must lie within the aircraft's
    seat range — from 0 up to but not including `seat_capacity` — and not
    already be held by another checked-in passenger on the same flight
    (`ERR_SEAT_NUMBER_TAKEN`)."

    Design: Corner/validations/seat_number_taken_rejected
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150),
                                            passenger_entry("P1", 150)])
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    pax0, pax1 = list_passengers_for_booking(booking["id"])
    sign_waiver(pax0["id"], "WAV-1")
    complete_briefing(pax0["id"])
    check_in_passenger(pax0["id"], 150, 0)
    sign_waiver(pax1["id"], "WAV-1")
    complete_briefing(pax1["id"])

    # Seat 0 is already held by the checked-in P0 on this flight.
    resp = api.passenger_event(
        pax1["id"],
        {"event_type": "CHECK_IN", "actual_weight_lb": 160, "seat_number": 0},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_NUMBER_TAKEN)

    # Seat 4 is outside [0, seat_capacity 4).
    resp = api.passenger_event(
        pax1["id"],
        {"event_type": "CHECK_IN", "actual_weight_lb": 160, "seat_number": 4},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_NUMBER_TAKEN)

    ok = check_in_passenger(pax1["id"], 160, 1)
    assert ok["checked_in"] is True
    assert ok["seat_number"] == 1


def test_creation_uniqueness_constraints(api):
    """PRD §3.5: "Two passengers in one booking may not share a `full_name` —
    `ERR_DUPLICATE_PASSENGER`."
    PRD §3.1: "Each carries a `route_code` unique across all routes"
    PRD §3.1: "Aircraft registration captures the tail as `tail_number`
    (unique across all aircraft, enforced with `ERR_UNIQUENESS_CONFLICT`)"
    PRD §3.1: "Pilot registration records a `display_name` and a
    `certificate_no` unique across all pilots (again
    `ERR_UNIQUENESS_CONFLICT`); a pilot begins AVAILABLE."

    Design: Corner/validations/creation_uniqueness_constraints
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    resp = api.create_booking(
        {
            "flight_id": flight["id"],
            "contact_name": "A",
            "contact_email": "a@x.com",
            "passengers": [passenger_entry("P0", 150),
                           passenger_entry("P0", 160)],
        },
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PASSENGER)

    resp = api.create_route(
        create_route_payload(route_code=env["route"]["route_code"], tier="GRAND",
                             duration_minutes=75, base_seat_price_cents=40000,
                             fuel_required_lb=600),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_UNIQUENESS_CONFLICT)

    resp = api.create_aircraft(
        create_aircraft_payload(
            tail_number=env["aircraft"]["tail_number"], seat_capacity=2,
            empty_weight_lb=1200, empty_moment_lb_in=60000,
            max_takeoff_weight_lb=2200, seat_arms_inches=[40, 80],
            noise_class="STANDARD",
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_UNIQUENESS_CONFLICT)

    resp = api.create_pilot(
        create_pilot_payload(display_name="Pat Uno",
                             certificate_no=env["pilot"]["certificate_no"]),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_UNIQUENESS_CONFLICT)


def test_booking_auto_flips_to_checked_in(api):
    """PRD §3.6: "A successful check-in records the scale-measured
    `actual_weight_lb` and the `seat_number`, flips `checked_in` true, and —
    when this was the booking's last unchecked passenger — automatically
    moves the booking CONFIRMED → CHECKED_IN."

    Design: Difficulty/non_linear_state_machine/booking_checkin_uncheck_revert_cycle
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150),
                                            passenger_entry("P1", 150)])
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    pax0, pax1 = list_passengers_for_booking(booking["id"])

    sign_waiver(pax0["id"], "WAV-1")
    complete_briefing(pax0["id"])
    check_in_passenger(pax0["id"], 150, 0)
    # Not the last unchecked passenger yet: still CONFIRMED.
    assert get_booking(booking["id"])["status"] == "CONFIRMED"

    sign_waiver(pax1["id"], "WAV-1")
    complete_briefing(pax1["id"])
    check_in_passenger(pax1["id"], 150, 1)
    assert get_booking(booking["id"])["status"] == "CHECKED_IN"


def test_uncheck_reverts_and_recheck_completes_cycle(api):
    """PRD §3.6: "Unchecking reverses it: `actual_weight_lb` and
    `seat_number` are cleared, `checked_in` returns false, and a booking
    sitting in CHECKED_IN reverts to CONFIRMED."
    PRD §3.6: "A successful check-in records the scale-measured
    `actual_weight_lb` and the `seat_number`, flips `checked_in` true, and —
    when this was the booking's last unchecked passenger — automatically
    moves the booking CONFIRMED → CHECKED_IN."

    Design: Difficulty/non_linear_state_machine/booking_checkin_uncheck_revert_cycle
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150),
                                            passenger_entry("P1", 150)])
    confirm_booking(booking["id"], booking["quoted_total_cents"])
    pax0, pax1 = list_passengers_for_booking(booking["id"])
    for pax, seat in ((pax0, 0), (pax1, 1)):
        sign_waiver(pax["id"], "WAV-1")
        complete_briefing(pax["id"])
        check_in_passenger(pax["id"], 150, seat)
    assert get_booking(booking["id"])["status"] == "CHECKED_IN"

    # Cycle step: one UNCHECK reverts the booking.
    unchecked = validate_success(
        api.passenger_event(pax0["id"], {"event_type": "UNCHECK"}, AGENT)
    )
    assert unchecked["checked_in"] is False
    assert unchecked["actual_weight_lb"] is None
    assert unchecked["seat_number"] is None
    assert get_booking(booking["id"])["status"] == "CONFIRMED"

    # The freed seat 0 is reclaimable; the loop closes a second time.
    rechecked = check_in_passenger(pax0["id"], 150, 0)
    assert rechecked["checked_in"] is True
    assert rechecked["seat_number"] == 0
    assert get_booking(booking["id"])["status"] == "CHECKED_IN"


def test_passengers_listed_in_pax_index_order(api):
    """PRD §3.6: "Passenger listings order rows by `pax_index` ascending
    within a booking."
    PRD §3.5: "its `Passenger` rows created with `pax_index` assigned 0, 1,
    2… in input order."

    Design: Corner/endpoints/passengers_listed_in_pax_index_order
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(
        flight["id"],
        [passenger_entry("Zed", 150), passenger_entry("Amy", 150),
         passenger_entry("Bob", 150)],
    )

    data, meta = validate_paginated(
        api.list_passengers(AGENT, params={"booking_id": booking["id"]})
    )
    assert meta["total_count"] == 3
    # Input order, not name order.
    assert [(p["full_name"], p["pax_index"]) for p in data] == [
        ("Zed", 0), ("Amy", 1), ("Bob", 2)
    ]
