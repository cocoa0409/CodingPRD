"""Venue and referee temporal-overlap rules and their boundary (adjacency) behaviour,
plus the validation-priority pair that pits matchup integrity against venue overlap.

Covers resource_temporal_overlap (venue buffer + referee half-open),
boundary_precision (referee zero-gap adjacency), and
priority_pair_validation_conflict (invalid_matchup beats venue_double_booked).
"""
from test_helpers import (
    validate_success, validate_error,
    make_league_admin_headers,
    ApiErrorId,
)
import test_helpers.fixtures as fx
import test_helpers.factories as F

ADMIN = make_league_admin_headers()


def test_venue_buffer_makes_adjacent_games_conflict(api):
    """PRD §3.5: "Because the buffer must physically separate the games, two games that
    merely abut — the new one starting exactly when the prior one ends — do conflict
    whenever the buffer is greater than zero."

    Design: Difficulty/resource_temporal_overlap/venue_buffer_makes_adjacent_games_conflict
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 2, "turnover_buffer_minutes": 30},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=False,
    )
    # New game on the SAME field starting exactly when the first ends -> conflict (buffer 30).
    payload = F.create_game_payload(
        s["home_team"]["id"], s["away_team"]["id"], s["venue"]["id"],
        field_index=1, round_index=2,
        starts_at="2026-09-15T19:30:00Z", ends_at="2026-09-15T21:00:00Z",
    )
    resp = api.create_game(s["division"]["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value)


def test_venue_conflict_is_per_field(api):
    """PRD §3.5: "Different `field_index` values at the same venue never conflict with
    one another."

    Design: Difficulty/resource_temporal_overlap/venue_buffer_makes_adjacent_games_conflict
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 2, "turnover_buffer_minutes": 30},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=False,
    )
    payload = F.create_game_payload(
        s["home_team"]["id"], s["away_team"]["id"], s["venue"]["id"],
        field_index=2, round_index=2,
        starts_at="2026-09-15T19:30:00Z", ends_at="2026-09-15T21:00:00Z",
    )
    g2 = validate_success(api.create_game(s["division"]["id"], payload, ADMIN), expected_status=201)
    assert g2["field_index"] == 2 and g2["schedule_status"] == "SCHEDULED"


def test_referee_overlapping_games_conflict(api):
    """PRD §3.5: "A referee cannot hold two `ASSIGNED` assignments whose games'
    half-open time intervals — from `starts_at` up to but not including `ends_at` —
    overlap. Two such intervals conflict when the first starts strictly before the
    second ends and the second starts strictly before the first ends ..."

    Design: Difficulty/resource_temporal_overlap/referee_overlapping_games_conflict
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 2, "turnover_buffer_minutes": 0},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=True,
    )
    # G2 [19:00,20:30) intersects G1 [18:00,19:30) for the referee.
    g2 = fx.schedule_game(
        s["division"]["id"], s["home_team"]["id"], s["away_team"]["id"], s["venue"]["id"],
        field_index=2, round_index=2,
        starts_at="2026-09-15T19:00:00Z", ends_at="2026-09-15T20:30:00Z",
    )
    resp = api.create_referee_assignment(g2["id"], {"referee_id": s["referee"]["id"], "role": "HEAD"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFEREE_DOUBLE_BOOKED.value)


def test_referee_overlapping_games_conflict_on_reschedule_unaffected_field(api):
    """PRD §3.5: "A referee cannot hold two `ASSIGNED` assignments whose games'
    half-open time intervals — from `starts_at` up to but not including `ends_at` —
    overlap. Two such intervals conflict when the first starts strictly before the
    second ends and the second starts strictly before the first ends ..."

    A second, fully-contained interval [18:30,19:00) also intersects G1 [18:00,19:30)
    and is rejected for the same referee.

    Design: Difficulty/resource_temporal_overlap/referee_overlapping_games_conflict
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 2, "turnover_buffer_minutes": 0},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=True,
    )
    g2 = fx.schedule_game(
        s["division"]["id"], s["home_team"]["id"], s["away_team"]["id"], s["venue"]["id"],
        field_index=2, round_index=2,
        starts_at="2026-09-15T18:30:00Z", ends_at="2026-09-15T19:00:00Z",
    )
    resp = api.create_referee_assignment(g2["id"], {"referee_id": s["referee"]["id"], "role": "HEAD"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFEREE_DOUBLE_BOOKED.value)


def test_referee_assignment_to_disjoint_game_succeeds(api):
    """PRD §3.5: "Two such intervals conflict when the first starts strictly before the
    second ends and the second starts strictly before the first ends; back-to-back
    games that share only the boundary instant (one ending exactly as the next begins)
    do not conflict for a referee ..."

    A fully-disjoint later interval [20:00,21:00) does not intersect G1 [18:00,19:30),
    so the same referee may take it.

    Design: Difficulty/boundary_precision_check/referee_adjacent_games_zero_gap_no_conflict
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 2, "turnover_buffer_minutes": 0},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=True,
    )
    g2 = fx.schedule_game(
        s["division"]["id"], s["home_team"]["id"], s["away_team"]["id"], s["venue"]["id"],
        field_index=2, round_index=2,
        starts_at="2026-09-15T20:00:00Z", ends_at="2026-09-15T21:00:00Z",
    )
    ra2 = validate_success(
        api.create_referee_assignment(g2["id"], {"referee_id": s["referee"]["id"], "role": "HEAD"}, ADMIN),
        expected_status=201,
    )
    assert ra2["state"] == "ASSIGNED"


def test_referee_adjacent_games_zero_gap_do_not_conflict(api):
    """PRD §3.5: "back-to-back games that share only the boundary instant (one ending
    exactly as the next begins) do not conflict for a referee, because no turnover
    buffer applies to an official moving between games."

    Design: Difficulty/boundary_precision_check/referee_adjacent_games_zero_gap_no_conflict
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 2, "turnover_buffer_minutes": 0},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=True,
    )
    # G2 [19:30,21:00) begins exactly when G1 ends -> no referee conflict.
    g2 = fx.schedule_game(
        s["division"]["id"], s["home_team"]["id"], s["away_team"]["id"], s["venue"]["id"],
        field_index=2, round_index=2,
        starts_at="2026-09-15T19:30:00Z", ends_at="2026-09-15T21:00:00Z",
    )
    ra2 = validate_success(
        api.create_referee_assignment(g2["id"], {"referee_id": s["referee"]["id"], "role": "HEAD"}, ADMIN),
        expected_status=201,
    )
    assert ra2["state"] == "ASSIGNED", "an adjacent (e1==a2) assignment must succeed for a referee"


