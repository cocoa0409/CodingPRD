"""League lifecycle and standings: the cyclic OPEN→ROUND_LOCKED→OPEN advance,
round-completeness and round-limit guards, finalize precondition, and standings
scoring.

Queue A (Difficulty) — non_linear_state_machine (league cyclic).
Queue B (Corner) — state_machines (league guards), calculations (standings).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_league_match_payload,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field,
    create_confirmed_booking, create_league, open_league,
    setup_open_league, setup_round_locked_league, check_in_booking, complete_booking,
)
from test_helpers import api_client

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]
LD = TEST_USERS["league_director_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — non_linear_state_machine: league cyclic open/lock/advance (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_league_advance_round_returns_to_open_and_increments_round(api):
    """PRD §3.9: "Advancing to the next round moves the league `ROUND_LOCKED → OPEN`: it
    requires `current_round` to be strictly less than `total_rounds` (an attempt at the
    last round is rejected with `ERR_ROUND_LIMIT_REACHED`) and again carries
    `expected_league_version`; on success `current_round` is incremented by one and the
    league's `version` is incremented by one."

    Design: Difficulty/non_linear_state_machine/league_cyclic_open_lock_advance
    """
    arena, locked = setup_round_locked_league(total_rounds=2)
    advanced = validate_success(
        api.advance_round(locked["id"], {"expected_league_version": locked["version"]}, LD), 200
    )
    assert advanced["status"] == "OPEN", \
        f"advance-round must return league to OPEN, got {advanced['status']}"
    assert advanced["current_round"] == 2, \
        f"advance-round must increment current_round to 2, got {advanced['current_round']}"


def test_league_lock_round_bumps_version(api):
    """PRD §3.9: "On a successful lock the league's `version` is incremented by one and
    the standings are recomputed."

    Design: Difficulty/non_linear_state_machine/league_cyclic_open_lock_advance
    """
    arena, league = setup_open_league(total_rounds=2)
    locked = validate_success(
        api.lock_round(league["id"], {"expected_league_version": league["version"]}, LD), 200
    )
    assert locked["status"] == "ROUND_LOCKED"
    assert locked["version"] == league["version"] + 1, \
        f"lock-round must bump version from {league['version']}, got {locked['version']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — league state-machine guards
# ─────────────────────────────────────────────────────────────────────────────
def test_lock_round_with_scheduled_match_returns_round_not_complete(api):
    """PRD §3.9: "Locking the current round moves the league `OPEN → ROUND_LOCKED` and
    is guarded three ways: every match in the current round must already be in
    `RESULT_RECORDED` or `VOID` (a still-`SCHEDULED` match blocks the lock with
    `ERR_ROUND_NOT_COMPLETE`), and the request must pass the OCC check of §2.6 carrying
    `expected_league_version`."

    Design: Corner/state_machines/lock_round_with_scheduled_match_returns_round_not_complete
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    league = create_league(arena["id"], total_rounds=2, name="Lb4")
    league = open_league(league["id"])
    validate_success(api.create_league_match(
        create_league_match_payload(arena["id"], league["id"], booking["id"],
                                    home_team="A", away_team="B"), LD), 201)
    res = api.lock_round(league["id"], {"expected_league_version": league["version"]}, LD)
    validate_error(res, "ERR_ROUND_NOT_COMPLETE", expected_status=409)


def test_finalize_before_last_round_returns_not_at_final_round(api):
    """PRD §3.9: "Finalizing moves the league `ROUND_LOCKED → FINALIZED` and requires
    `current_round` to equal `total_rounds`; a finalize attempted before the final round
    is locked is rejected with `ERR_LEAGUE_NOT_AT_FINAL_ROUND`, and the final standings
    are frozen."

    Design: Corner/state_machines/finalize_before_last_round_returns_invalid_state
    """
    arena, locked = setup_round_locked_league(total_rounds=2)  # ROUND_LOCKED at round 1
    res = api.finalize_league(locked["id"], LD)
    validate_error(res, "ERR_LEAGUE_NOT_AT_FINAL_ROUND", expected_status=409)


def test_advance_round_at_limit_returns_round_limit_reached(api):
    """PRD §3.9: "Advancing to the next round moves the league `ROUND_LOCKED → OPEN`: it
    requires `current_round` to be strictly less than `total_rounds` (an attempt at the
    last round is rejected with `ERR_ROUND_LIMIT_REACHED`) ..."

    Design: Corner/state_machines/advance_round_at_limit_returns_round_limit_reached
    """
    arena, locked = setup_round_locked_league(total_rounds=1)  # ROUND_LOCKED at last round
    res = api.advance_round(locked["id"], {"expected_league_version": locked["version"]}, LD)
    validate_error(res, "ERR_ROUND_LIMIT_REACHED", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — league standings calculation
# ─────────────────────────────────────────────────────────────────────────────
def test_league_standings_points_order(api):
    """PRD §3.9: "Walking the qualifying matches in chronological order of their
    creation timestamp, a `DRAW` adds the league's `draw_points` to both teams, a `HOME`
    outcome adds the league's `win_points` to the home team, and an `AWAY` outcome adds
    the league's `win_points` to the away team. The standings list is then the teams
    sorted by points descending, breaking ties by team label ascending ..."

    Design: Corner/calculations/league_standings_points_order
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 12}
    )
    league = create_league(arena["id"], total_rounds=1, name="Lc5", win_points=3, draw_points=1)
    league = open_league(league["id"])

    # booking 1 -> COMPLETED, match A beats B 5-2
    b1 = create_confirmed_booking(
        arena, field, booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T10:00:00Z", window_end="2026-06-15T11:00:00Z",
    )
    validate_success(api.set_clock({"arena_id": arena["id"], "to_iso8601": "2026-06-15T10:00:00Z"}, AM), 200)
    check_in_booking(b1["id"], 4)
    complete_booking(b1["id"])
    m1 = validate_success(api.create_league_match(
        create_league_match_payload(arena["id"], league["id"], b1["id"],
                                    home_team="A", away_team="B"), LD), 201)
    validate_success(api.record_match_result(m1["id"], {"home_score": 5, "away_score": 2}, LD), 200)

    # booking 2 -> COMPLETED, match A draws C 1-1
    b2 = create_confirmed_booking(
        arena, field, booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T11:30:00Z", window_end="2026-06-15T12:30:00Z",
    )
    validate_success(api.set_clock({"arena_id": arena["id"], "to_iso8601": "2026-06-15T11:30:00Z"}, AM), 200)
    check_in_booking(b2["id"], 4)
    complete_booking(b2["id"])
    m2 = validate_success(api.create_league_match(
        create_league_match_payload(arena["id"], league["id"], b2["id"],
                                    home_team="A", away_team="C"), LD), 201)
    validate_success(api.record_match_result(m2["id"], {"home_score": 1, "away_score": 1}, LD), 200)

    standings = validate_success(api.get_standings(league["id"], LD), 200)
    assert standings["standings"][0]["team"] == "A"
    assert standings["standings"][0]["points"] == 4, \
        f"A must lead with 4 points, got {standings['standings'][0]['points']}"
    assert standings["current_round"] == 1
