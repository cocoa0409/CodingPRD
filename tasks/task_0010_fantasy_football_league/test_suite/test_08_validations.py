"""Validations: veto self-interest, drop-player not on roster,
IR-as-starter rejection, keeper limit, snake-cost-cents rule, and
missing auth headers.

Translates Difficulty rule `priority_pair_validation_conflict` (instance B
only — instance A skipped because PRD §2.5 uniquely derives
ERR_STALE_WAIVER_VERSION, not ERR_INVALID_STATE) and the Corner
`validations` and `errors` sections.
"""
import pytest

from test_helpers import (
    accept_trade,
    api_client,
    create_player,
    create_team,
    create_league,
    finalize_draft,
    make_team_owner_headers,
    propose_trade,
    set_clock,
    setup_in_season_league,
    start_draft,
    submit_waiver_claim,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ─── Difficulty rule 5 instance B — business_safety wins on set-lineup ─────


def test_set_lineup_with_ir_placed_player_returns_invalid_starter(
    api, commissioner_headers,
):
    """PRD §3.5: "Starters are never allowed to be in `IR_PLACED` status —
    the safety check fires for both set-lineup and matchup-start, rejecting
    with `ERR_INVALID_STARTER_PLAYER` if a starter has `IR_PLACED` status
    or if a listed `starter_player_ids` member is not actually on the
    team's roster."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_business_safety_vs_business_referential_on_starter_assignment
    """
    set_clock("2026-11-21T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Pri2 L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 2, "ir_slot_count": 1,
            "faab_budget_cents": 5000, "veto_threshold": 1,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B"], divisions=["E", "E"],
    )
    ta, tb = ctx["teams"]
    # Pick the first A player; report-injury then place-on-IR.
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    px = validate_success(
        api.get_player(pa["player_id"], commissioner_headers),
        expected_status=200,
    )
    px_after = validate_success(
        api.report_injury(px["id"], px["version"], commissioner_headers),
        expected_status=200,
    )
    ta_v = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )["version"]
    validate_success(
        api.place_on_ir(
            ta["id"], px_after["id"], ta_v, make_team_owner_headers(ta["id"]),
        ),
        expected_status=200,
    )
    # Now try to set-lineup naming the IR_PLACED player as a starter.
    ta_v2 = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )["version"]
    res = api.set_lineup(
        ta["id"], [px_after["id"]], ta_v2, make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_INVALID_STARTER_PLAYER", expected_status=422)


def test_set_lineup_with_player_not_on_roster_returns_invalid_starter(
    api, commissioner_headers,
):
    """PRD §3.5: "rejecting with `ERR_INVALID_STARTER_PLAYER` if a starter
    has `IR_PLACED` status or if a listed `starter_player_ids` member is
    not actually on the team's roster."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_business_safety_vs_business_referential_on_starter_assignment
    """
    set_clock("2026-11-21T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pz = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    # Team A attempts set-lineup naming a player on B's roster.
    ta_v = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )["version"]
    res = api.set_lineup(
        ta["id"], [pz["player_id"]], ta_v, make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_INVALID_STARTER_PLAYER", expected_status=422)


# ─── Corner validations ────────────────────────────────────────────────────


def test_veto_vote_by_proposing_team_rejected(api, commissioner_headers):
    """PRD §3.8: "any neutral `TeamOwner` — neither the proposer nor the
    target — may cast a vote against it. The vote payload supplies the
    `voter_team_id`, the `vote` value (which must be `VETO` or `ALLOW`), and
    `expected_trade_version` for OCC. A voter that is the proposer or the
    target is rejected with `ERR_VETO_SELF_INTEREST`."

    Design: Corner/validations/veto_vote_by_proposing_team_rejected
    """
    set_clock("2026-10-04T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Self L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": 2,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B", "C", "D"],
        divisions=["E", "E", "W", "W"],
    )
    ta, tb, tc, td = ctx["teams"]
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    pc = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    trade = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
    )
    accepted = accept_trade(trade, tb)
    # Proposer attempts to vote — rejected.
    res = api.cast_veto_vote(
        accepted["id"], ta["id"], "VETO", accepted["version"],
        make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_VETO_SELF_INTEREST", expected_status=422)


def test_waiver_drop_player_not_on_claiming_teams_roster_rejected(
    api, commissioner_headers,
):
    """PRD §3.4: "an optional `drop_player_id` for the player the team will
    drop if the claim wins (which, if supplied, must currently be on the
    claiming team's roster, otherwise `ERR_DROP_PLAYER_NOT_ON_ROSTER`)".

    Design: Corner/validations/drop_player_not_on_roster_rejected
    """
    set_clock("2026-10-05T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pb_pick = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    fa = create_player("FA", "WR", "FA", projected_points=8.0, replacement_value=3.0)
    # Team A submits a waiver claim with drop_player_id pointing at B's player.
    res = api.create_waiver_claim(
        {
            "league_id": ctx["league"]["id"], "team_id": ta["id"],
            "player_id": fa["id"], "bid_cents": 100,
            "drop_player_id": pb_pick["player_id"],
            "processing_week": 1,
        },
        make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_DROP_PLAYER_NOT_ON_ROSTER", expected_status=422)


# ─── Corner errors ─────────────────────────────────────────────────────────


def test_keeper_count_exceeding_limit_returns_keeper_over_limit(
    api, commissioner_headers,
):
    """PRD §3.9: "the array's length must not exceed the league's
    `keeper_limit`, and every member must currently be on the acting team's
    roster, otherwise `ERR_KEEPER_OVER_LIMIT`."

    Design: Corner/errors/error_keeper_over_limit_triggered
    """
    set_clock("2026-10-08T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "KOL L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": 1,
            "keeper_limit": 1, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B"], divisions=["E", "E"],
    )
    ta = ctx["teams"][0]
    pa = [p for p in ctx["picks"] if p["team_id"] == ta["id"]]
    p1_id = pa[0]["player_id"]
    p2_id = pa[1]["player_id"]
    ta_v = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )["version"]
    res = api.update_keepers(
        ta["id"], [p1_id, p2_id], ta_v, make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_KEEPER_OVER_LIMIT", expected_status=422)


def test_snake_draft_pick_with_nonzero_cost_returns_auction_bid_invalid(
    api, commissioner_headers,
):
    """PRD §3.2: "in a `SNAKE` league, every pick's `cost_cents` must be
    exactly 0".
    PRD §2.7: "the auction-bid constraint (`ERR_AUCTION_BID_INVALID`)".

    Design: Corner/errors/error_auction_bid_invalid_on_snake_with_cost
    """
    set_clock("2026-10-09T00:00:00Z")
    league = create_league(
        name="SnB L", draft_type="SNAKE", roster_size=2, starter_slot_count=1,
        ir_slot_count=0, faab_budget_cents=5000, veto_threshold=1,
        keeper_limit=0, playoff_team_count=2, tiebreak_rule="STANDARD",
    )
    ta = create_team(league["id"], "A", "E")
    tb = create_team(league["id"], "B", "E")
    p1 = create_player("P1", "QB", "KC", projected_points=5.0, replacement_value=2.0)
    league = start_draft(league["id"])
    res = api.create_draft_pick(
        {
            "league_id": league["id"], "team_id": ta["id"],
            "player_id": p1["id"], "round": 1, "overall_pick": 1,
            "cost_cents": 500,
        },
        commissioner_headers,
    )
    validate_error(res, "ERR_AUCTION_BID_INVALID", expected_status=422)


# ─── Corner RBAC ───────────────────────────────────────────────────────────


def test_team_owner_cannot_create_player(api, commissioner_headers):
    """PRD §2.1: "If `X-User-Role` carries a value not in the two declared
    roles below, or names a role that is not permitted for the endpoint per
    §4's authorized-role column, the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    The endpoint table in PRD §4 lists POST /players as Commissioner-only.

    Design: Corner/rbac/team_owner_cannot_create_player
    """
    set_clock("2026-11-30T00:00:00Z")
    league = create_league(name="RB L")
    team = create_team(league["id"], "Team", "E")
    res = api.create_player(
        {
            "full_name": "Sneaky", "position": "QB", "nfl_team": "KC",
            "projected_points": 10.0, "replacement_value": 5.0,
        },
        make_team_owner_headers(team["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_team_owner_acting_on_another_team_returns_forbidden(api, commissioner_headers):
    """PRD §2.1: "A `TeamOwner` whose `X-User-ID` does not match the
    relevant team is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/team_owner_acting_as_other_team_blocked
    """
    set_clock("2026-10-11T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    p_b = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    tb_v = validate_success(
        api.get_team(tb["id"], commissioner_headers), expected_status=200,
    )["version"]
    # Owner of TA tries to set-lineup on TB.
    res = api.set_lineup(
        tb["id"], [p_b["player_id"]], tb_v,
        make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_user_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_user_role_header_returns_unauthenticated
    """
    res = api.list_leagues(headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
