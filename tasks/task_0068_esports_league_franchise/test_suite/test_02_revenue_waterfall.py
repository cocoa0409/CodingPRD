"""Sponsorship distribution and the revenue-share waterfall (POST /sponsorships/{id}/distribute).

Covers difficulty queue: dual_variant_calc (league-first cut), combinatorial_formula
(floor-then-remainder rounding order); and corner queue waterfall input-set cases.
"""
from test_helpers import (
    validate_success,
    setup_three_team_sponsorship, setup_single_team_sponsorship,
    distribute_sponsorship,
    TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def _shares_by_team(api, season_id, teams):
    """Fetch each team's revenue-share amount_cents."""
    out = {}
    for t in teams:
        res = api.get_team_revenue_shares(t["id"], COMMISH)
        data = validate_success(res, 200)
        out[t["id"]] = data[0]["amount_cents"]
    return out


def test_waterfall_takes_league_cut_first_off_gross_pool(api):
    """PRD §3.9: "The waterfall takes the league cut first, off the gross pool. The
    league cut is pool_cents multiplied by league_share_pct, rounded half up to whole
    cents. The distributable amount is the pool minus that league cut; the team
    waterfall divides only this post-cut distributable, never the gross pool."

    Pool 10,000,000 with 40% league cut → distributable 6,000,000; highest-weight
    team A (weight 3 of total 7) gets floor(6000000*3/7)=2571428 +1 remainder = 2571429.

    Design: Difficulty/dual_variant_calc/revenue_waterfall_league_first_vs_split_then_deduct
    """
    season, teams, spo = setup_three_team_sponsorship()
    validate_success(distribute_sponsorship(spo), 200)
    shares = _shares_by_team(api, season["id"], teams)
    a, b, c = teams[0]["id"], teams[1]["id"], teams[2]["id"]
    assert shares[a] == 2_571_429
    assert shares[b] == 2_571_429
    assert shares[c] == 857_142
    assert shares[a] + shares[b] + shares[c] == 6_000_000


def test_waterfall_floor_then_remainder_award_order(api):
    """PRD §3.9: "each team is provisionally awarded the floor of its raw share. The
    leftover — the distributable minus the sum of the floored shares — is then
    distributed one cent at a time, walking the teams in order of market_size_weight
    descending, breaking ties by created_at ascending, and cycling through that order
    until the remainder is exhausted. The result is that the awarded shares sum exactly
    to the distributable amount."

    Floors: A,B = 2,571,428; C = 857,142; sum 5,999,998; remainder 2 awarded to A then B.

    Design: Difficulty/combinatorial_formula/revenue_waterfall_floor_then_remainder_rounding_order_mode_b
    """
    season, teams, spo = setup_three_team_sponsorship()
    validate_success(distribute_sponsorship(spo), 200)
    shares = _shares_by_team(api, season["id"], teams)
    a, b, c = teams[0]["id"], teams[1]["id"], teams[2]["id"]
    assert shares[a] == 2_571_429
    assert shares[b] == 2_571_429
    assert shares[c] == 857_142


def test_waterfall_lowest_weight_team_gets_no_remainder_cent(api):
    """PRD §3.9: "each team is provisionally awarded the floor of its raw share. The
    leftover — the distributable minus the sum of the floored shares — is then
    distributed one cent at a time, walking the teams in order of market_size_weight
    descending, breaking ties by created_at ascending, and cycling through that order
    until the remainder is exhausted."

    The 2-cent remainder is consumed by A and B (weight 3) before C (weight 1) is
    reached, so C stays at its floor 857,142.

    Design: Difficulty/combinatorial_formula/revenue_waterfall_floor_then_remainder_rounding_order_mode_b
    """
    season, teams, spo = setup_three_team_sponsorship()
    validate_success(distribute_sponsorship(spo), 200)
    shares = _shares_by_team(api, season["id"], teams)
    c = teams[2]["id"]
    assert shares[c] == 857_142


def test_waterfall_remainder_sums_exactly_to_distributable(api):
    """PRD §3.9: "The result is that the awarded shares sum exactly to the distributable
    amount."

    Design: Difficulty/dual_variant_calc/revenue_waterfall_league_first_vs_split_then_deduct
    """
    season, teams, spo = setup_three_team_sponsorship()
    validate_success(distribute_sponsorship(spo), 200)
    shares = _shares_by_team(api, season["id"], teams)
    assert sum(shares.values()) == 6_000_000


def test_single_team_receives_full_distributable_with_weight_snapshot(api):
    """PRD §3.9: "Distributing the pool ... creates one revenue-share record per team
    in the season." PRD §3.9: "Each created revenue share records the sponsorship_id it
    was carved from, the team_id receiving it, the amount_cents allocated to that team
    by the waterfall, and the weight_used — the team's market_size_weight snapshotted
    at distribution time for audit."

    Design: Corner/calculations/revenue_waterfall_excludes_no_team_and_includes_all
    """
    season, team, spo = setup_single_team_sponsorship(weight=5)
    validate_success(distribute_sponsorship(spo), 200)
    res = api.get_team_revenue_shares(team["id"], COMMISH)
    data = validate_success(res, 200)
    assert data[0]["amount_cents"] == 6_000_000
    assert data[0]["weight_used"] == 5
