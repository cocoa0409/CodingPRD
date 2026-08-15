"""Manning and temporal-overlap rules: the >500 passenger deckhand
escalator, the vessel turnaround buffer (half-open at the buffer end), and
the crew 480-minute rest rule."""
from test_helpers import (
    ApiErrorId,
    assert_crew_assignment,
    assert_sailing,
    confirm_booking,
    create_booking,
    create_crew_assignment,
    create_crew_assignment_payload,
    create_crew_member,
    create_customer,
    create_route,
    create_sailing,
    create_sailing_payload,
    create_vessel,
    get_sailing,
    setup_open_sailing,
    validate_error,
    validate_success,
)


def test_manning_escalator_boundary_500_vs_501(api, scheduler_admin_headers):
    """PRD §2.8: "A passenger-load escalator applies on top of the class
    minimums: when a sailing's `booked_passengers` is strictly greater than
    500, the required `DECK` count rises by one. Exactly 500 passengers does
    not trigger the extra deckhand — the threshold is exclusive."
    PRD §2.8: "`MEDIUM` vessels require at least 1 `CAPTAIN`, at least 2
    `DECK`, and at least 1 `ENGINE`."

    Design: Corner/calculations/manning_passenger_escalator_boundary
    """
    setup = setup_open_sailing(
        deck_feet=200, passenger_capacity=600, crew_class="MEDIUM",
        fuel_price_index_cents=200,
    )
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Group A", fare_class="STANDARD")

    b500 = create_booking(sailing_id, customer, passenger_count=500)
    confirm_booking(b500["id"], customer)

    at_500 = get_sailing(sailing_id)
    assert_sailing(at_500)
    assert at_500["booked_passengers"] == 500
    assert at_500["manning_ok"] is True, (
        "exactly 500 booked passengers must NOT trigger the +1 DECK escalator "
        "(threshold is strictly greater than 500)"
    )

    b1 = create_booking(sailing_id, customer, passenger_count=1)
    confirm_booking(b1["id"], customer)

    at_501 = get_sailing(sailing_id)
    assert at_501["booked_passengers"] == 501
    assert at_501["manning_ok"] is False, (
        "501 booked passengers must trigger the +1 DECK escalator; the base "
        "MEDIUM complement (2 DECK) then falls short"
    )


def test_departure_inside_turnaround_buffer_rejected(api, scheduler_admin_headers):
    """PRD §3.1: "A vessel is occupied from its `departure_time` until its
    `arrival_time` plus the route's turnaround buffer, treated as a half-open
    interval; a new sailing whose own occupied window touches that interval is
    rejected with `ERR_VESSEL_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vessel_turnaround_buffer_semantics
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    first = create_sailing(
        route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z"
    )
    assert first["status"] == "SCHEDULED"
    # First sailing occupies [10:00, arrival 10:35 + 15 min buffer) = [10:00, 10:50)

    payload = create_sailing_payload(
        vessel_id=vessel["id"], departure_time="2026-09-01T10:49:00Z", season="OFF_PEAK"
    )
    resp = api.create_sailing(route["id"], payload, scheduler_admin_headers)
    validate_error(resp, ApiErrorId.ERR_VESSEL_SCHEDULE_CONFLICT)


def test_departure_at_buffer_end_exclusive_allowed(api, scheduler_admin_headers):
    """PRD §3.1: "A vessel is occupied from its `departure_time` until its
    `arrival_time` plus the route's turnaround buffer, treated as a half-open
    interval; a new sailing whose own occupied window touches that interval is
    rejected with `ERR_VESSEL_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vessel_turnaround_buffer_semantics
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    create_sailing(route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z")
    # Occupied [10:00, 10:50); a 10:50 departure touches nothing (half-open).

    payload = create_sailing_payload(
        vessel_id=vessel["id"], departure_time="2026-09-01T10:50:00Z", season="OFF_PEAK"
    )
    created = validate_success(
        api.create_sailing(route["id"], payload, scheduler_admin_headers),
        expected_status=201,
    )
    assert_sailing(created)
    assert created["status"] == "SCHEDULED"


def test_adjacent_crew_shifts_violate_rest_rule(api, crew_planner_headers):
    """PRD §3.3: "Two crew-protection rules guard assignment creation, both
    failing with `ERR_CREW_REST_CONFLICT`: no two `ASSIGNED` assignments for
    the same member may have overlapping half-open shift intervals, and any
    two such assignments must leave at least 480 minutes of rest between
    them."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_interval_with_rest_gap
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    s1 = create_sailing(route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z")
    s2 = create_sailing(route["id"], vessel["id"], departure_time="2026-09-01T20:00:00Z")
    captain = create_crew_member(credential_class="CAPTAIN", full_name="Cap A")

    first = create_crew_assignment(
        captain["id"], s1["id"],
        shift_start="2026-09-01T08:00:00Z", shift_end="2026-09-01T16:00:00Z",
    )
    assert first["status"] == "ASSIGNED"

    # Half-open adjacency means [08:00,16:00) and [16:00,00:00) do not
    # overlap, but 0 minutes of rest violates the 480-minute rule.
    payload = create_crew_assignment_payload(
        crew_member_id=captain["id"],
        shift_start="2026-09-01T16:00:00Z",
        shift_end="2026-09-02T00:00:00Z",
    )
    resp = api.create_crew_assignment(s2["id"], payload, crew_planner_headers)
    validate_error(resp, ApiErrorId.ERR_CREW_REST_CONFLICT)


def test_crew_shift_exactly_480_minutes_later_allowed(api, crew_planner_headers):
    """PRD §3.3: "Two crew-protection rules guard assignment creation, both
    failing with `ERR_CREW_REST_CONFLICT`: no two `ASSIGNED` assignments for
    the same member may have overlapping half-open shift intervals, and any
    two such assignments must leave at least 480 minutes of rest between
    them."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_interval_with_rest_gap
    """
    route = create_route(route_code="SEA-BI", crossing_minutes=35, turnaround_minutes=15)
    vessel = create_vessel(vessel_name="MV Kittitas")
    s1 = create_sailing(route["id"], vessel["id"], departure_time="2026-09-01T10:00:00Z")
    s2 = create_sailing(route["id"], vessel["id"], departure_time="2026-09-01T20:00:00Z")
    captain = create_crew_member(credential_class="CAPTAIN", full_name="Cap A")

    create_crew_assignment(
        captain["id"], s1["id"],
        shift_start="2026-09-01T08:00:00Z", shift_end="2026-09-01T16:00:00Z",
    )

    # 16:00 -> 00:00 the next day is exactly 480 minutes of rest: permitted.
    payload = create_crew_assignment_payload(
        crew_member_id=captain["id"],
        shift_start="2026-09-02T00:00:00Z",
        shift_end="2026-09-02T08:00:00Z",
    )
    created = validate_success(
        api.create_crew_assignment(s2["id"], payload, crew_planner_headers),
        expected_status=201,
    )
    assert_crew_assignment(created)
    assert created["status"] == "ASSIGNED"
