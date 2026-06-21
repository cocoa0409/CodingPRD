"""State machines: Trade branching, Player cyclic, terminal-state lockdown,
and pre-draft state rejection.

Translates Difficulty rule `non_linear_state_machine` (both instances) and
Corner Section 2 (state_machines) non-stub entries.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
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
    validate_error,
    validate_success,
)


# ─── Difficulty rule 3 instance A — Trade branch revert (PROPOSED→REJECTED) ─


def test_trade_proposed_to_rejected_marks_terminal(api, commissioner_headers):
    """PRD §3.8: "The target team's owner may reject it, moving it to the
    terminal `REJECTED`."

    Design: Difficulty/non_linear_state_machine/trade_branch_revert_proposed_rejected_terminal
    """
    set_clock("2026-10-15T00:00:00Z")
    ctx = setup_in_season_league(team_names=["TA", "TB"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pa = ctx["picks"][0]
    pc = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    trade = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
    )
    res = api.reject_trade(trade["id"], trade["version"], make_team_owner_headers(tb["id"]))
    rejected = validate_success(res, expected_status=200)
    assert rejected["state"] == "REJECTED"


def test_trade_rejected_leaves_player_current_team_unchanged(api, commissioner_headers):
    """PRD §3.8: "The target team's owner may reject it, moving it to the
    terminal `REJECTED`."

    REJECT has no roster swap; players_offered remain with the proposer.

    Design: Difficulty/non_linear_state_machine/trade_branch_revert_proposed_rejected_terminal
    """
    set_clock("2026-10-15T00:00:00Z")
    ctx = setup_in_season_league(team_names=["TA", "TB"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    pa = ctx["picks"][0]  # First pick belongs to team A (alpha).
    pc = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    trade = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[pa["player_id"]],
        players_requested=[pc["player_id"]],
    )
    validate_success(
        api.reject_trade(trade["id"], trade["version"], make_team_owner_headers(tb["id"])),
        expected_status=200,
    )
    pa_after = validate_success(
        api.get_player(pa["player_id"], commissioner_headers),
        expected_status=200,
    )
    assert pa_after["current_team_id"] == ta["id"]


# ─── Difficulty rule 3 instance B — Player cyclic ACTIVE→INJURED→IR→ACTIVE ─


def _solo_team_with_one_player(ir_slot_count=1):
    """Set up a two-team league where the first team owns exactly one
    player (the focal "cycler") on its bench, with ir_slot_count=1 so the
    cycler can be placed on IR."""
    league = create_league(
        name="Cycle L", draft_type="SNAKE", roster_size=2, starter_slot_count=1,
        ir_slot_count=ir_slot_count, faab_budget_cents=5000, veto_threshold=1,
        keeper_limit=0, playoff_team_count=2, tiebreak_rule="STANDARD",
    )
    solo = create_team(league["id"], "Solo", "E")
    other = create_team(league["id"], "Other", "E")
    cycler = create_player("Cycler", "QB", "KC", projected_points=10.0, replacement_value=5.0)
    f1 = create_player("F1", "RB", "KC", projected_points=5.0, replacement_value=2.0)
    f2 = create_player("F2", "QB", "BUF", projected_points=5.0, replacement_value=2.0)
    f3 = create_player("F3", "RB", "BUF", projected_points=5.0, replacement_value=2.0)
    start_draft(league["id"])
    layout = [
        (solo, cycler, 1, 1),
        (other, f2, 1, 2),
        (other, f3, 2, 3),
        (solo, f1, 2, 4),
    ]
    for team, player, rnd, ovr in layout:
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
    # finalize_draft assigns current_team_id to every drafted Player, which
    # bumps Player.version. Refetch the focal cycler so callers see the
    # current version for OCC-guarded endpoints like report_injury.
    cycler = validate_success(
        api_client.get_player(cycler["id"], TEST_USERS["commissioner_headers"]),
        expected_status=200,
    )
    return {"league": league, "solo": solo, "cycler": cycler}


def test_player_cycle_active_to_injured_to_ir_placed(api, commissioner_headers):
    """PRD §3.5: "Reporting an injury moves the player from `ACTIVE` to
    `INJURED`".
    PRD §3.5: "A `TeamOwner` may place an `INJURED` player on injured
    reserve ... The transition moves the player's `status` from `INJURED`
    to `IR_PLACED`".

    Design: Difficulty/non_linear_state_machine/player_cyclic_active_injured_ir_active
    """
    set_clock("2026-10-20T00:00:00Z")
    ctx = _solo_team_with_one_player()
    cy = ctx["cycler"]
    cy_v = cy["version"]
    cy_after_inj = validate_success(
        api.report_injury(cy["id"], cy_v, commissioner_headers),
        expected_status=200,
    )
    assert cy_after_inj["status"] == "INJURED"
    solo_v = validate_success(
        api.get_team(ctx["solo"]["id"], commissioner_headers), expected_status=200,
    )["version"]
    cy_after_ir = validate_success(
        api.place_on_ir(
            ctx["solo"]["id"], cy["id"], solo_v,
            make_team_owner_headers(ctx["solo"]["id"]),
        ),
        expected_status=200,
    )
    assert cy_after_ir["status"] == "IR_PLACED"


def test_player_cycle_ir_placed_back_to_active(api, commissioner_headers):
    """PRD §3.5: "The reverse move — activating from IR — is also
    team-owner-driven, takes the same `player_id` and `expected_team_version`,
    and moves the player from `IR_PLACED` back to `ACTIVE` with the slot
    returning to `BENCH`."

    Design: Difficulty/non_linear_state_machine/player_cyclic_active_injured_ir_active
    """
    set_clock("2026-10-20T00:00:00Z")
    ctx = _solo_team_with_one_player()
    cy = ctx["cycler"]
    validate_success(
        api.report_injury(cy["id"], cy["version"], commissioner_headers),
        expected_status=200,
    )
    solo_v1 = validate_success(
        api.get_team(ctx["solo"]["id"], commissioner_headers), expected_status=200,
    )["version"]
    validate_success(
        api.place_on_ir(
            ctx["solo"]["id"], cy["id"], solo_v1,
            make_team_owner_headers(ctx["solo"]["id"]),
        ),
        expected_status=200,
    )
    solo_v2 = validate_success(
        api.get_team(ctx["solo"]["id"], commissioner_headers), expected_status=200,
    )["version"]
    cy_after = validate_success(
        api.activate_from_ir(
            ctx["solo"]["id"], cy["id"], solo_v2,
            make_team_owner_headers(ctx["solo"]["id"]),
        ),
        expected_status=200,
    )
    assert cy_after["status"] == "ACTIVE"


# ─── Corner Section 2 — terminal-state lockdown ────────────────────────────


def test_trade_accept_from_rejected_terminal_returns_invalid_state(
    api, commissioner_headers,
):
    """PRD §3.8: "The target team's owner may reject it, moving it to the
    terminal `REJECTED`."
    PRD §2.7: "the target entity's own state machine precondition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/trade_invalid_from_terminal_returns_invalid_state
    """
    set_clock("2026-10-01T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    ta, tb = ctx["teams"]
    p_a = next(p for p in ctx["picks"] if p["team_id"] == ta["id"])
    p_b = next(p for p in ctx["picks"] if p["team_id"] == tb["id"])
    trade = propose_trade(
        ctx["league"]["id"], ta, tb,
        players_offered=[p_a["player_id"]],
        players_requested=[p_b["player_id"]],
    )
    rejected = validate_success(
        api.reject_trade(trade["id"], trade["version"], make_team_owner_headers(tb["id"])),
        expected_status=200,
    )
    # Now try to accept the terminal trade.
    res = api.accept_trade(
        rejected["id"], rejected["version"],
        make_team_owner_headers(tb["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner Section 2 — pre-condition: draft picks require DRAFTING ────────


def test_draft_pick_during_setup_rejected(api, commissioner_headers):
    """PRD §3.2: "During `DRAFTING`, picks arrive through a single endpoint".
    PRD §3.1: "On creation, the league's `status` is `SETUP`".
    PRD §2.7: "the target entity's own state machine precondition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/draft_pick_when_league_in_setup_rejected
    """
    set_clock("2026-08-01T00:00:00Z")
    league = create_league(name="Setup L", draft_type="SNAKE")
    team = create_team(league["id"], "A", "E")
    player = create_player("P1", "QB", "KC", projected_points=10.0, replacement_value=5.0)
    res = api.create_draft_pick(
        {
            "league_id": league["id"], "team_id": team["id"],
            "player_id": player["id"], "round": 1,
            "overall_pick": 1, "cost_cents": 0,
        },
        commissioner_headers,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
