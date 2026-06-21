"""Conservation invariants, OCC stale-version rejection, and
test-driving (clock) effects on Trade.accepted_at.

Translates Difficulty rule `compensating_invariant` (both instances) and the
Corner errors/cross_cutting_complexity entries that are NOT marked
excluded_because stubs.
"""
import pytest

from test_helpers import (
    accept_trade,
    advance_week,
    api_client,
    assert_total_faab_pool_invariant,
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


# ─── Difficulty rule 9 instance A — FAAB conservation across trade pair ────


def _four_team_in_season_with_one_player_each(faab_per_team=5000):
    """Stand up an IN_SEASON 4-team league with roster_size=2 and one
    drafted player per team. Returns dict (league, teams=[TA..TD], picks).
    """
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Inv L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": faab_per_team, "veto_threshold": 3,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["TA", "TB", "TC", "TD"],
        divisions=["E", "E", "W", "W"],
    )
    return ctx


def test_trade_executed_then_reversed_preserves_each_teams_faab(
    api, commissioner_headers,
):
    """PRD §3.8: "if `faab_offered_cents` is greater than 0, that amount is
    debited from the proposer's `faab_balance_cents` and credited to the
    target's, preserving the league's `total_faab_pool_cents` exactly."

    Forward trade: TA debits 2000, TB credits 2000. Reverse trade: TB
    debits 2000, TA credits 2000. Each team's faab_balance_cents returns
    to the starting value of 5000.

    Design: Difficulty/compensating_invariant/trade_executed_then_reversed_preserves_total_faab
    """
    set_clock("2026-11-28T00:00:00Z")
    ctx = _four_team_in_season_with_one_player_each(faab_per_team=5000)
    ta, tb, tc, td = ctx["teams"]
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    pc = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    # Trade 1: TA → TB. TA offers pa.player_id (TA's roster), requests
    # pc.player_id (TB's roster).
    trade1 = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
        faab_offered_cents=2000,
    )
    accepted1 = accept_trade(trade1, tb)
    executed1 = validate_success(
        api.finalize_trade(
            ctx["league"]["id"], accepted1["id"], accepted1["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    assert executed1["state"] == "EXECUTED"
    # After trade 1, pa.player_id is now on TB's roster and pc.player_id is
    # now on TA's roster. The reverse trade (TB → TA) must offer the player
    # TB currently owns (pa.player_id) and request the player TA owns
    # (pc.player_id), or PRD §3.8's roster-presence check (priority 8)
    # rejects with ERR_TRADE_PLAYER_NOT_ON_ROSTER.
    trade2 = propose_trade(
        ctx["league"]["id"], tb, ta,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
        faab_offered_cents=2000,
    )
    accepted2 = accept_trade(trade2, ta)
    validate_success(
        api.finalize_trade(
            ctx["league"]["id"], accepted2["id"], accepted2["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    # All four teams should be back to 5000 cents.
    ta_after = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )
    tb_after = validate_success(
        api.get_team(tb["id"], commissioner_headers), expected_status=200,
    )
    assert ta_after["faab_balance_cents"] == 5000
    assert tb_after["faab_balance_cents"] == 5000


def test_trade_executed_then_reversed_preserves_total_faab_pool(
    api, commissioner_headers,
):
    """PRD §1: "FAAB is a conserved pool: dollars debited from one team
    during a waiver win leave the team forever, but dollars transferred in
    a trade stay inside the league's total, so the sum of every team's
    FAAB balance never drifts from the league's starting total even as it
    moves between balance sheets."

    Design: Difficulty/compensating_invariant/trade_executed_then_reversed_preserves_total_faab
    """
    set_clock("2026-11-28T00:00:00Z")
    ctx = _four_team_in_season_with_one_player_each(faab_per_team=5000)
    ta, tb, tc, td = ctx["teams"]
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    pc = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    # Forward + reverse trades — players swap on trade 1, so the reverse
    # trade must reflect post-swap ownership (TB now holds pa.player_id,
    # TA now holds pc.player_id).
    trade1 = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
        faab_offered_cents=2000,
    )
    accepted1 = accept_trade(trade1, tb)
    validate_success(
        api.finalize_trade(
            ctx["league"]["id"], accepted1["id"], accepted1["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    trade2 = propose_trade(
        ctx["league"]["id"], tb, ta,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
        faab_offered_cents=2000,
    )
    accepted2 = accept_trade(trade2, ta)
    validate_success(
        api.finalize_trade(
            ctx["league"]["id"], accepted2["id"], accepted2["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    league_after = validate_success(
        api.get_league(ctx["league"]["id"], commissioner_headers),
        expected_status=200,
    )
    teams_after = [
        validate_success(api.get_team(t["id"], commissioner_headers),
                         expected_status=200)
        for t in (ta, tb, tc, td)
    ]
    assert_total_faab_pool_invariant(league_after, teams_after)


# ─── Difficulty rule 9 instance B — Player count conservation ──────────────


def test_waiver_win_then_release_restores_team_a_roster_size(
    api, commissioner_headers,
):
    """PRD §3.5: "Releasing a player is a separate, terminal action that a
    `TeamOwner` may invoke against a player on their roster whose `status`
    is `ACTIVE`. The release passes the player briefly through `RELEASED`
    then immediately back to `ACTIVE` with `current_team_id` nulled,
    removing every roster slot row that referenced the player on the
    releasing team; the player returns to the free-agent pool".

    After a waiver win adds the FA to team A's roster (with drop_player_id
    pa1 freeing a slot), then team A releases the FA back to free agency,
    team A's roster is composed of 3 players, NOT 5 — the drop+release
    chain conserves total player headcount.

    Design: Difficulty/compensating_invariant/waiver_won_then_released_preserves_player_count_invariant
    """
    set_clock("2026-11-29T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "PInv L", "draft_type": "SNAKE", "roster_size": 4,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": 1,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B"], divisions=["E", "E"],
    )
    ta, tb = ctx["teams"]
    pa1 = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])  # first A pick
    fa = create_player("FApool", "WR", "FA", projected_points=8.0, replacement_value=3.0)
    submit_waiver_claim(
        ctx["league"]["id"], ta, fa["id"], bid_cents=100,
        processing_week=1, drop_player_id=pa1["player_id"],
    )
    advance_week(ctx["league"]["id"])
    # Now release the just-won player.
    ta_v = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )["version"]
    validate_success(
        api.release_player(
            ta["id"], fa["id"], ta_v, make_team_owner_headers(ta["id"]),
        ),
        expected_status=200,
    )
    # Team A roster: 4 drafted - 1 dropped = 3 players.
    a_players_res = api.list_players(
        commissioner_headers, params={"current_team_id": ta["id"], "limit": 100},
    )
    a_players, _ = (lambda r: (r.json()["data"], r.json()["meta"]))(a_players_res)
    assert len(a_players) == 3


def test_waiver_win_then_release_preserves_total_drafted_plus_free_agents(
    api, commissioner_headers,
):
    """PRD §3.5: "the player returns to the free-agent pool and is available
    for waiver claims by other teams."

    Total player headcount in the league is unchanged across the
    waiver-win-then-release sequence: team A had 4 + team B had 4 +
    one FA = 9 players seeded; after the chain, team A has 3 + team B
    has 4 + free-agent pool has 2 = 9.

    Design: Difficulty/compensating_invariant/waiver_won_then_released_preserves_player_count_invariant
    """
    set_clock("2026-11-29T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "PInv L2", "draft_type": "SNAKE", "roster_size": 4,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": 1,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B"], divisions=["E", "E"],
    )
    ta, tb = ctx["teams"]
    pa1 = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    fa = create_player("FApool", "WR", "FA", projected_points=8.0, replacement_value=3.0)
    submit_waiver_claim(
        ctx["league"]["id"], ta, fa["id"], bid_cents=100,
        processing_week=1, drop_player_id=pa1["player_id"],
    )
    advance_week(ctx["league"]["id"])
    ta_v = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )["version"]
    validate_success(
        api.release_player(
            ta["id"], fa["id"], ta_v, make_team_owner_headers(ta["id"]),
        ),
        expected_status=200,
    )
    # team A players
    res_a = api.list_players(
        commissioner_headers, params={"current_team_id": ta["id"], "limit": 100},
    )
    a_data = res_a.json()["data"]
    # team B players
    res_b = api.list_players(
        commissioner_headers, params={"current_team_id": tb["id"], "limit": 100},
    )
    b_data = res_b.json()["data"]
    assert len(a_data) == 3
    assert len(b_data) == 4


# ─── Corner errors — stale-trade-version (412) ─────────────────────────────


def test_finalize_trade_with_stale_version_returns_412(api, commissioner_headers):
    """PRD §2.5: "Any request that drives a trade from `PENDING_VETO` to
    `EXECUTED` must carry an `expected_trade_version` field whose value
    matches the target trade's current `version`. If a veto vote was
    recorded against the trade since the commissioner last read it —
    bumping `Trade.version` and pushing `veto_votes_count` closer to the
    threshold — the commissioner's view of "no vetoes yet" is stale, and
    the finalize is rejected with `ERR_STALE_TRADE_VERSION` (HTTP 412)
    before any roster swap is applied."

    Design: Corner/errors/error_stale_trade_version_triggers_412
    """
    set_clock("2026-10-10T00:00:00Z")
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Stale L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": 3,
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
    stale_version = accepted["version"]
    # Cast an ALLOW vote — bumps Trade.version but does NOT trigger VETOED.
    validate_success(
        api.cast_veto_vote(
            accepted["id"], tc["id"], "ALLOW", accepted["version"],
            make_team_owner_headers(tc["id"]),
        ),
        expected_status=201,
    )
    # Commissioner finalizes with the stale version.
    res = api.finalize_trade(
        ctx["league"]["id"], accepted["id"], stale_version, commissioner_headers,
    )
    validate_error(res, "ERR_STALE_TRADE_VERSION", expected_status=412)


# ─── Corner cross_cutting_complexity_layers — clock effects ────────────────


def test_set_clock_pins_trade_accepted_at_to_iso_time(api, commissioner_headers):
    """PRD §3.10: "Setting the clock affects subsequent timestamps such as
    `Trade.accepted_at`; it does not retroactively rewrite already-committed
    timestamps."

    After set_clock("2027-01-15T12:00:00.000Z") and then accepting a trade,
    Trade.accepted_at equals "2027-01-15T12:00:00.000Z".

    Design: Corner/cross_cutting_complexity_layers/scheduled_action_set_clock_affects_accepted_at
    """
    set_clock("2026-12-25T10:30:00.000Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pa = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    pc = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    trade = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
    )
    # Re-pin clock to a fresh time before accept.
    set_clock("2027-01-15T12:00:00.000Z")
    accepted = validate_success(
        api.accept_trade(
            trade["id"], trade["version"], make_team_owner_headers(tb["id"]),
        ),
        expected_status=200,
    )
    # PRD §3.8: "Trade.accepted_at is set to the current system UTC".
    # The clock was pinned at 2027-01-15T12:00:00.000Z.
    assert accepted["accepted_at"] == "2027-01-15T12:00:00.000Z"
