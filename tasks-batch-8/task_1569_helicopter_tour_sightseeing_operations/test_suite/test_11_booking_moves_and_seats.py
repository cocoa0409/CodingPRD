"""Booking moves (settlement waterfall) and seat conservation / capacity."""
from test_helpers import (
    ApiErrorId,
    apply_credit,
    assert_seat_conservation,
    cancel_booking,
    confirm_booking,
    create_aircraft,
    create_booking,
    create_flight,
    create_pilot,
    get_booking,
    get_flight,
    is_valid_uuid,
    list_credits_for_booking,
    mint_credit_via_ops_cancellation,
    passenger_entry,
    setup_ops_env,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import create_season

AGENT = TEST_USERS["booking_agent_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_booking_move_positive_delta_relocks_quote(api):
    """PRD §3.8: "When the delta is positive, `additional_card_cents` must
    equal it exactly (`ERR_PAYMENT_AMOUNT_MISMATCH`) and `paid_cents` grows
    by it."
    PRD §3.8: "Finally the booking relocks: `flight_id` points at the new
    flight, `quoted_per_seat_cents`, `quoted_total_cents`, and `season_id`
    take the new quote's values, `credits_applied_cents` is recomposed as the
    new `quoted_total_cents` minus the new `paid_cents`, and the booking's
    `version` increments by one."
    PRD §3.8: "The quote recomputes against the new flight — its season, its
    load, its weekend."

    Design: Corner/state_machines/booking_move_positive_delta_relocks_quote
    """
    env = setup_ops_env()
    s1 = create_season(label="S1", start_date="2026-08-01",
                       end_date="2026-09-01", multiplier_bps=12000)
    f1 = create_flight(env, "2026-08-05T14:00:00Z")  # Wednesday
    f2 = create_flight(env, "2026-08-08T14:00:00Z")  # Saturday
    b1 = create_booking(f1["id"], [passenger_entry("P0", 150)])
    assert b1["quoted_total_cents"] == 30000  # 25000 * 1.20, base load
    confirm_booking(b1["id"], 30000)
    version_after_confirm = get_booking(b1["id"])["version"]

    # New flight's quote: season 12000 then weekend 11000 -> 30000 -> 33000.
    moved = validate_success(
        api.move_booking(
            b1["id"],
            {"new_flight_id": f2["id"],
             "expected_booking_version": version_after_confirm,
             "additional_card_cents": 3000},
            AGENT,
        )
    )
    assert moved["status"] == "CONFIRMED"
    assert moved["flight_id"] == f2["id"]
    assert moved["quoted_per_seat_cents"] == 33000
    assert moved["quoted_total_cents"] == 33000
    assert moved["paid_cents"] == 33000  # 30000 + 3000 exact delta
    assert moved["season_id"] == s1["id"]
    assert moved["version"] == version_after_confirm + 1

    # The seat moved between flights.
    assert get_flight(f1["id"])["seats_booked"] == 0
    assert get_flight(f2["id"])["seats_booked"] == 1


def test_move_negative_delta_waterfall_card_then_credit(api):
    """PRD §3.8: "When negative, the card refund is the smaller of the
    delta's magnitude and `paid_cents`; any excess beyond what the card can
    absorb is minted as a `RebookingCredit`."
    PRD §3.8: "Finally the booking relocks: `flight_id` points at the new
    flight, `quoted_per_seat_cents`, `quoted_total_cents`, and `season_id`
    take the new quote's values, `credits_applied_cents` is recomposed as the
    new `quoted_total_cents` minus the new `paid_cents`, and the booking's
    `version` increments by one."

    Design: Corner/calculations/move_negative_delta_waterfall_card_then_credit
    """
    # A 25000 credit minted by an ops-cancelled booking on an earlier flight.
    env, _f0, _b0, c0 = mint_credit_via_ops_cancellation()
    cheap_route = None
    from test_helpers.fixtures import create_route
    cheap_route = create_route(route_code="R2", base_seat_price_cents=10000)
    f1 = create_flight(env, "2026-08-12T14:00:00Z")  # Wednesday
    f2 = create_flight(env, "2026-10-05T14:00:00Z", route=cheap_route)  # Monday

    # Season created AFTER the credit was minted covers the new booking.
    create_season(label="S1", start_date="2026-08-01", end_date="2026-09-01",
                  multiplier_bps=12000)
    b1 = create_booking(f1["id"], [passenger_entry("P0", 150)])
    assert b1["quoted_total_cents"] == 30000
    applied = apply_credit(b1["id"], c0["id"])
    assert applied["credits_applied_cents"] == 25000
    confirm_booking(b1["id"], 5000)  # 30000 - 25000 balance
    version_after_confirm = get_booking(b1["id"])["version"]

    # Target quote 10000 -> delta -20000; card absorbs min(20000, 5000).
    moved = validate_success(
        api.move_booking(
            b1["id"],
            {"new_flight_id": f2["id"],
             "expected_booking_version": version_after_confirm},
            AGENT,
        )
    )
    assert moved["status"] == "CONFIRMED"
    assert moved["flight_id"] == f2["id"]
    assert moved["quoted_total_cents"] == 10000
    assert moved["refunded_card_cents"] == 5000
    assert moved["paid_cents"] == 5000
    # No PUBLISHED season covers 2026-10-05 -> fallback, season_id null.
    assert moved["season_id"] is None
    # Recomposed: 10000 - 5000.
    assert moved["credits_applied_cents"] == 5000

    # The 15000 overflow is minted as a fresh credit.
    credits = list_credits_for_booking(b1["id"])
    assert len(credits) == 1
    assert credits[0]["amount_cents"] == 15000
    assert credits[0]["status"] == "ISSUED"


def test_held_bookings_consume_seats_immediately(api):
    """PRD §3.3: "Three load figures track the flight's bookings:
    `seats_booked` sums `seat_count` over bookings in HELD, CONFIRMED,
    CHECKED_IN, or MANIFESTED; `seats_available` is the aircraft's
    `seat_capacity` minus `seats_booked`"

    Design: Difficulty/compensating_invariant/seat_conservation_across_hold_and_cancel
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")

    fresh = get_flight(flight["id"])
    assert (fresh["seats_booked"], fresh["seats_available"]) == (0, 4)
    assert_seat_conservation(fresh, 4)

    # HELD bookings count toward seats_booked.
    b1 = create_booking(flight["id"], [passenger_entry("P0", 100),
                                       passenger_entry("P1", 100)],
                        contact_name="A", contact_email="a@x.com")
    b2 = create_booking(flight["id"], [passenger_entry("P2", 100)],
                        contact_name="B", contact_email="b@x.com")
    after = get_flight(flight["id"])
    assert (after["seats_booked"], after["seats_available"]) == (3, 1)
    assert_seat_conservation(after, 4)

    # Compensating cancels restore the conserved seat count with zero drift.
    cancel_booking(b2["id"])
    assert_seat_conservation(get_flight(flight["id"]), 4)
    cancel_booking(b1["id"])
    final = get_flight(flight["id"])
    assert (final["seats_booked"], final["seats_available"]) == (0, 4)


def test_cancels_restore_seat_conservation(api):
    """PRD §3.8: "Cancelling from HELD is free: any applied credits release
    back to their original `RebookingCredit` rows — each credit's
    `redeemed_cents` is reduced by what it contributed and its status
    recomputed — and the seats release."
    PRD §3.3: "Three load figures track the flight's bookings: `seats_booked`
    sums `seat_count` over bookings in HELD, CONFIRMED, CHECKED_IN, or
    MANIFESTED; `seats_available` is the aircraft's `seat_capacity` minus
    `seats_booked`"

    Design: Difficulty/compensating_invariant/seat_conservation_across_hold_and_cancel
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    b1 = create_booking(flight["id"], [passenger_entry("P0", 100),
                                       passenger_entry("P1", 100)],
                        contact_name="A", contact_email="a@x.com")
    b2 = create_booking(flight["id"], [passenger_entry("P2", 100)],
                        contact_name="B", contact_email="b@x.com")

    cancel_booking(b2["id"])
    mid = get_flight(flight["id"])
    assert (mid["seats_booked"], mid["seats_available"]) == (2, 2)

    cancel_booking(b1["id"])
    final = get_flight(flight["id"])
    assert (final["seats_booked"], final["seats_available"]) == (0, 4)
    assert_seat_conservation(final, 4)


def test_booking_filling_last_seat_allowed(api):
    """PRD §3.5: "Capacity then requires the new `seat_count` — the number of
    passengers on the booking — to be no more than the flight's
    `seats_available`, with equality filling the flight exactly, allowed;
    overflow is `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_then_overflow
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    create_booking(flight["id"], [passenger_entry(f"P{i}", 100) for i in range(3)],
                   contact_name="A", contact_email="a@x.com")

    # The exact 4th seat: equality fills the flight exactly, allowed.
    b2 = create_booking(flight["id"], [passenger_entry("P3", 100)],
                        contact_name="B", contact_email="b@x.com")
    assert is_valid_uuid(b2["id"])
    full = get_flight(flight["id"])
    assert full["seats_booked"] == 4
    assert full["seats_available"] == 0


def test_booking_beyond_full_flight_rejected(api):
    """PRD §3.5: "Capacity then requires the new `seat_count` — the number of
    passengers on the booking — to be no more than the flight's
    `seats_available`, with equality filling the flight exactly, allowed;
    overflow is `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/seat_capacity_exact_fill_then_overflow
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    create_booking(flight["id"], [passenger_entry(f"P{i}", 100) for i in range(3)],
                   contact_name="A", contact_email="a@x.com")
    create_booking(flight["id"], [passenger_entry("P3", 100)],
                   contact_name="B", contact_email="b@x.com")

    # 1 seat requested, 0 available -> overflow.
    resp = api.create_booking(
        {
            "flight_id": flight["id"],
            "contact_name": "C",
            "contact_email": "c@x.com",
            "passengers": [passenger_entry("P4", 100)],
        },
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED)

    bookings, meta = validate_paginated(
        api.list_bookings(AGENT, params={"flight_id": flight["id"]})
    )
    assert meta["total_count"] == 2, "rejected create persists nothing"


def test_assignment_safety_beats_turn_conflict(api):
    """PRD §2.9: "Every endpoint evaluates its guards in a fixed global
    order, and a failure at an earlier rung masks every later one."
    PRD §2.9: "7. **Business safety rules** — posture, availability, duty
    limits, noise class, quiet hours, weight and balance, segregation of
    duties, in the relative order stated with each workflow in §3."
    PRD §2.9: "8. **Business temporal rules** — departure in the future,
    season windows, turn and overlap conflicts, hold liveness."
    PRD §3.3: "Crew changes happen through the OCC-guarded reassignment
    (§2.6), legitimate while the flight is SCHEDULED or DELAYED, accepting an
    optional `pilot_id` and/or `aircraft_id` alongside
    `expected_flight_version`; the duty, turn, noise, and availability gates
    re-run for the new crew, and the flight's `version` increments."

    Design: Difficulty/priority_pair_validation_conflict/assignment_safety_beats_turn_conflict
    """
    route_240 = {"route_code": "RD", "tier": "STANDARD", "duration_minutes": 240,
                 "base_seat_price_cents": 10000, "fuel_required_lb": 400}
    env = setup_ops_env(route_overrides=route_240)
    a2 = create_aircraft(tail_number="N2")
    p1 = env["pilot"]
    p2 = create_pilot(display_name="Pat Two", certificate_no="C2")
    # P2 already carries 240 + 240 == 480 scheduled minutes on A1.
    create_flight(env, "2026-08-03T08:00:00Z", pilot=p2)
    create_flight(env, "2026-08-03T13:00:00Z", pilot=p2)
    # Target flight FT dep 12:10 with P1 + A2 — cleanly created.
    ft = create_flight(env, "2026-08-03T12:10:00Z", aircraft=a2, pilot=p1)

    # Patching FT to {pilot P2, aircraft A1} violates the duty gate
    # (480 + 240 == 720 > 480) AND A1's turn buffer (12:10 < 12:00 + 25).
    # Duty is business safety; turn conflict is business temporal — safety
    # masks temporal.
    resp = api.update_flight_assignment(
        ft["id"],
        {"expected_flight_version": ft["version"],
         "pilot_id": p2["id"], "aircraft_id": env["aircraft"]["id"]},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_FLIGHT_TIME_EXCEEDED)


def test_failed_assignment_patch_leaves_crew_unchanged(api):
    """PRD §2.9: "Every endpoint evaluates its guards in a fixed global
    order, and a failure at an earlier rung masks every later one."
    PRD §2.6: "if that value does not match the parent resource's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.3: "Crew changes happen through the OCC-guarded reassignment
    (§2.6), legitimate while the flight is SCHEDULED or DELAYED, accepting an
    optional `pilot_id` and/or `aircraft_id` alongside
    `expected_flight_version`; the duty, turn, noise, and availability gates
    re-run for the new crew, and the flight's `version` increments."

    Design: Difficulty/priority_pair_validation_conflict/assignment_safety_beats_turn_conflict
    """
    route_240 = {"route_code": "RD", "tier": "STANDARD", "duration_minutes": 240,
                 "base_seat_price_cents": 10000, "fuel_required_lb": 400}
    env = setup_ops_env(route_overrides=route_240)
    a2 = create_aircraft(tail_number="N2")
    p1 = env["pilot"]
    p2 = create_pilot(display_name="Pat Two", certificate_no="C2")
    create_flight(env, "2026-08-03T08:00:00Z", pilot=p2)
    create_flight(env, "2026-08-03T13:00:00Z", pilot=p2)
    ft = create_flight(env, "2026-08-03T12:10:00Z", aircraft=a2, pilot=p1)

    resp = api.update_flight_assignment(
        ft["id"],
        {"expected_flight_version": ft["version"],
         "pilot_id": p2["id"], "aircraft_id": env["aircraft"]["id"]},
        DISP,
    )
    validate_error(resp, ApiErrorId.ERR_PILOT_FLIGHT_TIME_EXCEEDED)

    after = get_flight(ft["id"])
    assert after["pilot_id"] == p1["id"], "rejected patch leaves pilot unchanged"
    assert after["aircraft_id"] == a2["id"], "rejected patch leaves aircraft unchanged"


def test_cancelled_booking_terminal_lockdown(api):
    """PRD §2.9: "6. **State** — the target resource is in a state that
    permits the requested transition; terminal states reject every
    transition. Failure: `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.8: "Cancelling from HELD is free: any applied credits release back
    to their original `RebookingCredit` rows — each credit's `redeemed_cents`
    is reduced by what it contributed and its status recomputed — and the
    seats release."

    Design: Corner/state_machines/cancelled_booking_terminal_lockdown
    """
    env = setup_ops_env()
    flight = create_flight(env, "2026-08-03T14:00:00Z")
    booking = create_booking(flight["id"], [passenger_entry("P0", 150)])

    cancelled = cancel_booking(booking["id"])
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["paid_cents"] == 0
    assert cancelled["refunded_card_cents"] == 0

    resp = api.confirm_booking(booking["id"], {"card_amount_cents": 25000}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.booking_event(booking["id"], {"event_type": "CANCEL"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = get_booking(booking["id"])
    assert after["status"] == "CANCELLED"
    assert after["paid_cents"] == 0
    assert after["refunded_card_cents"] == 0
