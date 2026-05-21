"""Snake draft, tier-A cap, draft preconditions.

PRD §3.3 drives this file.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_player_to_evaluated,
    advance_to_regular_season,
    create_coach,
    create_guardian,
    create_player,
    create_season,
    create_team,
    create_team_payload,
    draft_pick_payload,
    make_coach_headers,
    populate_team_rosters,
    setup_regular_season,
    setup_season_with_teams,
    validate_error,
    validate_success,
    verify_age,
)


# ===========================================================================
# Team creation — PRD §3.3
# ===========================================================================
class TestTeamCreation:
    """PRD §3.3: "A `Coach` is registered with `full_name`, `email`
    (unique across the league), and the boolean `background_check_passed`
    (default false). The background check is more than bookkeeping: a
    coach cannot be assigned as head coach of any team unless their
    `background_check_passed` is true at the moment of team creation or
    head-coach reassignment, and any attempt with a coach lacking it is
    rejected with `ERR_COACH_NO_BACKGROUND_CHECK`."
    """

    def test_create_team_with_unchecked_coach_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.3: "a coach cannot be assigned as head coach of any
        team unless their `background_check_passed` is true at the
        moment of team creation or head-coach reassignment, and any
        attempt with a coach lacking it is rejected with
        `ERR_COACH_NO_BACKGROUND_CHECK`."

        Claim: create-team with a coach whose background_check_passed
        is False -> ERR_COACH_NO_BACKGROUND_CHECK.
        """
        season = create_season()
        coach = create_coach(background_check_passed=False)
        payload = create_team_payload(
            season_id=season["id"],
            head_coach_id=coach["id"],
            draft_position=1,
        )
        resp = api.create_team(payload, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_COACH_NO_BACKGROUND_CHECK.value)

    def test_duplicate_draft_position_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.3: "Duplicate names or duplicate draft positions in
        the same season surface as `ERR_TEAM_DUPLICATE`."

        Claim: two teams with same draft_position -> ERR_TEAM_DUPLICATE.
        """
        season = create_season()
        coach1 = create_coach(background_check_passed=True)
        coach2 = create_coach(background_check_passed=True)
        create_team(
            season_id=season["id"],
            head_coach_id=coach1["id"],
            draft_position=1,
        )
        payload = create_team_payload(
            season_id=season["id"],
            head_coach_id=coach2["id"],
            draft_position=1,
        )
        resp = api.create_team(payload, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_TEAM_DUPLICATE.value)

    def test_duplicate_team_name_rejected(self, api, league_admin_headers):
        """PRD §3.3: "Duplicate names or duplicate draft positions in
        the same season surface as `ERR_TEAM_DUPLICATE`."

        Claim: two teams with same name in same season ->
        ERR_TEAM_DUPLICATE.
        """
        season = create_season()
        coach1 = create_coach(background_check_passed=True)
        coach2 = create_coach(background_check_passed=True)
        create_team(
            season_id=season["id"],
            head_coach_id=coach1["id"],
            draft_position=1,
            name="Red Sox",
        )
        payload = create_team_payload(
            season_id=season["id"],
            head_coach_id=coach2["id"],
            draft_position=2,
            name="Red Sox",
        )
        resp = api.create_team(payload, league_admin_headers)
        validate_error(resp, ApiErrorId.ERR_TEAM_DUPLICATE.value)


# ===========================================================================
# Snake draft — PRD §3.3
# ===========================================================================
class TestSnakeDraftSeat:
    """PRD §3.3: "When the round index is even (so round 1, round 3,
    and so on), the current seat is the seat index plus one, ascending
    from 1 to N; when the round index is odd, the current seat is N
    minus the seat index, descending from N back down to 1. A draft
    attempt by a coach whose team's `draft_position` does not equal the
    resolved current seat is rejected with `ERR_NOT_TEAMS_TURN`."
    """

    def test_first_pick_must_go_to_position_1(self, api):
        """PRD §3.3: "A draft attempt by a coach whose team's
        `draft_position` does not equal the resolved current seat is
        rejected with `ERR_NOT_TEAMS_TURN`."

        Claim: with picks_so_far=0, position 2 cannot draft;
        ERR_NOT_TEAMS_TURN.
        """
        season, teams, coaches = setup_season_with_teams(n_teams=4)
        guardian = create_guardian()
        player = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=70.0,
        )
        # Coach 2 (position 2) attempts the first pick.
        resp = api.draft_pick(
            teams[1]["id"],
            draft_pick_payload(player_id=player["id"]),
            make_coach_headers(coaches[1]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_TEAMS_TURN.value)

    def test_snake_reverses_after_round_one(self, api):
        """PRD §3.3: "When the round index is even (so round 1, round 3,
        and so on), the current seat is the seat index plus one,
        ascending from 1 to N; when the round index is odd, the current
        seat is N minus the seat index, descending from N back down to
        1."

        Claim: with 4 teams and picks_so_far=4 (round 2, seat_in_round=0),
        the snake reverses so position 4 must pick first.
        """
        season, teams, coaches = setup_season_with_teams(n_teams=4)
        guardian = create_guardian()
        # Pre-draft round-1 (4 picks). populate_team_rosters walks the
        # snake correctly, so after 1 player per team round 1 is done.
        populate_team_rosters(
            season=season, teams=teams, coaches=coaches,
            players_per_team=1, guardian=guardian,
        )
        # Now the next picker should be the team at position 4 (snake
        # reverses).
        next_player = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=70.0,
        )
        # Coach at position 1 tries — should reject (not their turn).
        team_at_pos_1 = next(t for t in teams if t["draft_position"] == 1)
        coach_at_pos_1 = next(
            c for c, t in zip(coaches, teams) if t["draft_position"] == 1
        )
        resp = api.draft_pick(
            team_at_pos_1["id"],
            draft_pick_payload(player_id=next_player["id"]),
            make_coach_headers(coach_at_pos_1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_TEAMS_TURN.value)

        # Coach at position 4 picks — should succeed.
        team_at_pos_4 = next(t for t in teams if t["draft_position"] == 4)
        coach_at_pos_4 = next(
            c for c, t in zip(coaches, teams) if t["draft_position"] == 4
        )
        resp = api.draft_pick(
            team_at_pos_4["id"],
            draft_pick_payload(player_id=next_player["id"]),
            make_coach_headers(coach_at_pos_4["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "DRAFTED"
        assert data["team_id"] == team_at_pos_4["id"]


# ===========================================================================
# Tier-A cap — PRD §3.3
# ===========================================================================
class TestTierACap:
    """PRD §3.3: "The roster also enforces a cap of at most 3 `TIER_A`
    players per team: if the team's current `tier_a_count` is already 3
    or more and the picked player's `evaluation_tier` is `TIER_A`, the
    pick is rejected with `ERR_TIER_A_CAP_EXCEEDED`."
    """

    def test_tier_a_cap_blocks_fourth_tier_a(self, api):
        """PRD §3.3: "if the team's current `tier_a_count` is already 3
        or more and the picked player's `evaluation_tier` is `TIER_A`,
        the pick is rejected with `ERR_TIER_A_CAP_EXCEEDED`."

        Claim: a team holds 3 TIER_A players (score=85.0); the next
        attempt to draft a TIER_A player onto the same team rejects
        with ERR_TIER_A_CAP_EXCEEDED.
        """
        # Build a 4-team season with picks engineered so team-1 gets
        # exactly 3 TIER_A picks.
        season, teams, coaches = setup_season_with_teams(n_teams=4)
        guardian = create_guardian()
        # Round 1 picks go in seats 1,2,3,4 then round 2 reverses 4,3,2,1
        # then round 3 goes 1,2,3,4 again, then round 4 reverses, etc.
        # Team at position 1 picks at indices 0, 7, 8, 15, 16 ...
        # We need 3 TIER_A picks for team at position 1 with score 85+
        # at indices 0, 7, 8 and a fourth TIER_A pick attempt next.

        # Use score=85.0 for picks at 0, 7, 8 to put 3 TIER_A on team 1.
        # Pad other picks with TIER_B (score 70). After 9 picks
        # (rounds 1+2+ first of round3), the next snake-pick is at
        # seat_index_in_round_3=1, which goes to position 2 in round 3
        # (ascending). To make team 1 attempt another TIER_A pick we
        # need picks_so_far at a multiple where seat resolves to 1.
        # Simpler approach: only use 1 team at full position and put
        # 3 TIER_A picks via repeated round trips. populate_team_rosters
        # can do this with a per-pick score list.
        scores_per_pick: list = [None] * 16
        # Picks for position 1: round 1 pick #1 (index 0), round 2 pick
        # last (index 7), round 3 pick #1 (index 8). Make all three
        # TIER_A (=85), and the rest TIER_B (=70).
        for i in range(16):
            scores_per_pick[i] = 70.0
        scores_per_pick[0] = 85.0
        scores_per_pick[7] = 85.0
        scores_per_pick[8] = 85.0
        populate_team_rosters(
            season=season, teams=teams, coaches=coaches,
            players_per_team=4,  # 4 teams * 4 picks = 16 picks
            guardian=guardian,
            evaluation_score_by_pick=scores_per_pick,
        )
        # Now: position 1's tier_a_count == 3. We need a *next* pick
        # attempt onto team-1 with a TIER_A player. Find the team and
        # coach at position 1.
        team_at_pos_1 = next(t for t in teams if t["draft_position"] == 1)
        coach_at_pos_1 = next(
            c for c, t in zip(coaches, teams) if t["draft_position"] == 1
        )
        # Create another TIER_A candidate.
        candidate = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=90.0,
        )
        # After 16 picks (rounds 1..4 of a 4-team draft), picks_so_far
        # is 16. round_index = 16//4 = 4 (even), seat_in_round = 0,
        # current_seat = 1 — team at position 1's turn. The pick onto
        # team 1 will trigger the tier-A cap.
        resp = api.draft_pick(
            team_at_pos_1["id"],
            draft_pick_payload(player_id=candidate["id"]),
            make_coach_headers(coach_at_pos_1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TIER_A_CAP_EXCEEDED.value)


# ===========================================================================
# Ownership / RBAC on draft-pick — PRD §3.3
# ===========================================================================
class TestDraftOwnership:
    """PRD §3.3: "the acting coach to match the team's `head_coach_id`
    (otherwise `ERR_NOT_TEAM_OWNER`)".
    """

    def test_coach_cannot_draft_for_other_team(self, api):
        """PRD §3.3: "the acting coach to match the team's
        `head_coach_id` (otherwise `ERR_NOT_TEAM_OWNER`)".

        Claim: Coach C2 attempting draft-pick on Team T1 -> ERR_NOT_TEAM_OWNER.
        """
        season, teams, coaches = setup_season_with_teams(n_teams=4)
        guardian = create_guardian()
        player = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=70.0,
        )
        team_at_pos_1 = next(t for t in teams if t["draft_position"] == 1)
        wrong_coach = next(
            c for c, t in zip(coaches, teams) if t["draft_position"] != 1
        )
        # The wrong_coach has the right headers but is not the head
        # coach of team_at_pos_1 — expect ERR_NOT_TEAM_OWNER.
        resp = api.draft_pick(
            team_at_pos_1["id"],
            draft_pick_payload(player_id=player["id"]),
            make_coach_headers(wrong_coach["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_TEAM_OWNER.value)
