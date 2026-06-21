"""Trade lifecycle, veto-threshold boundary, and trade-related cross-entity
state dependencies.

Translates Difficulty rule `boundary_precision_check` (instance A — veto
threshold) and `cross_entity_state_dependency` (instance A — trade
finalize blocked during matchup).
"""
import pytest

from test_helpers import (
    api_client,
    create_regular_matchup,
    make_team_owner_headers,
    propose_trade,
    accept_trade,
    cast_veto_vote,
    set_clock,
    setup_in_season_league,
    start_matchup,
    validate_error,
    validate_success,
)


# ─── Difficulty rule 6 instance A — veto threshold exact-count boundary ────


def _four_team_in_season_with_pending_veto_trade(veto_threshold=2):
    """Stand up an IN_SEASON 4-team league (TA-TD), propose+accept a trade
    between TA and TB. Trade is now in PENDING_VETO. Returns dict.
    """
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Veto L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": veto_threshold,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["TA", "TB", "TC", "TD"],
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
    return {
        "league": ctx["league"], "ta": ta, "tb": tb, "tc": tc, "td": td,
        "trade": accepted,
    }


def test_veto_count_below_threshold_remains_pending_veto(api, commissioner_headers):
    """PRD §3.8: "Each recorded `VETO` vote increments
    `Trade.veto_votes_count` by 1".
    PRD §3.8: "When `veto_votes_count + 1` first reaches the league's
    `veto_threshold` upon recording a new `VETO` vote — that is, after this
    vote is committed, the count would be at or above the threshold — the
    trade auto-transitions to the terminal `VETOED`".

    With veto_threshold=2 and one VETO vote, the trade remains in
    PENDING_VETO (1 < 2).

    Design: Difficulty/boundary_precision_check/veto_threshold_exact_count_triggers_veto
    """
    set_clock("2026-11-22T00:00:00Z")
    ctx = _four_team_in_season_with_pending_veto_trade(veto_threshold=2)
    cast_veto_vote(ctx["trade"], ctx["tc"], vote="VETO")
    trade_after = validate_success(
        api.get_trade(ctx["trade"]["id"], commissioner_headers),
        expected_status=200,
    )
    assert trade_after["state"] == "PENDING_VETO"
    assert trade_after["veto_votes_count"] == 1


def test_veto_count_at_threshold_triggers_terminal_vetoed(api, commissioner_headers):
    """PRD §3.8: "When `veto_votes_count + 1` first reaches the league's
    `veto_threshold` upon recording a new `VETO` vote — that is, after this
    vote is committed, the count would be at or above the threshold — the
    trade auto-transitions to the terminal `VETOED`, no roster swap occurs,
    and FAAB is unchanged."

    With veto_threshold=2 and TWO VETO votes recorded, the trade is VETOED.

    Design: Difficulty/boundary_precision_check/veto_threshold_exact_count_triggers_veto
    """
    set_clock("2026-11-22T00:00:00Z")
    ctx = _four_team_in_season_with_pending_veto_trade(veto_threshold=2)
    # First vote (from TC).
    trade_after_1 = cast_veto_vote(ctx["trade"], ctx["tc"], vote="VETO")
    # Re-read trade to capture updated version after the first VETO.
    trade_after_1_read = validate_success(
        api.get_trade(ctx["trade"]["id"], commissioner_headers),
        expected_status=200,
    )
    # Second vote (from TD) — should trigger VETOED.
    cast_veto_vote(trade_after_1_read, ctx["td"], vote="VETO")
    trade_after_2 = validate_success(
        api.get_trade(ctx["trade"]["id"], commissioner_headers),
        expected_status=200,
    )
    assert trade_after_2["state"] == "VETOED"
    assert trade_after_2["veto_votes_count"] == 2


# ─── Difficulty rule 7 instance A — trade finalize blocked by IN_PROGRESS matchup ─


