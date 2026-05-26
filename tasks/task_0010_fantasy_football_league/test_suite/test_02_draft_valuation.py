"""Draft valuation under SNAKE (VBD) vs AUCTION (share-of-pool) variants.

Translates Difficulty rule `dual_variant_calc` (instance A — draft-value
divergence on the same Player across two leagues).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_league,
    create_player,
    create_team,
    set_clock,
    validate_success,
)


def _league_with_one_player_and_two_teams(draft_type: str, name: str,
                                          faab_budget_cents: int = 10000) -> dict:
    """Create a league of the chosen draft_type with two teams and one
    target Player, with roster_size=2 so the top_pool (for AUCTION) is
    sized as roster_size * team_count = 4. We deliberately seed only one
    player into the pool, so when AUCTION computes the share, the player's
    projected_points is the entire pool and share = 1.0.

    Returns the league dict (teams are created server-side and the test
    queries them through the global pool when needed).
    """
    league = create_league(
        name=name, draft_type=draft_type, roster_size=2, starter_slot_count=1,
        ir_slot_count=0, faab_budget_cents=faab_budget_cents, veto_threshold=1,
        keeper_limit=1, playoff_team_count=2, tiebreak_rule="STANDARD",
    )
    # AUCTION pool size = roster_size * team_count, so two teams are required
    # in SETUP for the pool to be non-empty.
    create_team(league["id"], "Alpha", "E")
    create_team(league["id"], "Bravo", "E")
    return league


def test_snake_draft_value_uses_projected_minus_replacement(api, commissioner_headers):
    """PRD §3.2: "The **snake** variant fires when `draft_type` equals `SNAKE`.
    It is pure value-based drafting: for each player, the value is the
    player's `projected_points` minus their `replacement_value`, rounded
    half-up to two decimal places. FAAB is not involved."

    Design: Difficulty/dual_variant_calc/draft_value_snake_vs_auction_diverge_on_same_player
    """
    set_clock("2026-08-01T00:00:00Z")
    league = _league_with_one_player_and_two_teams("SNAKE", "Snake L")
    player = create_player(
        full_name="Big Star", position="QB", nfl_team="KC",
        projected_points=22.0, replacement_value=8.0,
    )
    res = api.get_player_draft_value(player["id"], league["id"], commissioner_headers)
    data = validate_success(res, expected_status=200)
    assert data["value"] == pytest.approx(14.00, abs=0.001)
    assert data["variant"].lower() == "snake"


def test_auction_draft_value_uses_share_of_pool(api, commissioner_headers):
    """PRD §3.2: "The **auction** variant fires when `draft_type` equals
    `AUCTION`. The system first builds the top pool: all players in the
    league's universe ordered by `projected_points` descending with ties
    broken by `created_at` ascending (never by id), limited in size to
    `roster_size` multiplied by the team count. The pool's `projected_points`
    are summed into a total. Each player's share of the pool is their
    `projected_points` divided by that total, with the share treated as zero
    if the total is zero (a defensive guard against the empty-pool edge
    case). The player's value is then the league's `faab_budget_cents`
    divided by 100 (so the unit is dollars, not cents) multiplied by that
    share, rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/draft_value_snake_vs_auction_diverge_on_same_player
    """
    set_clock("2026-08-01T00:00:00Z")
    league = _league_with_one_player_and_two_teams(
        "AUCTION", "Auction L", faab_budget_cents=10000,
    )
    player = create_player(
        full_name="Big Star", position="QB", nfl_team="KC",
        projected_points=22.0, replacement_value=8.0,
    )
    # Only one player in the global pool → top_pool sum = 22.0 → share = 1.0.
    # value = (10000 / 100) * 1.0 = $100.00.
    res = api.get_player_draft_value(player["id"], league["id"], commissioner_headers)
    data = validate_success(res, expected_status=200)
    assert data["value"] == pytest.approx(100.00, abs=0.001)
    assert data["variant"].lower() == "auction"
