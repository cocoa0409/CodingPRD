"""Referee assignments: confirm time-overlap, day-limit, game-start dependency,
release/confirm day-occupancy conservation, ownership.

Covers: cross_entity_state_dependency (game start needs confirmed assignment),
boundary_precision (empty referee set blocks start), resource_temporal_overlap
(referee unbuffered overlap), compensating_invariant (confirm/release day
occupancy), cross_cutting (day-limit boundary), rbac (referee owns own
assignment).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_league_admin_headers,
    make_referee_headers,
)
from test_helpers import fixtures as fx


ADMIN = make_league_admin_headers("admin-1")


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / game_start_depends_on_assignment_state  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_game_start_blocked_until_assignment_confirmed(api):
    """PRD §3.5: "A game may not start unless at least one of its referee
    assignments is `CONFIRMED` or `CHECKED_IN`; starting without a confirmed
    umpire is rejected with `ERR_NO_REFEREE_CONFIRMED`."

    With only a PROPOSED assignment the start is rejected.

    Design: Difficulty/cross_entity_state_dependency/game_start_depends_on_assignment_state
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    fx.propose_assignment(game["id"], s["referee"]["id"])

    resp = api.start_game(game["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_REFEREE_CONFIRMED.value)


def test_game_start_succeeds_once_assignment_confirmed(api):
    """PRD §3.5: "A game may not start unless at least one of its referee
    assignments is `CONFIRMED` or `CHECKED_IN`". Once confirmed, the same start
    succeeds and moves the game to IN_PROGRESS.

    Design: Difficulty/cross_entity_state_dependency/game_start_depends_on_assignment_state
    """
    s = fx.setup_game_with_confirmed_referee()
    out = validate_success(api.start_game(s["game"]["id"], ADMIN))
    assert out["status"] == "IN_PROGRESS", out["status"]


# ─────────────────────────────────────────────────────────────────────────────
# cross_entity_state_dependency / player_evaluate_depends_on_league_status  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_evaluate_blocked_while_league_in_registration(api):
    """PRD §3.3: "Once the league has advanced to `EVALUATION`, a `LeagueAdmin`
    records evaluation scores, moving an `AGE_VERIFIED` player to `EVALUATED`.
    Evaluation requires the league to be in `EVALUATION`".

    With the league still in REGISTRATION, evaluating an AGE_VERIFIED player is
    rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/player_evaluate_depends_on_league_status
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="P1", birth_date="2015-01-15",
                          birth_certificate_ref="bc1")
    fx.verify_age(p["id"])

    resp = api.evaluate_player(p["id"], {
        "eval_speed": 55, "eval_hitting": 55, "eval_fielding": 55,
    }, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    player = validate_success(api.get_player(p["id"], ADMIN))
    assert player["status"] == "AGE_VERIFIED", player["status"]


def test_evaluate_succeeds_once_league_in_evaluation(api):
    """PRD §3.3: "Once the league has advanced to `EVALUATION`, a `LeagueAdmin`
    records evaluation scores, moving an `AGE_VERIFIED` player to `EVALUATED`."

    Design: Difficulty/cross_entity_state_dependency/player_evaluate_depends_on_league_status
    """
    league = fx.create_league(draft_snake=True)
    fx.set_clock("2026-06-01T00:00:00Z")
    division = fx.create_division(league["id"])
    family = fx.create_family(league["id"], volunteer_deposit_cents=0)
    fx.advance(league["id"], "REGISTRATION")
    p = fx.register_player(league["id"], family["id"], division["id"],
                          full_name="P1", birth_date="2015-01-15",
                          birth_certificate_ref="bc1")
    fx.verify_age(p["id"])
    fx.advance(league["id"], "EVALUATION")

    out = validate_success(api.evaluate_player(p["id"], {
        "eval_speed": 55, "eval_hitting": 55, "eval_fielding": 55,
    }, ADMIN))
    assert out["status"] == "EVALUATED", out["status"]


# ─────────────────────────────────────────────────────────────────────────────
# boundary_precision_check / empty_referee_set_blocks_game_start  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_confirmed_referee_set_blocks_start(api):
    """PRD §3.5: "A game may not start unless at least one of its referee
    assignments is `CONFIRMED` or `CHECKED_IN`; starting without a confirmed
    umpire is rejected with `ERR_NO_REFEREE_CONFIRMED`."

    Zero CONFIRMED/CHECKED_IN assignments (only a PROPOSED one) -> start rejected,
    game stays SCHEDULED.

    Design: Difficulty/boundary_precision_check/empty_referee_set_blocks_game_start
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    fx.propose_assignment(game["id"], s["referee"]["id"])

    resp = api.start_game(game["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_REFEREE_CONFIRMED.value)
    fetched = validate_success(api.get_game(game["id"], ADMIN))
    assert fetched["status"] == "SCHEDULED", fetched["status"]


def test_start_with_zero_assignments_blocked(api):
    """PRD §3.5: "starting without a confirmed umpire is rejected with
    `ERR_NO_REFEREE_CONFIRMED`."

    A game with NO referee assignments at all cannot start.

    Design: Difficulty/boundary_precision_check/empty_referee_set_blocks_game_start
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    resp = api.start_game(game["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NO_REFEREE_CONFIRMED.value)


# ─────────────────────────────────────────────────────────────────────────────
# resource_temporal_overlap / referee_time_overlap_no_buffer  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_referee_back_to_back_allowed_overlap_rejected(api):
    """PRD §3.7: "confirming is rejected with `ERR_REFEREE_TIME_CONFLICT` if the
    referee has any other `CONFIRMED` or `CHECKED_IN` assignment whose game's time
    window overlaps this game's window. That overlap uses the bare game intervals
    with no buffer — two assignments conflict when this game's start falls before
    the other game's end and the other game's start falls before this game's end;
    touching exactly at a boundary does not conflict."

    Referee CONFIRMED on 17:00-19:00 may confirm a back-to-back 19:00-21:00 game
    (boundary touch) but not an 18:00-20:00 game that truly overlaps.

    Design: Difficulty/resource_temporal_overlap/referee_time_overlap_no_buffer
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=3, max_games_per_day=10)
    ref = s["referee"]
    gA = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][0]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    aA = fx.propose_assignment(gA["id"], ref["id"])
    fx.confirm_assignment(aA["id"], ref["user_id"])

    gB = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][1]["id"],
        "2026-05-01T19:00:00Z", "2026-05-01T21:00:00Z")
    aB = fx.propose_assignment(gB["id"], ref["id"])
    gC = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][2]["id"],
        "2026-05-01T18:00:00Z", "2026-05-01T20:00:00Z")
    aC = fx.propose_assignment(gC["id"], ref["id"])

    out_b = validate_success(api.confirm_assignment(
        aB["id"], make_referee_headers(ref["user_id"])))
    assert out_b["status"] == "CONFIRMED", out_b["status"]

    resp_c = api.confirm_assignment(aC["id"], make_referee_headers(ref["user_id"]))
    validate_error(resp_c, ApiErrorId.ERR_REFEREE_TIME_CONFLICT.value)


