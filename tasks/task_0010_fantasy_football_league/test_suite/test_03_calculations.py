"""Injury-replacement projection (PRD §3.6), trade fairness scoring
(PRD §3.8), and dynasty-keeper cost (PRD §3.9).

Translates Difficulty rule `combinatorial_formula` (both instances) and the
Corner `calculations` section.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    advance_week,
    create_league,
    create_player,
    create_team,
    create_regular_matchup,
    draft_pairs_serpent,
    finalize_draft,
    finalize_matchup_auto,
    make_team_owner_headers,
    propose_trade,
    set_clock,
    set_lineup_for_team,
    start_draft,
    start_matchup,
    validate_success,
)


# ─── Difficulty rule 2 instance A — injury replacement projection ──────────

def _setup_three_starter_home_one_away_league(starter_count=3, ir_slot_count=1):
    """Stand up a league with home_team having 3 starters and away having
    enough roster to fill draft, then run a draft, set lineups, and start
    a regular-season matchup at week=1. Returns dict with everything needed
    for the injury-replacement test.
    """
    league = create_league(
        name="Injury L", draft_type="SNAKE", roster_size=starter_count,
        starter_slot_count=starter_count, ir_slot_count=ir_slot_count,
        faab_budget_cents=10000, veto_threshold=1, keeper_limit=0,
        playoff_team_count=2, tiebreak_rule="STANDARD",
    )
    home = create_team(league["id"], "Home", "E")
    away = create_team(league["id"], "Away", "E")
    # Home starters: ACTIVE pp=12.0, INJURED pp=10.0, IR_PLACED pp=14.0.
    p_active = create_player("P_Active", "QB", "KC", projected_points=12.0,
                              replacement_value=5.0)
    p_injured = create_player("P_Injured", "RB", "KC", projected_points=10.0,
                              replacement_value=5.0)
    p_ir = create_player("P_IR", "WR", "KC", projected_points=14.0,
                          replacement_value=5.0)
    # Away starters: ACTIVE pp=5.0 + two pp=1.0 fillers.
    p_away_active = create_player("P_Away_Active", "QB", "BUF",
                                   projected_points=5.0, replacement_value=2.0)
    p_away_f1 = create_player("P_Away_F1", "RB", "BUF",
                               projected_points=1.0, replacement_value=1.0)
    p_away_f2 = create_player("P_Away_F2", "WR", "BUF",
                               projected_points=1.0, replacement_value=1.0)
    league = start_draft(league["id"])
    # Snake draft: 6 players × 2 teams × 3 rounds; tailored ordering.
    # Round 1: home, away (start with #1)
    # Round 2: away, home (reversed)
    # Round 3: home, away
    picks_order = [
        (home, p_active, 1, 1),
        (away, p_away_active, 1, 2),
        (away, p_away_f1, 2, 3),
        (home, p_injured, 2, 4),
        (home, p_ir, 3, 5),
        (away, p_away_f2, 3, 6),
    ]
    for team, player, rnd, ovr in picks_order:
        validate_success(
            api_client.create_draft_pick(
                {
                    "league_id": league["id"], "team_id": team["id"],
                    "player_id": player["id"], "round": rnd,
                    "overall_pick": ovr, "cost_cents": 0,
                },
                TEST_USERS["commissioner_headers"],
            ),
            expected_status=201,
        )
    finalize_draft(league["id"])
    set_lineup_for_team(home, [p_active["id"], p_injured["id"], p_ir["id"]])
    set_lineup_for_team(away, [p_away_active["id"], p_away_f1["id"], p_away_f2["id"]])
    # finalize_draft and set_lineup_for_team bump each Player.version when
    # current_team_id is assigned; refetch so callers receive fresh
    # `version` values for OCC-guarded endpoints like report_injury.
    def _refresh(p):
        return validate_success(
            api_client.get_player(p["id"], TEST_USERS["commissioner_headers"]),
            expected_status=200,
        )
    p_active = _refresh(p_active)
    p_injured = _refresh(p_injured)
    p_ir = _refresh(p_ir)
    p_away_active = _refresh(p_away_active)
    return {
        "league": league, "home": home, "away": away,
        "p_active": p_active, "p_injured": p_injured, "p_ir": p_ir,
        "p_away_active": p_away_active,
    }


def test_injury_replacement_projection_three_input_active_injured_ir(api, commissioner_headers):
    """PRD §3.6: "If the player's `status` is `ACTIVE`, that value is taken
    as-is. If the player's `status` is `INJURED`, the contribution becomes
    the projection minus an injury penalty of 4.0 points, with a floor of 0
    (so an injured player with a projection below 4.0 contributes 0, not a
    negative). If the player's `status` is `IR_PLACED` — an invalid
    configuration for a starter that nevertheless can happen if the player
    is moved to IR after the start lock — the contribution is treated as 0,
    the replacement-level fallback."

    Three home starters: ACTIVE pp=12.0 → 12.00; INJURED pp=10.0 → max(0,
    10-4)=6.00; IR_PLACED pp=14.0 → 0.00. Home score sum is 18.00.

    Design: Difficulty/combinatorial_formula/injury_replacement_projection_three_input_nonlinear
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = _setup_three_starter_home_one_away_league()
    matchup = create_regular_matchup(
        ctx["league"]["id"], 1, ctx["home"], ctx["away"],
    )
    matchup = start_matchup(matchup)
    # After start, status flips: injure both p_injured and p_ir; place p_ir on IR.
    p_injured = validate_success(
        api.report_injury(
            ctx["p_injured"]["id"], ctx["p_injured"]["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    p_ir = validate_success(
        api.report_injury(
            ctx["p_ir"]["id"], ctx["p_ir"]["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    home_v = validate_success(
        api.get_team(ctx["home"]["id"], commissioner_headers),
        expected_status=200,
    )["version"]
    validate_success(
        api.place_on_ir(
            ctx["home"]["id"], p_ir["id"], home_v,
            make_team_owner_headers(ctx["home"]["id"]),
        ),
        expected_status=200,
    )
    # Finalize with auto-compute; injury replacement should yield home=18.00.
    completed = finalize_matchup_auto(matchup)
    assert completed["home_score"] == pytest.approx(18.00, abs=0.001)


def test_injury_replacement_projection_away_team_three_active(api, commissioner_headers):
    """PRD §3.6: "Each per-line-item contribution is rounded half-up to two
    decimal places first; the per-line-rounded contributions are then summed
    for the team; the team's running sum is then itself rounded half-up to
    two decimal places to produce the final `home_score` (or `away_score`)."

    Three away starters all ACTIVE: pp=5.0, 1.0, 1.0 → 5.00 + 1.00 + 1.00 = 7.00.

    Design: Difficulty/combinatorial_formula/injury_replacement_projection_three_input_nonlinear
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = _setup_three_starter_home_one_away_league()
    matchup = create_regular_matchup(
        ctx["league"]["id"], 1, ctx["home"], ctx["away"],
    )
    matchup = start_matchup(matchup)
    # Don't injure the away team; both injuries are on home.
    p_injured = validate_success(
        api.report_injury(
            ctx["p_injured"]["id"], ctx["p_injured"]["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    p_ir = validate_success(
        api.report_injury(
            ctx["p_ir"]["id"], ctx["p_ir"]["version"],
            commissioner_headers,
        ),
        expected_status=200,
    )
    home_v = validate_success(
        api.get_team(ctx["home"]["id"], commissioner_headers),
        expected_status=200,
    )["version"]
    validate_success(
        api.place_on_ir(
            ctx["home"]["id"], p_ir["id"], home_v,
            make_team_owner_headers(ctx["home"]["id"]),
        ),
        expected_status=200,
    )
    completed = finalize_matchup_auto(matchup)
    assert completed["away_score"] == pytest.approx(7.00, abs=0.001)


# ─── Difficulty rule 2 instance B — trade fairness score (nested rounding) ─


def _setup_trade_fairness_league():
    """Stand up an IN_SEASON league with TWO teams; proposer has 4 players
    drafted (PA-PD), target has 4 (PE-PH). PA/PB/PC are the three offered
    players with the contrived projected_points = 12.34/7.86/4.55. Returns
    dict.
    """
    league = create_league(
        name="Trade L", draft_type="SNAKE", roster_size=4, starter_slot_count=2,
        ir_slot_count=0, faab_budget_cents=5000, veto_threshold=1,
        keeper_limit=0, playoff_team_count=2, tiebreak_rule="STANDARD",
    )
    prop = create_team(league["id"], "Prop", "E")
    targ = create_team(league["id"], "Targ", "E")
    pa = create_player("PA", "QB", "KC", projected_points=12.34, replacement_value=5.0)
    pb = create_player("PB", "RB", "KC", projected_points=7.86, replacement_value=3.0)
    pc = create_player("PC", "WR", "KC", projected_points=4.55, replacement_value=2.0)
    pd = create_player("PD", "TE", "KC", projected_points=6.0, replacement_value=2.0)
    pe = create_player("PE", "QB", "BUF", projected_points=8.0, replacement_value=3.0)
    pf = create_player("PF", "RB", "BUF", projected_points=5.0, replacement_value=2.0)
    pg = create_player("PG", "WR", "BUF", projected_points=4.0, replacement_value=2.0)
    ph = create_player("PH", "TE", "BUF", projected_points=3.0, replacement_value=1.0)
    start_draft(league["id"])
    # Draft order: snake with two teams over 4 rounds = 8 picks.
    order = [
        (prop, pa, 1, 1), (targ, pe, 1, 2),
        (targ, pf, 2, 3), (prop, pb, 2, 4),
        (prop, pc, 3, 5), (targ, pg, 3, 6),
        (targ, ph, 4, 7), (prop, pd, 4, 8),
    ]
    for team, player, rnd, ovr in order:
        validate_success(
            api_client.create_draft_pick(
                {
                    "league_id": league["id"], "team_id": team["id"],
                    "player_id": player["id"], "round": rnd,
                    "overall_pick": ovr, "cost_cents": 0,
                },
                TEST_USERS["commissioner_headers"],
            ),
            expected_status=201,
        )
    finalize_draft(league["id"])
    return {
        "league": league, "prop": prop, "targ": targ,
        "pa": pa, "pb": pb, "pc": pc, "pe": pe,
    }


def test_trade_fairness_offered_value_per_player_then_sum_then_round(api, commissioner_headers):
    """PRD §3.8: "The computation rounds each player's `projected_points`
    half-up to one decimal place first, sums the rounded values per side,
    then rounds the per-side sum half-up to two decimal places to get
    `offered_value` and `requested_value`".

    Offered pp = 12.34, 7.86, 4.55 → round-to-1 = 12.3, 7.9, 4.6 → sum =
    24.8 → 24.80.

    Design: Difficulty/combinatorial_formula/trade_fairness_score_nested_rounding_order_pinned
    """
    set_clock("2026-10-01T00:00:00Z")
    ctx = _setup_trade_fairness_league()
    trade = propose_trade(
        ctx["league"]["id"], ctx["prop"], ctx["targ"],
        players_offered=[ctx["pa"]["id"], ctx["pb"]["id"], ctx["pc"]["id"]],
        players_requested=[ctx["pe"]["id"]],
        faab_offered_cents=0,
    )
    res = api.get_trade_fairness(trade["id"], commissioner_headers)
    data = validate_success(res, expected_status=200)
    assert data["offered_value"] == pytest.approx(24.80, abs=0.001)


def test_trade_fairness_score_uses_absolute_difference_rounded_two_decimals(
    api, commissioner_headers,
):
    """PRD §3.8: "the FAAB delta is `faab_offered_cents` divided by 100 (so
    dollars, not cents); the final `fairness_score` is the absolute value of
    `offered_value` plus the FAAB delta minus `requested_value`, rounded
    half-up to two decimal places."

    With offered_value=24.80, requested_value=8.00 (PE pp=8.0 → round-to-1
    = 8.0 → sum 8.0 → 8.00), faab_delta=0.0, score = abs(24.80 + 0 - 8.00)
    = 16.80.

    Design: Difficulty/combinatorial_formula/trade_fairness_score_nested_rounding_order_pinned
    """
    set_clock("2026-10-01T00:00:00Z")
    ctx = _setup_trade_fairness_league()
    trade = propose_trade(
        ctx["league"]["id"], ctx["prop"], ctx["targ"],
        players_offered=[ctx["pa"]["id"], ctx["pb"]["id"], ctx["pc"]["id"]],
        players_requested=[ctx["pe"]["id"]],
        faab_offered_cents=0,
    )
    res = api.get_trade_fairness(trade["id"], commissioner_headers)
    data = validate_success(res, expected_status=200)
    assert data["fairness_score"] == pytest.approx(16.80, abs=0.001)


# ─── Corner Section 3 — keeper cost calculation ────────────────────────────


def _two_team_keeper_league(keeper_limit=2, roster_size=5):
    """Stand up an IN_SEASON two-team league with `roster_size` players per
    team and a configurable keeper_limit. Returns dict with league + teams
    + a player-name → dict map.
    """
    league = create_league(
        name="DK L", draft_type="SNAKE", roster_size=roster_size,
        starter_slot_count=1, ir_slot_count=0, faab_budget_cents=5000,
        veto_threshold=1, keeper_limit=keeper_limit, playoff_team_count=2,
        tiebreak_rule="STANDARD",
    )
    ta = create_team(league["id"], "A", "E")
    tb = create_team(league["id"], "B", "E")
    return {"league": league, "ta": ta, "tb": tb}


def test_dynasty_keeper_cost_two_keepers_round_decreases_by_one_each(
    api, commissioner_headers,
):
    """PRD §3.9: "The team's `keeper_player_ids` are walked in
    `Player.created_at` ascending order — never by player `id`. The first
    keeper in that order gets a cost equal to their `round` from the prior
    season's draft pick row; the second gets a cost equal to that
    prior-season round minus 1; the third minus 2; and so on for the index
    of the player in the sorted list. Every cost is floored at 1".

    Player pa1 is drafted round 3 and created first chronologically; pa2 is
    drafted round 5 and created second; both designated as keepers. Costs:
    pa1 → max(1, 3-0) = 3; pa2 → max(1, 5-1) = 4.

    Design: Corner/calculations/dynasty_keeper_cost_two_keepers_round_decreases_by_one_each
    """
    set_clock("2026-10-01T00:00:00Z")
    ctx = _two_team_keeper_league(keeper_limit=2, roster_size=5)
    pa1 = create_player("Pa1", "QB", "KC", projected_points=5.0, replacement_value=2.0)
    pa2 = create_player("Pa2", "RB", "KC", projected_points=5.0, replacement_value=2.0)
    pa3 = create_player("Pa3", "WR", "KC", projected_points=5.0, replacement_value=2.0)
    pa4 = create_player("Pa4", "TE", "KC", projected_points=5.0, replacement_value=2.0)
    pa5 = create_player("Pa5", "K", "KC", projected_points=5.0, replacement_value=2.0)
    pb1 = create_player("Pb1", "QB", "BUF", projected_points=5.0, replacement_value=2.0)
    pb2 = create_player("Pb2", "RB", "BUF", projected_points=5.0, replacement_value=2.0)
    pb3 = create_player("Pb3", "WR", "BUF", projected_points=5.0, replacement_value=2.0)
    pb4 = create_player("Pb4", "TE", "BUF", projected_points=5.0, replacement_value=2.0)
    pb5 = create_player("Pb5", "K", "BUF", projected_points=5.0, replacement_value=2.0)
    start_draft(ctx["league"]["id"])
    # We deliberately give pa1 round=3 and pa2 round=5.
    picks_layout = [
        (ctx["ta"], pa1, 3, 1),
        (ctx["tb"], pb1, 1, 2),
        (ctx["tb"], pb2, 2, 3),
        (ctx["ta"], pa2, 5, 4),
        (ctx["ta"], pa3, 5, 5),
        (ctx["tb"], pb3, 3, 6),
        (ctx["tb"], pb4, 4, 7),
        (ctx["ta"], pa4, 4, 8),
        (ctx["ta"], pa5, 5, 9),
        (ctx["tb"], pb5, 5, 10),
    ]
    pick_ids = {}
    for team, player, rnd, ovr in picks_layout:
        res = api.create_draft_pick(
            {
                "league_id": ctx["league"]["id"], "team_id": team["id"],
                "player_id": player["id"], "round": rnd,
                "overall_pick": ovr, "cost_cents": 0,
            },
            commissioner_headers,
        )
        dp = validate_success(res, expected_status=201)
        pick_ids[player["id"]] = dp["id"]
    finalize_draft(ctx["league"]["id"])
    ta_v = validate_success(
        api.get_team(ctx["ta"]["id"], commissioner_headers),
        expected_status=200,
    )["version"]
    validate_success(
        api.update_keepers(
            ctx["ta"]["id"], [pa1["id"], pa2["id"]], ta_v,
            make_team_owner_headers(ctx["ta"]["id"]),
        ),
        expected_status=200,
    )
    dp_pa1 = validate_success(
        api.get_draft_pick(pick_ids[pa1["id"]], commissioner_headers),
        expected_status=200,
    )
    dp_pa2 = validate_success(
        api.get_draft_pick(pick_ids[pa2["id"]], commissioner_headers),
        expected_status=200,
    )
    assert dp_pa1["keeper_round"] == 3
    assert dp_pa2["keeper_round"] == 4


def test_keeper_cost_floors_at_keeper_floor_round_one(api, commissioner_headers):
    """PRD §3.9: "Every cost is floored at 1, so a player whose prior round
    was 3 and who is the team's fifth keeper still costs round 1, not round
    -2. The floor constant is the keeper-floor round, value 1, applied via
    the `max` operation against the subtracted figure."

    Player px drafted round 2, created first chronologically; py drafted
    round 1, created second. Costs: px → max(1, 2-0)=2; py → max(1, 1-1)
    = max(1, 0) = 1, floored at 1.

    Design: Corner/calculations/keeper_cost_floors_at_round_one
    """
    set_clock("2026-10-02T00:00:00Z")
    ctx = _two_team_keeper_league(keeper_limit=2, roster_size=2)
    px = create_player("Px", "QB", "KC", projected_points=5.0, replacement_value=2.0)
    py = create_player("Py", "RB", "KC", projected_points=5.0, replacement_value=2.0)
    pb1 = create_player("Pb1", "QB", "BUF", projected_points=5.0, replacement_value=2.0)
    pb2 = create_player("Pb2", "RB", "BUF", projected_points=5.0, replacement_value=2.0)
    start_draft(ctx["league"]["id"])
    layout = [
        (ctx["ta"], px, 2, 1),
        (ctx["tb"], pb1, 1, 2),
        (ctx["tb"], pb2, 2, 3),
        (ctx["ta"], py, 1, 4),
    ]
    pick_ids = {}
    for team, player, rnd, ovr in layout:
        res = api.create_draft_pick(
            {
                "league_id": ctx["league"]["id"], "team_id": team["id"],
                "player_id": player["id"], "round": rnd,
                "overall_pick": ovr, "cost_cents": 0,
            },
            commissioner_headers,
        )
        dp = validate_success(res, expected_status=201)
        pick_ids[player["id"]] = dp["id"]
    finalize_draft(ctx["league"]["id"])
    ta_v = validate_success(
        api.get_team(ctx["ta"]["id"], commissioner_headers),
        expected_status=200,
    )["version"]
    validate_success(
        api.update_keepers(
            ctx["ta"]["id"], [px["id"], py["id"]], ta_v,
            make_team_owner_headers(ctx["ta"]["id"]),
        ),
        expected_status=200,
    )
    dp_x = validate_success(
        api.get_draft_pick(pick_ids[px["id"]], commissioner_headers),
        expected_status=200,
    )
    dp_y = validate_success(
        api.get_draft_pick(pick_ids[py["id"]], commissioner_headers),
        expected_status=200,
    )
    assert dp_x["keeper_round"] == 2
    assert dp_y["keeper_round"] == 1


# ─── Corner Section 3 — waiver priority resolution tiebreak ───────────────


def test_waiver_priority_resolution_tiebreak_uses_priority_then_created_at(
    api, commissioner_headers,
):
    """PRD §3.4: "claims are ordered by `bid_cents` descending first; ties
    are broken by `priority_at_submission` ascending (lower priority number
    wins); remaining ties are broken by `WaiverClaim.created_at` ascending —
    never by `WaiverClaim.id`."

    Two teams bid the same 200 cents; team A.waiver_priority=1 (created
    first), team B.waiver_priority=2 — A wins.

    Design: Corner/calculations/waiver_priority_resolution_tiebreak_uses_priority_then_created_at
    """
    set_clock("2026-10-03T00:00:00Z")
    from test_helpers import setup_in_season_league, submit_waiver_claim
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Tie L", "draft_type": "SNAKE", "roster_size": 2,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 5000, "veto_threshold": 1,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B"], divisions=["E", "E"],
    )
    # Free one roster slot on each team so a waiver win (without
    # drop_player_id) does not trip ERR_ROSTER_OVER_CAP at submission per
    # PRD §3.4 — setup_in_season_league fills the roster to roster_size.
    a, b = ctx["teams"]
    for team in (a, b):
        team_picks = sorted(
            [p for p in ctx["picks"] if p["team_id"] == team["id"]],
            key=lambda p: p["overall_pick"],
        )
        last_pick = team_picks[-1]
        team_v = validate_success(
            api.get_team(team["id"], commissioner_headers),
            expected_status=200,
        )["version"]
        validate_success(
            api.release_player(
                team["id"], last_pick["player_id"], team_v,
                make_team_owner_headers(team["id"]),
            ),
            expected_status=200,
        )
    fa = create_player("FA", "WR", "FA", projected_points=8.0, replacement_value=3.0)
    wc_a = submit_waiver_claim(
        ctx["league"]["id"], a, fa["id"], bid_cents=200, processing_week=1,
    )
    wc_b = submit_waiver_claim(
        ctx["league"]["id"], b, fa["id"], bid_cents=200, processing_week=1,
    )
    advance_week(ctx["league"]["id"])
    wc_a_final = validate_success(
        api.get_waiver_claim(wc_a["id"], commissioner_headers),
        expected_status=200,
    )
    wc_b_final = validate_success(
        api.get_waiver_claim(wc_b["id"], commissioner_headers),
        expected_status=200,
    )
    assert wc_a_final["state"] == "WON"
    assert wc_b_final["state"] == "LOST_BID"
