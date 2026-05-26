"""Action-endpoint claims from Corner Section 5 (endpoints).

Filtered-list-by-player_id is SKIPPED — PRD §4 only lists the endpoint
title and never states that the player_id filter is exposed; two
PRD-only readers could ship the endpoint without that filter and still
be PRD-faithful.
"""
from test_helpers import (
    advance_week,
    api_client,
    set_clock,
    setup_in_season_league,
    validate_success,
)


def test_advance_week_increments_league_current_week(api, commissioner_headers):
    """PRD §3.3: "When both conditions hold, the system processes every
    submitted waiver claim for the current week (described in §3.4), then
    increments the league's `current_week` by 1."

    Design: Corner/endpoints/action_endpoint_advance_week_increments_current_week
    """
    set_clock("2026-10-06T00:00:00Z")
    ctx = setup_in_season_league(team_names=["A", "B"], divisions=["E", "E"])
    assert ctx["league"]["current_week"] == 1
    after = advance_week(ctx["league"]["id"])
    assert after["current_week"] == 2