def test_referee_overlapping_game_confirm_rejected(api):
    """PRD §3.7: "confirming is rejected with `ERR_REFEREE_TIME_CONFLICT` if the
    referee has any other `CONFIRMED` or `CHECKED_IN` assignment whose game's time
    window overlaps this game's window. That overlap uses the bare game intervals
    with no buffer — two assignments conflict when this game's start falls before
    the other game's end and the other game's start falls before this game's end".

    Design: Difficulty/resource_temporal_overlap/referee_time_overlap_no_buffer
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=2, max_games_per_day=10)
    ref = s["referee"]
    gA = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][0]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    aA = fx.propose_assignment(gA["id"], ref["id"])
    fx.confirm_assignment(aA["id"], ref["user_id"])

    gC = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][1]["id"],
        "2026-05-01T18:00:00Z", "2026-05-01T20:00:00Z")
    aC = fx.propose_assignment(gC["id"], ref["id"])
    resp = api.confirm_assignment(aC["id"], make_referee_headers(ref["user_id"]))
    validate_error(resp, ApiErrorId.ERR_REFEREE_TIME_CONFLICT.value)


# ─────────────────────────────────────────────────────────────────────────────
# compensating_invariant / confirm_release_conserves_referee_day_occupancy  (A)
# ─────────────────────────────────────────────────────────────────────────────

def test_release_frees_day_occupancy_for_reconfirm(api):
    """PRD §3.7: "confirming is rejected with `ERR_REFEREE_DAY_LIMIT` if the
    referee already holds that many `CONFIRMED` or `CHECKED_IN` assignments on the
    game's UTC calendar day." §3.7: "a `LeagueAdmin` may release a `CONFIRMED`
    assignment, moving it to the terminal `RELEASED` status".

    With max_games_per_day=1, releasing the first CONFIRMED assignment frees the
    day so a second same-day game can be confirmed.

    Design: Difficulty/compensating_invariant/confirm_release_conserves_referee_day_occupancy
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1, max_games_per_day=1)
    ref = s["referee"]
    gA = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    aA = fx.propose_assignment(gA["id"], ref["id"])
    fx.confirm_assignment(aA["id"], ref["user_id"])
    gB = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T20:00:00Z", "2026-05-01T22:00:00Z")
    aB = fx.propose_assignment(gB["id"], ref["id"])

    released = validate_success(api.release_assignment(aA["id"], ADMIN))
    assert released["status"] == "RELEASED", released["status"]

    out_b = validate_success(api.confirm_assignment(
        aB["id"], make_referee_headers(ref["user_id"])))
    assert out_b["status"] == "CONFIRMED", out_b["status"]