def test_invalid_matchup_beats_venue_overlap_on_game_create(api):
    """PRD §2.7: "then matchup referential integrity (`ERR_INVALID_MATCHUP`); then
    referee double-booking (`ERR_REFEREE_DOUBLE_BOOKED`); then venue double-booking
    (`ERR_VENUE_DOUBLE_BOOKED`)".
    PRD §3.5: "The two teams must differ, must both be `CONFIRMED`, and must belong to
    the same division as the game — a violation of any of these is rejected with
    `ERR_INVALID_MATCHUP`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_matchup_beats_venue_overlap_on_game_create
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 1, "turnover_buffer_minutes": 30},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=False,
    )
    # home==away AND an overlapping (venue,field) slot: matchup (p9) must win over venue (p11).
    payload = F.create_game_payload(
        s["home_team"]["id"], s["home_team"]["id"], s["venue"]["id"],
        field_index=1, round_index=2,
        starts_at="2026-09-15T18:30:00Z", ends_at="2026-09-15T20:00:00Z",
    )
    resp = api.create_game(s["division"]["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_MATCHUP.value)


def test_invalid_matchup_unconfirmed_team_beats_venue_overlap(api):
    """PRD §2.7: "then matchup referential integrity (`ERR_INVALID_MATCHUP`); then
    referee double-booking (`ERR_REFEREE_DOUBLE_BOOKED`); then venue double-booking
    (`ERR_VENUE_DOUBLE_BOOKED`)".
    PRD §3.5: "The two teams must differ, must both be `CONFIRMED`, and must belong to
    the same division as the game — a violation of any of these is rejected with
    `ERR_INVALID_MATCHUP`."

    An away team that is not CONFIRMED is itself a matchup violation, and even when the
    requested slot also collides on (venue,field), the matchup check (p9) is reported
    ahead of the venue check (p11).

    Design: Difficulty/priority_pair_validation_conflict/invalid_matchup_beats_venue_overlap_on_game_create
    """
    s = fx.setup_scheduled_game(
        venue_overrides={"field_count": 1, "turnover_buffer_minutes": 30},
        game_overrides={"field_index": 1, "round_index": 1,
                        "starts_at": "2026-09-15T18:00:00Z", "ends_at": "2026-09-15T19:30:00Z"},
        with_head_referee=False,
    )
    # A fresh PENDING (un-confirmed) team in the same division as the away side.
    pending_cap = fx.create_player()
    pending_team = fx.register_team(s["division"]["id"], pending_cap["id"])  # status PENDING
    payload = F.create_game_payload(
        s["home_team"]["id"], pending_team["id"], s["venue"]["id"],
        field_index=1, round_index=2,
        starts_at="2026-09-15T18:30:00Z", ends_at="2026-09-15T20:00:00Z",  # overlapping slot
    )
    resp = api.create_game(s["division"]["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_MATCHUP.value)
