"""Depth tests for the two opposed interval-overlap resources.

Instance one is the title's aggregate server pool with **half-open** intervals,
where adjacency is legal and the check is a peak-occupancy count (PRD §3.7).
Instance two is the school's broadcast channel with **closed** intervals and a
buffer applied to the candidate only, where adjacency conflicts (PRD §3.8).
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import league_admin_headers, make_coach_headers


# ==========================================================================
# Instance: server_pool_half_open_aggregate_capacity_with_legal_adjacency
# ==========================================================================
def _build_pool_with_two_overlapping_matches(api):
    """One shared pool of capacity 2 already carrying an 18:00-19:00 match and
    an 18:30-19:30 match, both SCHEDULED and therefore both holding capacity."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach_a = fx.make_coach(api, school["id"], full_name="Coach Alpha")
    coach_b = fx.make_coach(api, school["id"], full_name="Coach Bravo")
    title = fx.make_title(
        api,
        server_pool_id="POOL-SHARED",
        server_pool_capacity=2,
        match_duration_minutes=60,
    )
    season = fx.make_season(api, title["id"])
    alpha = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha"
    )
    bravo = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo"
    )

    first = fx.schedule_match(
        api, season["id"], alpha["id"], bravo["id"], "2026-09-25T18:00:00.000Z"
    )
    second = fx.schedule_match(
        api, season["id"], bravo["id"], alpha["id"], "2026-09-25T18:30:00.000Z"
    )
    return {
        "season": season,
        "title": title,
        "alpha": alpha,
        "bravo": bravo,
        "first": first,
        "second": second,
    }


def _season_match_count(api, season_id):
    _rows, meta = validate_paginated(
        api.list_matches({"season_id": season_id}, league_admin_headers())
    )
    return meta["total_count"]


def test_a_third_overlapping_match_exceeds_the_pool_at_its_own_start_instant(api):
    """Peak occupancy, not pairwise overlap, is what the pool tests.

    PRD §3.7: "Concurrency is probed at the candidate's own start instant and
    at every peer start instant that falls at or after the candidate's start
    and strictly before the candidate's end. At each probe instant the
    occupancy is one — the candidate itself — plus the number of peers whose
    start is at or before that instant and whose end is strictly after it. If
    the occupancy at any probe instant exceeds the title's
    `server_pool_capacity`, the scheduling request is refused with
    `ERR_SERVER_POOL_CAPACITY_EXCEEDED`."  And: "The server derives
    `scheduled_end_at` by adding the season's title's `match_duration_minutes`
    to `scheduled_start_at`, and copies that title's `server_pool_id` onto the
    match".

    Design: Difficulty/resource_temporal_overlap/server_pool_half_open_aggregate_capacity_with_legal_adjacency
    """
    world = _build_pool_with_two_overlapping_matches(api)

    assert world["first"]["scheduled_end_at"] == "2026-09-25T19:00:00.000Z"
    assert world["second"]["scheduled_end_at"] == "2026-09-25T19:30:00.000Z"
    assert world["first"]["server_pool_id"] == "POOL-SHARED"
    assert world["second"]["server_pool_id"] == "POOL-SHARED"
    A.assert_match_state(world["first"], play_status="SCHEDULED")
    A.assert_match_state(world["second"], play_status="SCHEDULED")

    response = api.create_match(
        {
            "season_id": world["season"]["id"],
            "home_team_id": world["alpha"]["id"],
            "away_team_id": world["bravo"]["id"],
            "scheduled_start_at": "2026-09-25T18:45:00.000Z",
        },
        league_admin_headers(),
    )
    validate_error(
        response, ApiErrorId.ERR_SERVER_POOL_CAPACITY_EXCEEDED.value, 409
    )

    assert _season_match_count(api, world["season"]["id"]) == 2