def test_release_sets_assignment_released(api):
    """PRD §3.7: "a `LeagueAdmin` may release a `CONFIRMED` assignment, moving it
    to the terminal `RELEASED` status".

    Design: Difficulty/compensating_invariant/confirm_release_conserves_referee_day_occupancy
    """
    s = fx.setup_game_with_confirmed_referee(max_games_per_day=1)
    released = validate_success(api.release_assignment(s["assignment"]["id"], ADMIN))
    assert released["status"] == "RELEASED", released["status"]


# ─────────────────────────────────────────────────────────────────────────────
# cross_cutting / referee_day_limit_threshold_boundary  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_referee_day_limit_at_cap(api):
    """PRD §3.7: "the referee may not exceed their `max_games_per_day`: confirming
    is rejected with `ERR_REFEREE_DAY_LIMIT` if the referee already holds that
    many `CONFIRMED` or `CHECKED_IN` assignments on the game's UTC calendar day."

    max_games_per_day=1, already 1 CONFIRMED that day -> second same-day confirm
    rejected.

    Design: Corner/cross_cutting_complexity_layers/referee_day_limit_threshold_boundary
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=2, max_games_per_day=1)
    ref = s["referee"]
    gA = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][0]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    aA = fx.propose_assignment(gA["id"], ref["id"])
    fx.confirm_assignment(aA["id"], ref["user_id"])
    gB = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["fields"][1]["id"],
        "2026-05-01T20:00:00Z", "2026-05-01T22:00:00Z")
    aB = fx.propose_assignment(gB["id"], ref["id"])

    resp = api.confirm_assignment(aB["id"], make_referee_headers(ref["user_id"]))
    validate_error(resp, ApiErrorId.ERR_REFEREE_DAY_LIMIT.value)


# ─────────────────────────────────────────────────────────────────────────────
# rbac / referee_confirm_only_own_assignment  (B)
# ─────────────────────────────────────────────────────────────────────────────

def test_referee_cannot_confirm_others_assignment(api):
    """PRD §2.1: "When `X-User-Role` is `Referee`, the role is entity-backed by
    `Referee`: `X-User-ID` is the `user_id` of the acting `Referee`. Ownership
    checks on any assignment compare the assignment's referee — resolved through
    `referee_id` to that `Referee`'s `user_id` — against `X-User-ID`."

    ref-2 confirming an assignment proposed to ref-1 is forbidden.

    Design: Corner/rbac/referee_confirm_only_own_assignment
    """
    s = fx.setup_league_in_season(num_teams=2, num_fields=1)
    r1 = s["referee"]  # user_id ref-1
    fx.create_referee(s["league"]["id"], user_id="ref-2", full_name="Ref Two",
                      max_games_per_day=10)
    game = fx.schedule_game(
        s["league"]["id"], s["division"]["id"],
        s["teams"][0]["id"], s["teams"][1]["id"], s["field"]["id"],
        "2026-05-01T17:00:00Z", "2026-05-01T19:00:00Z")
    a1 = fx.propose_assignment(game["id"], r1["id"])

    resp = api.confirm_assignment(a1["id"], make_referee_headers("ref-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
