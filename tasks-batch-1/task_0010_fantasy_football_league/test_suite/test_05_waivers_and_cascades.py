"""Waiver-claim resolution, depth-3 cascade chain, and the cross-entity
state dependency from Player.status to WaiverClaim transitions.

Translates Difficulty rule `transitive_cascade` (instance A — waiver →
faab → invalidation), `cross_entity_state_dependency` (instance B — waiver
LOST_BID vs WON depending on competing claims and player status), and
Difficulty rule 8 instance B (waiver week interval).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_week,
    api_client,
    create_player,
    make_team_owner_headers,
    set_clock,
    setup_in_season_league,
    submit_waiver_claim,
    validate_error,
    validate_success,
)


# ─── Difficulty rule 4 instance A — depth-3 waiver cascade ─────────────────


def _release_one_player_each_team(ctx):
    """Drop the most-recent drafted player from each team to free one
    non-IR roster slot per team. setup_in_season_league fills every team
    to roster_size, so a waiver win without `drop_player_id` would
    otherwise hit ERR_ROSTER_OVER_CAP at submission per PRD §3.4 ("the
    team's non-IR roster slot count must still not exceed `roster_size`").
    """
    for team in ctx["teams"]:
        team_picks = [p for p in ctx["picks"] if p["team_id"] == team["id"]]
        # Release the most recent pick (highest overall_pick) for that team.
        team_picks.sort(key=lambda p: p["overall_pick"])
        last_pick = team_picks[-1]
        team_v = validate_success(
            api_client.get_team(team["id"], TEST_USERS["commissioner_headers"]),
            expected_status=200,
        )["version"]
        validate_success(
            api_client.release_player(
                team["id"], last_pick["player_id"], team_v,
                make_team_owner_headers(team["id"]),
            ),
            expected_status=200,
        )


def _league_with_two_fa_targets(roster_size=4):
    """Stand up an IN_SEASON two-team league with `roster_size`=4 and TWO
    additional free-agent players in the global pool. Each team releases
    its last-drafted player to leave one open roster slot, so a single
    waiver win (without `drop_player_id`) can be applied without tripping
    ERR_ROSTER_OVER_CAP at submission time."""
    ctx = setup_in_season_league(
        league_overrides={
            "name": "Casc L", "draft_type": "SNAKE", "roster_size": roster_size,
            "starter_slot_count": 1, "ir_slot_count": 0,
            "faab_budget_cents": 10000, "veto_threshold": 1,
            "keeper_limit": 0, "playoff_team_count": 2,
            "tiebreak_rule": "STANDARD",
        },
        team_names=["A", "B"], divisions=["E", "E"],
    )
    _release_one_player_each_team(ctx)
    fa_x = create_player("FAx", "WR", "FA", projected_points=7.0, replacement_value=2.0)
    fa_y = create_player("FAy", "TE", "FA", projected_points=6.0, replacement_value=2.0)
    return {**ctx, "fa_x": fa_x, "fa_y": fa_y}


def test_waiver_win_debits_faab_to_zero(api, commissioner_headers):
    """PRD §3.4: "each commit debits the winning team's `faab_balance_cents`
    by `bid_cents`".

    Team A bids the full 10000 cents on player_x; after advance-week, team
    A's FAAB is zero (10000 - 10000 = 0).

    Design: Difficulty/transitive_cascade/waiver_won_drains_faab_invalidates_pending_claims_depth3
    """
    set_clock("2026-11-01T00:00:00Z")
    ctx = _league_with_two_fa_targets()
    ta = ctx["teams"][0]
    submit_waiver_claim(
        ctx["league"]["id"], ta, ctx["fa_x"]["id"], bid_cents=10000, processing_week=1,
    )
    advance_week(ctx["league"]["id"])
    ta_after = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )
    assert ta_after["faab_balance_cents"] == 0


def test_waiver_win_then_zero_faab_invalidates_same_team_pending_claim(
    api, commissioner_headers,
):
    """PRD §3.4: "if a team's `faab_balance_cents` reaches 0 mid-batch,
    every still-pending `SUBMITTED` claim for that same team within the
    same `processing_week` is auto-marked `INVALID` before the third pass —
    this is a cascade-depth-3 chain (group winner selection → winner commit
    → same-team invalidation)".

    Design: Difficulty/transitive_cascade/waiver_won_drains_faab_invalidates_pending_claims_depth3
    """
    set_clock("2026-11-01T00:00:00Z")
    ctx = _league_with_two_fa_targets()
    ta = ctx["teams"][0]
    wc_x = submit_waiver_claim(
        ctx["league"]["id"], ta, ctx["fa_x"]["id"], bid_cents=10000, processing_week=1,
    )
    wc_y = submit_waiver_claim(
        ctx["league"]["id"], ta, ctx["fa_y"]["id"], bid_cents=100, processing_week=1,
    )
    advance_week(ctx["league"]["id"])
    wc_x_final = validate_success(
        api.get_waiver_claim(wc_x["id"], commissioner_headers), expected_status=200,
    )
    wc_y_final = validate_success(
        api.get_waiver_claim(wc_y["id"], commissioner_headers), expected_status=200,
    )
    assert wc_x_final["state"] == "WON"
    assert wc_y_final["state"] == "INVALID"


# ─── Difficulty rule 7 instance B — competing bid → LOST_BID for lower bid ─


def test_waiver_loses_bid_when_outbid_by_higher_team(api, commissioner_headers):
    """PRD §3.4: "claims are ordered by `bid_cents` descending first; ties
    are broken by `priority_at_submission` ascending (lower priority number
    wins); remaining ties are broken by `WaiverClaim.created_at` ascending".
    PRD §3.4: "The third pass marks every remaining same-player loser as
    `LOST_BID` with no FAAB debit, conserving the league's
    `total_faab_pool_cents`."

    Team A bids 100; team B bids 500 on the same FA — B wins, A's claim
    is LOST_BID.

    Design: Difficulty/cross_entity_state_dependency/waiver_won_requires_player_not_released
    """
    set_clock("2026-11-25T00:00:00Z")
    ctx = _league_with_two_fa_targets()
    ta, tb = ctx["teams"]
    wc_a = submit_waiver_claim(
        ctx["league"]["id"], ta, ctx["fa_x"]["id"], bid_cents=100, processing_week=1,
    )
    wc_b = submit_waiver_claim(
        ctx["league"]["id"], tb, ctx["fa_x"]["id"], bid_cents=500, processing_week=1,
    )
    advance_week(ctx["league"]["id"])
    a_final = validate_success(
        api.get_waiver_claim(wc_a["id"], commissioner_headers), expected_status=200,
    )
    b_final = validate_success(
        api.get_waiver_claim(wc_b["id"], commissioner_headers), expected_status=200,
    )
    assert a_final["state"] == "LOST_BID"
    assert b_final["state"] == "WON"


def test_waiver_lost_bid_does_not_debit_faab(api, commissioner_headers):
    """PRD §3.4: "The third pass marks every remaining same-player loser as
    `LOST_BID` with no FAAB debit, conserving the league's
    `total_faab_pool_cents`."

    Design: Difficulty/cross_entity_state_dependency/waiver_won_requires_player_not_released
    """
    set_clock("2026-11-25T00:00:00Z")
    ctx = _league_with_two_fa_targets()
    ta, tb = ctx["teams"]
    starting_faab_a = ta["faab_balance_cents"]
    submit_waiver_claim(
        ctx["league"]["id"], ta, ctx["fa_x"]["id"], bid_cents=100, processing_week=1,
    )
    submit_waiver_claim(
        ctx["league"]["id"], tb, ctx["fa_x"]["id"], bid_cents=500, processing_week=1,
    )
    advance_week(ctx["league"]["id"])
    ta_after = validate_success(
        api.get_team(ta["id"], commissioner_headers), expected_status=200,
    )
    assert ta_after["faab_balance_cents"] == starting_faab_a


# ─── Difficulty rule 8 instance B — wrong processing_week ──────────────────


def test_waiver_claim_with_future_processing_week_rejected(api, commissioner_headers):
    """PRD §3.4: "the `processing_week` value, which the claimant copies
    from the league's current week — claims for past weeks and for future
    weeks are equally invalid and rejected with `ERR_INVALID_WAIVER_WEEK`."

    Design: Difficulty/resource_temporal_overlap/waiver_claim_in_wrong_processing_week
    """
    set_clock("2026-11-27T00:00:00Z")
    ctx = _league_with_two_fa_targets()
    ta = ctx["teams"][0]
    from test_helpers import make_team_owner_headers
    res = api.create_waiver_claim(
        {
            "league_id": ctx["league"]["id"], "team_id": ta["id"],
            "player_id": ctx["fa_x"]["id"], "bid_cents": 100,
            "processing_week": 2,  # league is in week 1.
        },
        make_team_owner_headers(ta["id"]),
    )
    validate_error(res, "ERR_INVALID_WAIVER_WEEK", expected_status=422)


def test_waiver_claim_with_matching_processing_week_accepted(api, commissioner_headers):
    """PRD §3.4: "the `processing_week` value, which the claimant copies
    from the league's current week".

    Submitting with processing_week == current_week is accepted (sanity
    counter-check for the negative test above).

    Design: Difficulty/resource_temporal_overlap/waiver_claim_in_wrong_processing_week
    """
    set_clock("2026-11-27T00:00:00Z")
    ctx = _league_with_two_fa_targets()
    ta = ctx["teams"][0]
    wc = submit_waiver_claim(
        ctx["league"]["id"], ta, ctx["fa_x"]["id"],
        bid_cents=100, processing_week=1,
    )
    assert wc["state"] == "SUBMITTED"