def test_a_match_starting_exactly_when_a_peer_ends_still_fits_the_pool(api):
    """Half-open endpoints touch without intersecting, so adjacency is legal.

    PRD §3.7: "Because the interval is half-open, **adjacency is legal**: a
    peer that ends at exactly the candidate's start instant, or begins at
    exactly the candidate's end instant, does not conflict."  And: "a match
    occupies its pool from `scheduled_start_at` inclusive to `scheduled_end_at`
    exclusive."

    Design: Difficulty/resource_temporal_overlap/server_pool_half_open_aggregate_capacity_with_legal_adjacency
    """
    world = _build_pool_with_two_overlapping_matches(api)
    rejected = api.create_match(
        {
            "season_id": world["season"]["id"],
            "home_team_id": world["alpha"]["id"],
            "away_team_id": world["bravo"]["id"],
            "scheduled_start_at": "2026-09-25T18:45:00.000Z",
        },
        league_admin_headers(),
    )
    validate_error(rejected, ApiErrorId.ERR_SERVER_POOL_CAPACITY_EXCEEDED.value, 409)

    accepted = api.create_match(
        {
            "season_id": world["season"]["id"],
            "home_team_id": world["bravo"]["id"],
            "away_team_id": world["alpha"]["id"],
            "scheduled_start_at": "2026-09-25T19:00:00.000Z",
        },
        league_admin_headers(),
    )
    validate_success(accepted, 201)
    fourth = A.data_of(accepted, 201)
    assert fourth["scheduled_start_at"] == "2026-09-25T19:00:00.000Z"
    assert fourth["scheduled_end_at"] == "2026-09-25T20:00:00.000Z"
    assert fourth["server_pool_id"] == "POOL-SHARED"
    A.assert_match_state(fourth, play_status="SCHEDULED")

    assert _season_match_count(api, world["season"]["id"]) == 3


