"""Cancellation cascades: the three-hop operator-cancel cascade and the
vessel out-of-service cascade."""
from test_helpers import (
    close_sailing,
    create_crew_assignment,
    create_crew_member,
    create_customer,
    create_fare_schedule,
    create_route,
    create_sailing,
    create_vessel,
    get_booking,
    get_crew_assignment,
    get_crew_member,
    get_customer,
    get_sailing,
    get_standby_entry,
    join_standby,
    setup_sailing_with_confirmed_booking,
    submit_and_approve,
    validate_success,
)


def test_cancel_open_sailing_fires_three_hop_cascade(api, scheduler_admin_headers):
    """PRD §3.8: "Cancellation is a three-hop cascade applied immediately.
    First, every booking in `RESERVED`, `CONFIRMED`, `MODIFIED`, or
    `CHECKED_IN` moves to `CANCELLED`, and for each booking that had settled a
    fare, the customer's `refund_credit_cents` increases by that booking's
    `final_fare_cents` (bookings cancelled from `RESERVED` had settled nothing
    and generate no credit). Second, every standby entry in `WAITING` or
    `CALLED` moves to `EXPIRED`. Third, every crew assignment still `ASSIGNED`
    is released, and each crew member with no remaining assignments returns to
    `AVAILABLE`."

    Design: Difficulty/transitive_cascade/sailing_cancel_cascade_depth3
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=2, has_vehicle=True, vehicle_length_feet=18,
        fuel_price_index_cents=350,
    )
    sailing_id = setup["sailing"]["id"]
    customer = setup["customer"]
    booking = setup["booking"]
    crew_assignment = setup["crew"]["assignments"][0]
    crew_member_id = crew_assignment["crew_member_id"]

    walk_on = create_customer(full_name="Walk On", fare_class="COMMUTER")
    entry = join_standby(sailing_id, walk_on, passenger_count=1, priority_class="STANDARD")
    assert entry["status"] == "WAITING"

    cancelled = validate_success(
        api.cancel_sailing(sailing_id, {"cancel_reason": "WEATHER"}, scheduler_admin_headers)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "WEATHER"

    # hop 1: booking cancelled, settled fare credited (2*1000+2000+100*2 = 4200)
    assert get_booking(booking["id"])["status"] == "CANCELLED"
    credit = get_customer(customer["id"])["refund_credit_cents"]
    assert credit == 4200, f"cancelled settled booking must credit 4200, got {credit}"

    # hop 2: standby entry expired
    assert get_standby_entry(entry["id"])["status"] == "EXPIRED"

    # hop 3: crew assignment released, member back to AVAILABLE
    assert get_crew_assignment(crew_assignment["id"])["status"] == "RELEASED"
    assert get_crew_member(crew_member_id)["status"] == "AVAILABLE"


def test_cancel_booking_closed_sailing_fires_same_cascade(api, scheduler_admin_headers):
    """PRD §3.8: "A `SchedulerAdmin` may cancel a sailing from any
    pre-departure posture — `SCHEDULED`, `OPEN_FOR_BOOKING`, `BOOKING_CLOSED`,
    or `BOARDING` — supplying a `cancel_reason` of `WEATHER`, `TIDES`,
    `MECHANICAL`, `CREW_SHORTAGE`, or `OTHER`."
    PRD §3.8: "Second, every standby entry in `WAITING` or `CALLED` moves to
    `EXPIRED`. Third, every crew assignment still `ASSIGNED` is released, and
    each crew member with no remaining assignments returns to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/sailing_cancel_cascade_depth3
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=2, has_vehicle=True, vehicle_length_feet=18,
        fuel_price_index_cents=350,
    )
    sailing_id = setup["sailing"]["id"]
    customer = setup["customer"]
    booking = setup["booking"]
    crew_assignment = setup["crew"]["assignments"][0]
    walk_on = create_customer(full_name="Walk On", fare_class="COMMUTER")
    entry = join_standby(sailing_id, walk_on, passenger_count=1, priority_class="STANDARD")

    close_sailing(sailing_id)  # now BOOKING_CLOSED — still a pre-departure posture

    cancelled = validate_success(
        api.cancel_sailing(sailing_id, {"cancel_reason": "TIDES"}, scheduler_admin_headers)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "TIDES"

    assert get_booking(booking["id"])["status"] == "CANCELLED"
    assert get_customer(customer["id"])["refund_credit_cents"] == 4200
    assert get_standby_entry(entry["id"])["status"] == "EXPIRED"
    assert get_crew_assignment(crew_assignment["id"])["status"] == "RELEASED"
    assert get_crew_member(crew_assignment["crew_member_id"])["status"] == "AVAILABLE"


def test_out_of_service_vessel_cancels_scheduled_sailings(api, scheduler_admin_headers):
    """PRD §3.1: "A vessel can later be taken out of service, moving its
    `status` to `OUT_OF_SERVICE` — and when that happens, every
    still-`SCHEDULED` sailing using that vessel is cancelled with
    `cancel_reason` set to `MECHANICAL`, firing the full cancellation cascade
    of §3.8."

    Design: Difficulty/transitive_cascade/vessel_out_of_service_cascade_depth2
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas", crew_class="MEDIUM")
    fs = create_fare_schedule(route["id"], route_version=route["version"])
    submit_and_approve(fs["id"], 200)
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z", season="OFF_PEAK"
    )
    assert sailing["status"] == "SCHEDULED"

    updated = validate_success(
        api.set_vessel_out_of_service(vessel["id"], scheduler_admin_headers)
    )
    assert updated["status"] == "OUT_OF_SERVICE"

    sailing_after = get_sailing(sailing["id"])
    assert sailing_after["status"] == "CANCELLED", (
        f"SCHEDULED sailing on an out-of-service vessel must be cancelled, got "
        f"{sailing_after['status']}"
    )
    assert sailing_after["cancel_reason"] == "MECHANICAL", (
        f"vessel-driven cancellation must record MECHANICAL, got "
        f"{sailing_after['cancel_reason']}"
    )


def test_out_of_service_cascade_releases_crew(api, scheduler_admin_headers):
    """PRD §3.1: "A vessel can later be taken out of service, moving its
    `status` to `OUT_OF_SERVICE` — and when that happens, every
    still-`SCHEDULED` sailing using that vessel is cancelled with
    `cancel_reason` set to `MECHANICAL`, firing the full cancellation cascade
    of §3.8."
    PRD §3.8: "Third, every crew assignment still `ASSIGNED` is released, and
    each crew member with no remaining assignments returns to `AVAILABLE`."

    Design: Difficulty/transitive_cascade/vessel_out_of_service_cascade_depth2
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas", crew_class="MEDIUM")
    fs = create_fare_schedule(route["id"], route_version=route["version"])
    submit_and_approve(fs["id"], 200)
    sailing = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z", season="OFF_PEAK"
    )
    captain = create_crew_member(credential_class="CAPTAIN", full_name="Cap A")
    assignment = create_crew_assignment(captain["id"], sailing["id"])
    assert get_crew_member(captain["id"])["status"] == "ASSIGNED"

    validate_success(api.set_vessel_out_of_service(vessel["id"], scheduler_admin_headers))

    assert get_crew_assignment(assignment["id"])["status"] == "RELEASED", (
        "the cancellation cascade must release the sailing's crew assignments"
    )
    assert get_crew_member(captain["id"])["status"] == "AVAILABLE", (
        "member with no remaining ASSIGNED assignments must return to AVAILABLE"
    )
