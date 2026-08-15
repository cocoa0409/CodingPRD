"""Sailing lifecycle: initial state, the full happy-path voyage, the
departure no-show sweep, terminal-state lockdown, and the effective-schedule
gate at open-booking."""
from test_helpers import (
    ApiErrorId,
    assert_sailing,
    begin_boarding,
    close_sailing,
    complete_sailing,
    create_fare_schedule,
    create_route,
    create_sailing,
    create_vessel,
    crew_sailing_to_class_minimum,
    depart_sailing,
    get_booking,
    get_crew_assignment,
    get_crew_member,
    get_customer,
    get_sailing,
    setup_sailing_with_confirmed_booking,
    submit_and_approve,
    validate_error,
    validate_success,
)


def test_sailing_starts_scheduled_with_computed_arrival(api, scheduler_admin_headers):
    """PRD §3.3: "The server stamps `arrival_time` as the departure instant
    plus the route's `crossing_minutes`, sets `status` to `SCHEDULED`, and
    enforces the vessel-overlap rule of §3.1."

    Design: Corner/state_machines/sailing_initial_state_scheduled
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z", season="OFF_PEAK"
    )
    assert_sailing(sailing)
    assert sailing["status"] == "SCHEDULED", (
        f"new sailing must start SCHEDULED, got {sailing['status']}"
    )
    # 10:00 departure + 35-minute crossing -> 10:35 arrival. Compared as
    # instants: PRD §2.5 requires only that arrival_time be an ISO 8601 UTC
    # instant and does not pin the fractional-digit rendering.
    from datetime import datetime
    expected = datetime.fromisoformat("2026-09-01T10:35:00Z")
    actual = datetime.fromisoformat(sailing["arrival_time"])
    assert actual == expected, (
        f"arrival_time must be departure + crossing_minutes, got {sailing['arrival_time']}"
    )


def test_full_voyage_happy_path_completes(api, terminal_agent_headers):
    """PRD §3.7: "A `TerminalAgent` completes a `DEPARTED` sailing (`DEPARTED
    → COMPLETED`): all `BOARDED` bookings become `COMPLETED`, all crew
    assignments still `ASSIGNED` are released, and each crew member left with
    no remaining `ASSIGNED` assignments anywhere returns to `AVAILABLE`."
    PRD §3.7: "A `TerminalAgent` checks in a `CONFIRMED` booking (`CONFIRMED →
    CHECKED_IN`) once the sailing has closed booking — check-in is legal in
    `BOOKING_CLOSED` or `BOARDING` — and boards it (`CHECKED_IN → BOARDED`)
    once the sailing is `BOARDING`."

    Design: Corner/state_machines/full_sailing_happy_path_completes
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=1, has_vehicle=True, vehicle_length_feet=18
    )
    sailing_id = setup["sailing"]["id"]
    booking = setup["booking"]
    crew_assignment = setup["crew"]["assignments"][0]
    crew_member_id = crew_assignment["crew_member_id"]

    close_sailing(sailing_id)
    checked_in = validate_success(
        api.check_in_booking(booking["id"], terminal_agent_headers)
    )
    assert checked_in["status"] == "CHECKED_IN"

    boarding = begin_boarding(sailing_id)
    assert boarding["status"] == "BOARDING"

    boarded = validate_success(api.board_booking(booking["id"], terminal_agent_headers))
    assert boarded["status"] == "BOARDED"

    departed = depart_sailing(sailing_id)
    assert departed["status"] == "DEPARTED"

    completed = complete_sailing(sailing_id)
    assert_sailing(completed)
    assert completed["status"] == "COMPLETED"

    final_booking = get_booking(booking["id"])
    assert final_booking["status"] == "COMPLETED", (
        f"boarded booking must complete with its sailing, got {final_booking['status']}"
    )
    final_assignment = get_crew_assignment(crew_assignment["id"])
    assert final_assignment["status"] == "RELEASED"
    final_member = get_crew_member(crew_member_id)
    assert final_member["status"] == "AVAILABLE", (
        "member with no remaining ASSIGNED assignments must return to AVAILABLE"
    )


def test_departure_marks_unchecked_bookings_no_show(api):
    """PRD §3.7: "every booking still `CONFIRMED` or `MODIFIED` — reserved,
    settled, but never checked in — becomes `NO_SHOW` with its fare forfeited
    (no refund credit is issued), and its vehicle feet and passenger counts
    are released as the counters are recomputed"

    Design: Corner/state_machines/booking_depart_no_show_sweep
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=1, has_vehicle=True, vehicle_length_feet=18
    )
    sailing_id = setup["sailing"]["id"]
    booking = setup["booking"]
    customer = setup["customer"]
    assert get_sailing(sailing_id)["reserved_vehicle_feet"] == 18

    close_sailing(sailing_id)
    begin_boarding(sailing_id)
    departed = depart_sailing(sailing_id)
    assert departed["status"] == "DEPARTED"

    final_booking = get_booking(booking["id"])
    assert final_booking["status"] == "NO_SHOW", (
        f"confirmed-but-never-checked-in booking must become NO_SHOW, got "
        f"{final_booking['status']}"
    )
    sailing_after = get_sailing(sailing_id)
    assert sailing_after["reserved_vehicle_feet"] == 0, (
        "no-show release must recompute reserved_vehicle_feet back to 0, got "
        f"{sailing_after['reserved_vehicle_feet']}"
    )
    customer_after = get_customer(customer["id"])
    assert customer_after["refund_credit_cents"] == 0, (
        "no-show forfeits the fare: no refund credit may be issued, got "
        f"{customer_after['refund_credit_cents']}"
    )


def test_cancel_of_cancelled_sailing_rejected(api, scheduler_admin_headers):
    """PRD §3.8: "A `SchedulerAdmin` may cancel a sailing from any
    pre-departure posture — `SCHEDULED`, `OPEN_FOR_BOOKING`, `BOOKING_CLOSED`,
    or `BOARDING` — supplying a `cancel_reason` of `WEATHER`, `TIDES`,
    `MECHANICAL`, `CREW_SHORTAGE`, or `OTHER`."
    PRD §2.11: "4. Target resource in a legal state for the requested
    transition — otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_terminal_sailing_rejected
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=2, has_vehicle=True, vehicle_length_feet=18
    )
    sailing_id = setup["sailing"]["id"]
    customer = setup["customer"]

    cancelled = validate_success(
        api.cancel_sailing(sailing_id, {"cancel_reason": "WEATHER"}, scheduler_admin_headers)
    )
    assert cancelled["status"] == "CANCELLED"
    # 2*1000 + 2000 + 100*2 = 4200 credited by the first cancellation
    assert get_customer(customer["id"])["refund_credit_cents"] == 4200

    resp = api.cancel_sailing(
        sailing_id, {"cancel_reason": "WEATHER"}, scheduler_admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_customer(customer["id"])["refund_credit_cents"] == 4200, (
        "the cancellation cascade must not re-fire for a terminal sailing"
    )


def test_open_booking_requires_effective_fare_schedule(api, scheduler_admin_headers):
    """PRD §3.4: "Four preconditions gate the transition, and a failure on the
    manning or state legs surfaces as the corresponding error from §2.11: the
    route must be `ACTIVE`, the vessel must be `IN_SERVICE`, an `EFFECTIVE`
    fare schedule must exist for the sailing's route and season covering its
    `departure_time`, and `manning_ok` must be true."
    PRD §2.11: "13. An `EFFECTIVE` fare schedule covers the sailing —
    otherwise `ERR_FARE_SCHEDULE_NOT_EFFECTIVE`."

    Design: Corner/endpoints/conditional_action_open_booking_requires_effective_schedule
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas", crew_class="MEDIUM")
    fs = create_fare_schedule(
        route["id"],
        route_version=route["version"],
        season="OFF_PEAK",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2026-11-01T00:00:00Z",
    )
    submit_and_approve(fs["id"], 200)
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-15T10:00:00Z", season="OFF_PEAK"
    )
    crew_sailing_to_class_minimum(sailing["id"], "MEDIUM", "2026-09-15")

    # No clock call: the fixed default 2026-08-01T00:00:00Z predates the
    # schedule window, so the schedule is APPROVED but not EFFECTIVE.
    resp = api.open_booking(sailing["id"], scheduler_admin_headers)
    validate_error(resp, ApiErrorId.ERR_FARE_SCHEDULE_NOT_EFFECTIVE)

    after = get_sailing(sailing["id"])
    assert after["status"] == "SCHEDULED", (
        f"failed open-booking must leave the sailing SCHEDULED, got {after['status']}"
    )