# ==========================================================================
# Instance: broadcast_channel_closed_interval_with_buffer_makes_adjacency_
#           illegal
# ==========================================================================
def _build_channel_held_from_eighteen_to_nineteen(api):
    """A capacity-1 school channel already holding [18:00, 19:00] for the first
    match, with a second match waiting at 19:00 whose coach may also claim it."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach_a = fx.make_coach(api, school["id"], full_name="Coach Alpha")
    coach_b = fx.make_coach(api, school["id"], full_name="Coach Bravo")
    title = fx.make_title(
        api,
        server_pool_id="POOL-B",
        server_pool_capacity=3,
        match_duration_minutes=60,
    )
    season = fx.make_season(api, title["id"])
    alpha = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_a["id"], name="Alpha"
    )
    bravo = fx.make_team(
        api, season["id"], school["id"], title["id"], coach_b["id"], name="Bravo"
    )

    first = fx.schedule_match(
        api, season["id"], alpha["id"], bravo["id"], "2026-09-25T18:00:00.000Z"
    )
    second = fx.schedule_match(
        api, season["id"], alpha["id"], bravo["id"], "2026-09-25T19:00:00.000Z"
    )
    first = fx.register_broadcast(
        api,
        first["id"],
        coach_a["id"],
        school["id"],
        "2026-09-25T18:00:00.000Z",
        "2026-09-25T19:00:00.000Z",
    )
    return {
        "district": district,
        "school": school,
        "coach_a": coach_a,
        "first": first,
        "second": second,
    }


def _claim(api, world, start_at, end_at):
    return api.broadcast_action(
        world["second"]["id"],
        {
            "action": "REGISTER",
            "broadcast_school_id": world["school"]["id"],
            "broadcast_start_at": start_at,
            "broadcast_end_at": end_at,
        },
        make_coach_headers(world["coach_a"]["id"]),
    )


def test_a_touching_window_and_a_gap_of_exactly_the_buffer_both_collide(api):
    """The candidate alone is expanded, so the boundary sits at peer_end + 15.

    PRD §3.8: "The channel conflict test treats the requested window as a
    **closed** interval and expands it by the governing district's
    `broadcast_buffer_minutes` on **both** ends ... A peer conflicts when its
    `broadcast_start_at` is at or before the expanded candidate's end and its
    `broadcast_end_at` is at or after the expanded candidate's start. If the
    number of conflicting peers reaches the school's
    `concurrent_broadcast_capacity`, the claim is refused with
    `ERR_BROADCAST_CHANNEL_CONFLICT`. The buffer expands only the candidate;
    peer windows are compared exactly as stored."

    Design: Difficulty/resource_temporal_overlap/broadcast_channel_closed_interval_with_buffer_makes_adjacency_illegal
    """
    world = _build_channel_held_from_eighteen_to_nineteen(api)
    assert world["first"]["broadcast_status"] == "SCHEDULED"
    assert world["first"]["broadcast_school_id"] == world["school"]["id"]
    assert world["first"]["broadcast_start_at"] == "2026-09-25T18:00:00.000Z"
    assert world["first"]["broadcast_end_at"] == "2026-09-25T19:00:00.000Z"

    touching = _claim(
        api, world, "2026-09-25T19:00:00.000Z", "2026-09-25T20:00:00.000Z"
    )
    validate_error(touching, ApiErrorId.ERR_BROADCAST_CHANNEL_CONFLICT.value, 409)
    still_free = fx.get_match(api, world["second"]["id"])
    assert still_free["broadcast_status"] == "NONE"
    assert still_free["broadcast_school_id"] is None

    exactly_the_buffer = _claim(
        api, world, "2026-09-25T19:15:00.000Z", "2026-09-25T20:00:00.000Z"
    )
    validate_error(
        exactly_the_buffer, ApiErrorId.ERR_BROADCAST_CHANNEL_CONFLICT.value, 409
    )
    assert fx.get_match(api, world["second"]["id"])["broadcast_status"] == "NONE"


def test_a_gap_one_minute_wider_than_the_buffer_clears_the_channel(api):
    """Only a gap strictly greater than the buffer clears.

    PRD §3.8: "The practical consequence is that **adjacency conflicts here**,
    which is the reverse of the server pool rule: two windows that merely touch
    collide, any gap of at most `broadcast_buffer_minutes` collides, and only a
    gap strictly greater than `broadcast_buffer_minutes` clears. On success the
    three broadcast fields are pinned and `broadcast_status` moves `NONE →
    SCHEDULED`."  PRD §3.1: "`broadcast_buffer_minutes` is the cool-down
    applied to both ends of a requested broadcast window ... it defaults to
    15".

    Design: Difficulty/resource_temporal_overlap/broadcast_channel_closed_interval_with_buffer_makes_adjacency_illegal
    """
    world = _build_channel_held_from_eighteen_to_nineteen(api)
    validate_error(
        _claim(api, world, "2026-09-25T19:15:00.000Z", "2026-09-25T20:00:00.000Z"),
        ApiErrorId.ERR_BROADCAST_CHANNEL_CONFLICT.value,
        409,
    )

    cleared = _claim(
        api, world, "2026-09-25T19:16:00.000Z", "2026-09-25T20:00:00.000Z"
    )
    validate_success(cleared)
    second = A.data_of(cleared)
    assert second["broadcast_status"] == "SCHEDULED"
    assert second["broadcast_school_id"] == world["school"]["id"]
    assert second["broadcast_start_at"] == "2026-09-25T19:16:00.000Z"
    assert second["broadcast_end_at"] == "2026-09-25T20:00:00.000Z"
    A.assert_version_advanced_by(world["second"], second, 1)

    first = fx.get_match(api, world["first"]["id"])
    assert first["broadcast_status"] == "SCHEDULED"
    assert first["broadcast_start_at"] == "2026-09-25T18:00:00.000Z"
    assert first["broadcast_end_at"] == "2026-09-25T19:00:00.000Z"
