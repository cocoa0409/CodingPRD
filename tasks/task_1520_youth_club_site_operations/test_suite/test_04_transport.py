"""Transport routes, ride windows, overlap and seat-capacity gates."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_ride,
    create_active_member,
    create_ride_payload,
    create_route,
    director_headers,
    open_club_day,
    setup_site_with_director,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ride_invalid_window_rejected(api):
    """PRD 3.7: "a provided `effective_end_date` must be later than
    `effective_start_date` (`ERR_INVALID_DATE_WINDOW`, 422)".

    Design: Corner/validations/c_ride_invalid_window_rejected
    """
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    route = create_route(site["id"])
    res = api.create_ride_assignment(
        create_ride_payload(route["id"], member["id"], "2026-08-10",
                            "2026-08-03"),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_DATE_WINDOW, expected_status=422)
    data, meta = validate_paginated(
        api.list_member_ride_assignments(member["id"],
                                         TEST_USERS["platform_admin_headers"])
    )
    assert meta["total_count"] == 0


def _setup_member_with_ride(api):
    """ACTIVE member; route seat_capacity 5; ACTIVE ride [08-03, 08-10)."""
    site, director = setup_site_with_director(clock="2026-08-01T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid R")
    route = create_route(site["id"], "Route 1", "Lincoln", 5)
    ride = assign_ride(route["id"], member["id"], director["id"],
                       "2026-08-03", "2026-08-10")
    return site, director, member, route, ride


def test_ride_window_overlap_rejected(api):
    """PRD 3.7: "the new window must not overlap any other `ACTIVE` ride window
    belonging to the same member — adjacency is permitted precisely because
    windows are half-open (`ERR_RIDE_WINDOW_OVERLAP`, 409)".

    Design: Difficulty/resource_temporal_overlap/ride_window_half_open_overlap_adjacency_allowed
    """
    site, director, member, route, ride = _setup_member_with_ride(api)
    res = api.create_ride_assignment(
        create_ride_payload(route["id"], member["id"], "2026-08-07",
                            "2026-08-14"),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_RIDE_WINDOW_OVERLAP, expected_status=409)


def test_ride_window_adjacency_allowed(api):
    """PRD 3.7: "Ride windows are half-open: the start date is included and the
    end date excluded, so a window ending on a given date does not cover that
    date." — a new window starting exactly at the existing window's end does
    not overlap.

    Design: Difficulty/resource_temporal_overlap/ride_window_half_open_overlap_adjacency_allowed
    """
    site, director, member, route, ride = _setup_member_with_ride(api)
    adjacent = validate_success(
        api.create_ride_assignment(
            create_ride_payload(route["id"], member["id"], "2026-08-10",
                                "2026-08-17"),
            director_headers(director),
        ),
        201,
    )
    assert adjacent["status"] == "ACTIVE"
    assert adjacent["effective_start_date"] == "2026-08-10"


def _setup_seat_capacity_route(api):
    """Route seat_capacity 2 with club day 2026-08-03 open; three ACTIVE
    members. Returns (site, director, route, members)."""
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    members = [
        create_active_member(site["id"], director["id"], legal_name=n)
        for n in ("Rider A", "Rider B", "Rider C")
    ]
    route = create_route(site["id"], "Route 9", "Hoover", 2)
    open_club_day(site["id"], director["id"], "2026-08-03")
    return site, director, route, members


def test_route_seat_occupancy_at_capacity_allowed(api):
    """PRD 3.7: "on every already-existing club day whose date falls inside the
    new window, the number of `ACTIVE` ride assignments on the route covering
    that date, counting the new one, may not exceed the route's
    `seat_capacity` (`ERR_SEAT_CAPACITY_EXCEEDED`, 422)" — reaching exactly the
    capacity is allowed.

    Design: Difficulty/resource_temporal_overlap/route_seat_aggregate_occupancy_at_capacity
    """
    site, director, route, members = _setup_seat_capacity_route(api)
    ra = assign_ride(route["id"], members[0]["id"], director["id"], "2026-08-03")
    rb = assign_ride(route["id"], members[1]["id"], director["id"], "2026-08-03")
    assert ra["status"] == "ACTIVE"
    assert rb["status"] == "ACTIVE", (
        "occupancy reaching exactly seat_capacity 2 is allowed"
    )


def test_route_seat_occupancy_over_capacity_rejected(api):
    """PRD 3.7: "the number of `ACTIVE` ride assignments on the route covering
    that date, counting the new one, may not exceed the route's
    `seat_capacity` (`ERR_SEAT_CAPACITY_EXCEEDED`, 422)".

    Design: Difficulty/resource_temporal_overlap/route_seat_aggregate_occupancy_at_capacity
    """
    site, director, route, members = _setup_seat_capacity_route(api)
    assign_ride(route["id"], members[0]["id"], director["id"], "2026-08-03")
    assign_ride(route["id"], members[1]["id"], director["id"], "2026-08-03")
    res = api.create_ride_assignment(
        create_ride_payload(route["id"], members[2]["id"], "2026-08-03"),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED,
                   expected_status=422)


def test_ride_end_twice_returns_not_active(api):
    """PRD 3.7: "The ride must be `ACTIVE` (`ERR_RIDE_NOT_ACTIVE`, 409)" and
    "The ride's `effective_end_date` is rewritten to `end_date` and its status
    becomes `ENDED`".

    Design: Corner/state_machines/c_ride_end_twice_returns_not_active
    """
    site, director, member, route, ride = _setup_member_with_ride(api)
    ended = validate_success(
        api.end_ride_assignment(ride["id"], {"end_date": "2026-08-10"},
                                director_headers(director)),
        200,
    )
    assert ended["status"] == "ENDED"
    assert ended["effective_end_date"] == "2026-08-10"
    res = api.end_ride_assignment(ride["id"], {"end_date": "2026-08-11"},
                                  director_headers(director))
    validate_error(res, ApiErrorId.ERR_RIDE_NOT_ACTIVE, expected_status=409)
