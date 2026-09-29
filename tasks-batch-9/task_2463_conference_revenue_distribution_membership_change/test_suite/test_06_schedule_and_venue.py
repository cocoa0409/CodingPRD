"""Contended resources: the per-member rest buffer and the half-open venue occupancy window."""

from test_helpers import (
    ApiErrorId,
    assert_fields_equal,
    assert_same_instant,
    create_schedule_game,
    make_championship_event_payload,
    make_schedule_coordinator_headers,
    make_schedule_game_payload,
    setup_charter_roster,
    setup_venue_capacity_fixture,
    validate_error,
    validate_success,
)


def _attempt_game(api, conference_id, home_member_id, away_member_id, venue_id, game_date):
    return api.create_schedule_game(
        make_schedule_game_payload(
            conference_id,
            home_member_id,
            away_member_id,
            venue_id,
            game_date,
            media_designated=False,
        ),
        headers=make_schedule_coordinator_headers(),
    )


def _attempt_event(api, ctx, sport, window_start, window_end):
    return api.create_championship_event(
        make_championship_event_payload(
            ctx["conference_id"],
            ctx["venue_east"]["id"],
            ctx["member_ids"]["south"],
            ctx["pool_id"],
            window_start,
            window_end,
            sport=sport,
        ),
        headers=make_schedule_coordinator_headers(),
    )


def _games(api):
    return validate_success(
        api.list_schedule_games(headers=make_schedule_coordinator_headers())
    )


def _events_at_east(api, ctx):
    return validate_success(
        api.list_championship_events(
            params={"venue_id": ctx["venue_east"]["id"]},
            headers=make_schedule_coordinator_headers(),
        )
    )


def test_rest_buffer_is_reported_before_the_wrong_home_venue(api):
    """PRD §3.4: "Several checks guard it, and their relative order matters because they
    carry different codes."
    PRD §3.4: "Then comes the **member rest buffer**: neither participant may already have a
    game in status `SCHEDULED` or `PLAYED` whose `game_date` is fewer than six calendar days
    away from the requested `game_date`, in either direction; a separation of exactly six days
    is accepted, and anything tighter is refused with `ERR_MEMBER_REST_BUFFER_VIOLATION`."
    PRD §3.4: "Only after the rest buffer passes does the home-venue check run: the supplied
    `venue_id` must be the home member's own `home_venue_id`, and a mismatch is refused with
    `ERR_VENUE_NOT_HOME_VENUE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/rest_buffer_precedes_home_venue_constraint
    """
    ctx = setup_charter_roster(api, member_keys=("north", "south", "east"))
    ids = ctx["member_ids"]
    create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )

    # Two days after North's existing game, and at a venue that is not North's home.
    response = _attempt_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        ctx["venue_east"]["id"],
        "2026-09-07T19:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_MEMBER_REST_BUFFER_VIOLATION.value, 409)
    assert len(_games(api)) == 1, "the refused create leaves no game behind"


def test_rest_buffer_satisfied_then_the_wrong_home_venue_surfaces(api):
    """PRD §3.4: "Only after the rest buffer passes does the home-venue check run: the supplied
    `venue_id` must be the home member's own `home_venue_id`, and a mismatch is refused with
    `ERR_VENUE_NOT_HOME_VENUE` (HTTP 422)."
    PRD §3.4: "Then comes the **member rest buffer**: neither participant may already have a
    game in status `SCHEDULED` or `PLAYED` whose `game_date` is fewer than six calendar days
    away from the requested `game_date`, in either direction; a separation of exactly six days
    is accepted, and anything tighter is refused with `ERR_MEMBER_REST_BUFFER_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/rest_buffer_precedes_home_venue_constraint
    """
    ctx = setup_charter_roster(api, member_keys=("north", "south", "east"))
    ids = ctx["member_ids"]
    create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )

    # Fifteen days out clears the buffer, so the venue mismatch is no longer masked.
    response = _attempt_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        ctx["venue_east"]["id"],
        "2026-09-20T19:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_VENUE_NOT_HOME_VENUE.value, 422)
    assert len(_games(api)) == 1, "neither refused create leaves a game behind"