def test_trade_finalize_blocked_when_matchup_in_progress(api, commissioner_headers):
    """PRD §3.8: "no `PlayoffMatchup` with this league's id is currently
    `IN_PROGRESS` (otherwise `ERR_TRADE_LOCKED_DURING_GAME`)".

    Design: Difficulty/cross_entity_state_dependency/trade_finalize_blocked_when_matchup_in_progress
    """
    set_clock("2026-11-24T00:00:00Z")
    ctx = _four_team_in_season_with_pending_veto_trade(veto_threshold=3)
    # Start a matchup between the OTHER two teams (TC vs TD), placing one
    # PlayoffMatchup in IN_PROGRESS state.
    matchup = create_regular_matchup(
        ctx["league"]["id"], 1, ctx["tc"], ctx["td"],
    )
    start_matchup(matchup)
    # Now commissioner attempts to finalize the trade.
    res = api.finalize_trade(
        ctx["league"]["id"], ctx["trade"]["id"], ctx["trade"]["version"],
        commissioner_headers,
    )
    validate_error(res, "ERR_TRADE_LOCKED_DURING_GAME", expected_status=409)


def test_trade_finalize_succeeds_when_no_matchup_in_progress(api, commissioner_headers):
    """PRD §3.8: "the league's `status` is `IN_SEASON`, no `PlayoffMatchup`
    with this league's id is currently `IN_PROGRESS` ... The finalize moves
    the trade to `EXECUTED`".

    Positive counter-check: with NO matchup in progress, the same finalize
    succeeds.

    Design: Difficulty/cross_entity_state_dependency/trade_finalize_blocked_when_matchup_in_progress
    """
    set_clock("2026-11-24T00:00:00Z")
    ctx = _four_team_in_season_with_pending_veto_trade(veto_threshold=3)
    res = api.finalize_trade(
        ctx["league"]["id"], ctx["trade"]["id"], ctx["trade"]["version"],
        commissioner_headers,
    )
    executed = validate_success(res, expected_status=200)
    assert executed["state"] == "EXECUTED"


# ─── Difficulty rule 8 instance A — player can't be on two teams ───────────


def test_trade_offering_player_not_on_proposers_roster_rejected(
    api, commissioner_headers,
):
    """PRD §3.8: "an array `players_offered` of 1 to 5 player ids the
    proposer would send (every member must currently sit on the proposer's
    roster, otherwise `ERR_TRADE_PLAYER_NOT_ON_ROSTER`)".

    Team B proposes trade offering team A's player_x — rejected.

    Design: Difficulty/resource_temporal_overlap/player_cannot_be_on_two_teams_in_same_week
    """
    set_clock("2026-11-26T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    pb = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    res = api.create_trade(
        {
            "league_id": ctx["league"]["id"],
            "proposing_team_id": tb["id"],
            "target_team_id": ta["id"],
            "players_offered": [pa["player_id"]],  # belongs to A, not B!
            "players_requested": [pb["player_id"]],
            "faab_offered_cents": 0,
        },
        make_team_owner_headers(tb["id"]),
    )
    validate_error(res, "ERR_TRADE_PLAYER_NOT_ON_ROSTER", expected_status=422)


def test_trade_requesting_player_not_on_targets_roster_rejected(
    api, commissioner_headers,
):
    """PRD §3.8: "an array `players_requested` of 1 to 5 player ids the
    target would send (with the symmetric roster check against the target's
    roster)".

    Symmetric: team A proposes requesting a player not on B's roster.

    Design: Difficulty/resource_temporal_overlap/player_cannot_be_on_two_teams_in_same_week
    """
    set_clock("2026-11-26T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    pa2_belongs_to_a = [p for p in ctx["picks"] if p["team_id"] == ta["id"]][1]
    # Request a player from team B's roster -- but actually pass an A player
    # in players_requested, violating the symmetric rule.
    res = api.create_trade(
        {
            "league_id": ctx["league"]["id"],
            "proposing_team_id": ta["id"],
            "target_team_id": tb["id"],
            "players_offered": [pa["player_id"]],
            "players_requested": [pa2_belongs_to_a["player_id"]],
            "faab_offered_cents": 0,
        },
        make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_TRADE_PLAYER_NOT_ON_ROSTER", expected_status=422)
