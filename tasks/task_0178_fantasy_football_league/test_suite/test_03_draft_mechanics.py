"""Draft mechanics: SNAKE turn order, AUCTION budget guard, player
uniqueness, position eligibility.

Covers PRD §3.3 (draft picks: turn order, unique (league_id, player_id),
auction budget floor, position eligibility).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_draft_pick,
    create_draft_pick_payload,
    create_league_with_teams,
    create_player,
    create_team_payload,
    make_manager_headers,
    manager_uid,
    seed_player_catalog,
    validate_error,
    validate_success,
)


def _start_draft(api, commissioner_headers, league):
    res = api.start_draft(league["id"], commissioner_headers)
    return validate_success(res, 200)


# ===========================================================================
# SNAKE turn order — PRD §3.3
# ===========================================================================
class TestSnakeTurnOrder:
    def test_non_next_team_pick_rejected_with_not_your_turn(
        self, api, commissioner_headers,
    ):
        """PRD §3.3: "For SNAKE leagues, the system enforces strict turn order: only the team whose pick is next in the snake sequence may submit a pick, and any attempt by a non-next team is rejected with ERR_NOT_YOUR_TURN".

        Claim: in SNAKE mode, the team that is NOT next-up cannot
        create a draft pick — receives ERR_NOT_YOUR_TURN.
        """
        league, teams = create_league_with_teams(team_count=4, draft_mode="SNAKE")
        _start_draft(api, commissioner_headers, league)
        # Determine which team has draft_position 1 (first overall pick).
        positions = {}
        for t in teams:
            t_after = validate_success(
                api.get_team(league["id"], t["id"], commissioner_headers), 200,
            )
            positions[t_after["draft_position"]] = t_after
        first_team = positions[1]
        # Use a team that is NOT the first-up — draft_position 2 or 3.
        non_first = positions.get(2) or positions.get(3)
        assert non_first is not None and non_first["id"] != first_team["id"]
        player = create_player(position="RB")
        payload = create_draft_pick_payload(
            team_id=non_first["id"], player_id=player["id"],
        )
        headers = make_manager_headers(non_first["manager_user_id"])
        res = api.create_draft_pick(league["id"], payload, headers)
        validate_error(res, ApiErrorId.ERR_NOT_YOUR_TURN.value)


# ===========================================================================
# Player uniqueness — PRD §3.3
# ===========================================================================
class TestPlayerUniqueness:
    def test_drafting_same_player_twice_rejected(
        self, api, commissioner_headers,
    ):
        """PRD §3.3: "Two managers racing to draft the same player_id are serialized by a first-writer-wins guarantee on the league-scoped unique (league_id, player_id) constraint over DraftPick; the loser receives ERR_PLAYER_ALREADY_DRAFTED."

        Claim: a second DraftPick for the same (league_id, player_id)
        in AUCTION mode (no turn order in the way) yields
        ERR_PLAYER_ALREADY_DRAFTED.
        """
        league, teams = create_league_with_teams(
            team_count=4, draft_mode="AUCTION", auction_budget_dollars=200,
        )
        _start_draft(api, commissioner_headers, league)
        player = create_player(position="RB")
        # Team 0 successfully drafts player at $1.
        t0 = teams[0]
        h0 = make_manager_headers(t0["manager_user_id"])
        first = api.create_draft_pick(
            league["id"],
            create_draft_pick_payload(team_id=t0["id"], player_id=player["id"], price_dollars=1),
            h0,
        )
        validate_success(first, 201)
        # Team 1 tries to draft the same player.
        t1 = teams[1]
        h1 = make_manager_headers(t1["manager_user_id"])
        second = api.create_draft_pick(
            league["id"],
            create_draft_pick_payload(team_id=t1["id"], player_id=player["id"], price_dollars=1),
            h1,
        )
        validate_error(second, ApiErrorId.ERR_PLAYER_ALREADY_DRAFTED.value)


# ===========================================================================
# AUCTION budget — PRD §3.3
# ===========================================================================
class TestAuctionBudgetFloor:
    def test_auction_pick_exceeding_remaining_budget_floor_rejected(
        self, api, commissioner_headers,
    ):
        """PRD §3.3: "the auction budget floor: for AUCTION picks, the submitted price_dollars may not exceed the team's auction_balance_dollars minus one dollar per remaining required pick (so the team always retains at least 1 dollar per remaining roster slot it still owes); a violation is rejected with ERR_AUCTION_BUDGET_EXCEEDED."

        Claim: an AUCTION pick whose price would violate the "$1 per
        remaining slot" floor yields ERR_AUCTION_BUDGET_EXCEEDED.

        Setup: team_count=4, roster_size=12, ir_slots=1 ⇒ required
        picks per team = 11. Auction budget 200. The very first pick
        must leave at least $10 ($1 each for the 10 remaining picks),
        so a price of 200 would violate the floor.
        """
        league, teams = create_league_with_teams(
            team_count=4, draft_mode="AUCTION",
            auction_budget_dollars=200, roster_size=12, ir_slots=1,
        )
        _start_draft(api, commissioner_headers, league)
        # Determine first-up team (auction is open, but use any team
        # since AUCTION has no turn-order check).
        t0 = teams[0]
        h0 = make_manager_headers(t0["manager_user_id"])
        player = create_player(position="RB")
        # required picks per team = 11; first pick must leave >= $10.
        # 200 - 200 = 0 < 10 → reject.
        payload = create_draft_pick_payload(
            team_id=t0["id"], player_id=player["id"], price_dollars=200,
        )
        res = api.create_draft_pick(league["id"], payload, h0)
        validate_error(res, ApiErrorId.ERR_AUCTION_BUDGET_EXCEEDED.value)


# NOTE: PRD §3.3 names position-eligibility for "the position the team is
# drafting them into" but the create_draft_pick endpoint (PRD §4) does not
# accept a position_label — slots are written at finish-draft as BENCH.
# Whether ERR_POSITION_INELIGIBLE applies to the pick endpoint or only to
# the subsequent PATCH /teams/.../roster-slots is not uniquely derivable
# from PRD prose. Skipped under category: applies_to-scope. The roster-slot
# variant is exercised in test_04_roster_lineup.