def test_rest_buffer_refuses_a_participant_playing_three_days_later(api):
    """PRD §3.4: "Then comes the **member rest buffer**: neither participant may already have a
    game in status `SCHEDULED` or `PLAYED` whose `game_date` is fewer than six calendar days
    away from the requested `game_date`, in either direction; a separation of exactly six days
    is accepted, and anything tighter is refused with `ERR_MEMBER_REST_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/member_rest_buffer_is_per_member_point_date_capacity
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]
    create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )

    # North is the contended resource: it already plays three days earlier.
    response = _attempt_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["east"],
        ctx["venue_north"]["id"],
        "2026-09-08T19:00:00Z",
    )

    validate_error(response, ApiErrorId.ERR_MEMBER_REST_BUFFER_VIOLATION.value, 409)
    assert len(_games(api)) == 1


def test_rest_buffer_keys_on_participants_not_on_the_calendar_date(api):
    """PRD §3.4: "Then comes the **member rest buffer**: neither participant may already have a
    game in status `SCHEDULED` or `PLAYED` whose `game_date` is fewer than six calendar days
    away from the requested `game_date`, in either direction; a separation of exactly six days
    is accepted, and anything tighter is refused with `ERR_MEMBER_REST_BUFFER_VIOLATION`."
    PRD §3.4: "A game is created in `SCHEDULED` and immediately triggers a recomputation of
    `schedule_compliance_score` for both participants."

    Design: Difficulty/resource_temporal_overlap/member_rest_buffer_is_per_member_point_date_capacity
    """
    ctx = setup_charter_roster(api)
    ids = ctx["member_ids"]
    north_south = create_schedule_game(
        api,
        ctx["conference_id"],
        ids["north"],
        ids["south"],
        ctx["venue_north"]["id"],
        "2026-09-05T19:00:00Z",
    )

    # The same date that is refused for North is free for two members with no games.
    east_west = create_schedule_game(
        api,
        ctx["conference_id"],
        ids["east"],
        ids["west"],
        ctx["venue_east"]["id"],
        "2026-09-08T19:00:00Z",
        media_designated=False,
    )

    assert_fields_equal(
        east_west,
        status="SCHEDULED",
        home_member_id=ids["east"],
        away_member_id=ids["west"],
    )
    assert_same_instant(east_west["game_date"], "2026-09-08T19:00:00Z")
    assert north_south["status"] == "SCHEDULED"
    assert len(_games(api)) == 2


def test_third_intersecting_window_exceeds_the_venue_capacity_of_two(api):
    """PRD §3.5: "Then venue occupancy is checked: the number of events on the same venue in
    status `SCHEDULED`, `HOST_AT_RISK` or `HOSTED` whose half-open window intersects the
    requested half-open window must be strictly less than that venue's
    `concurrent_event_capacity`, and otherwise the award is refused with
    `ERR_VENUE_CAPACITY_EXCEEDED`."
    PRD §3.4: "A `ScheduleCoordinator` or `PlatformAdmin` registers one with a `name`, a
    `city`, a `seating_capacity` that must be strictly greater than 0, and a
    `concurrent_event_capacity` that defaults to 1 and must be at least 1 — the latter governs
    how many championship occupancy windows may overlap on that venue at once, and is used in
    §3.5 rather than in ordinary game scheduling."

    Design: Difficulty/resource_temporal_overlap/championship_venue_capacity_uses_half_open_windows
    """
    ctx = setup_venue_capacity_fixture(api)
    assert ctx["venue_east"]["concurrent_event_capacity"] == 2
    assert len(_events_at_east(api, ctx)) == 2

    # This window intersects both scheduled events, so the occupancy count reaches 2.
    response = _attempt_event(
        api, ctx, "GYMNASTICS", "2027-03-04T00:00:00Z", "2027-03-06T00:00:00Z"
    )

    validate_error(response, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value, 409)
    assert len(_events_at_east(api, ctx)) == 2, "the refused award occupies nothing"


def test_window_beginning_at_another_windows_end_is_admitted(api):
    """PRD §3.5: "The window is half-open: it includes its start instant and excludes its end
    instant."
    PRD §3.5: "Because both windows are half-open, a requested window that begins exactly at
    another event's `window_end` does not intersect it and is therefore permitted."
    PRD §3.5: "Then venue occupancy is checked: the number of events on the same venue in
    status `SCHEDULED`, `HOST_AT_RISK` or `HOSTED` whose half-open window intersects the
    requested half-open window must be strictly less than that venue's
    `concurrent_event_capacity`, and otherwise the award is refused with
    `ERR_VENUE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/championship_venue_capacity_uses_half_open_windows
    """
    ctx = setup_venue_capacity_fixture(api)

    admitted = validate_success(
        _attempt_event(api, ctx, "TENNIS", "2027-03-07T00:00:00Z", "2027-03-09T00:00:00Z"),
        201,
    )
    # One second earlier the window reaches back into the event that ends at 03-07 and
    # also covers the newly admitted one, so two events now intersect it.
    refused = _attempt_event(
        api, ctx, "GOLF", "2027-03-06T23:59:59Z", "2027-03-09T00:00:00Z"
    )

    assert_fields_equal(
        admitted,
        status="SCHEDULED",
        sport="TENNIS",
        venue_id=ctx["venue_east"]["id"],
    )
    assert_same_instant(admitted["window_start"], "2027-03-07T00:00:00Z")
    assert_same_instant(admitted["window_end"], "2027-03-09T00:00:00Z")
    validate_error(refused, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value, 409)
    assert len(_events_at_east(api, ctx)) == 3
