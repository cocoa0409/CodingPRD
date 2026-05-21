"""League / Team creation and the league lifecycle (DRAFT_PENDING →
DRAFTING → REGULAR_SEASON → PLAYOFFS → COMPLETED → ARCHIVED).

Covers PRD §3.1 (league creation fields and ranges, team creation),
§3.3 (start-draft preconditions and side effects, finish-draft),
§3.8 (archive cascade), §4 (RBAC on lifecycle endpoints).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    COMMISSIONER,
    assert_league,
    assert_team,
    create_league,
    create_league_payload,
    create_league_with_teams,
    create_team_payload,
    manager_uid,
    setup_drafted_league,
    setup_scored_regular_season,
    validate_error,
    validate_success,
)


# ===========================================================================
# League creation — PRD §3.1
# ===========================================================================
class TestLeagueCreate:
    def test_create_league_returns_league_in_draft_pending(self, api, commissioner_headers):
        """PRD §3.1: "The newly created league is born in DRAFT_PENDING with current_week set to 0 and now_ts initialized to the league's created_at instant."

        Claim: a freshly created league has status=DRAFT_PENDING and
        current_week=0.
        """
        payload = create_league_payload(team_count=4)
        res = api.create_league(payload, commissioner_headers)
        data = validate_success(res, 201)
        assert_league(data)
        assert data["status"] == "DRAFT_PENDING"
        assert data["current_week"] == 0
        assert data["now_ts"] == data["created_at"], \
            "PRD §3.1: now_ts initialized to the league's created_at instant"

    def test_create_league_persists_input_fields(self, api, commissioner_headers):
        """PRD §3.1: "the league is playing (which must be 2020 or later), a draft_mode of either SNAKE or AUCTION, a scoring_mode of STANDARD, HALF_PPR, or PPR, a team_count that must be an even number in the inclusive range 4 to 16, a roster_size between 12 and 20 inclusive, a starter_count between 7 and 11 inclusive".

        Claim: the create payload's input fields are echoed in the
        response.
        """
        payload = create_league_payload(
            season_year=2027,
            draft_mode="AUCTION",
            scoring_mode="PPR",
            team_count=6,
            roster_size=14,
            starter_count=9,
            ir_slots=2,
            faab_budget_dollars=200,
            playoff_team_count=4,
            regular_season_weeks=12,
        )
        res = api.create_league(payload, commissioner_headers)
        data = validate_success(res, 201)
        assert data["season_year"] == 2027
        assert data["draft_mode"] == "AUCTION"
        assert data["scoring_mode"] == "PPR"
        assert data["team_count"] == 6
        assert data["roster_size"] == 14
        assert data["starter_count"] == 9
        assert data["ir_slots"] == 2

    def test_default_auction_budget_is_200_when_omitted(self, api, commissioner_headers):
        """PRD §3.1: "an optional auction_budget_dollars in the inclusive range 0 to 500 (defaulting to 200, and operationally meaningful only when draft_mode is AUCTION)".

        Claim: omitting auction_budget_dollars yields 200.
        """
        payload = create_league_payload(draft_mode="AUCTION")
        # Strip auction_budget_dollars in case the factory defaulted it.
        payload.pop("auction_budget_dollars", None)
        res = api.create_league(payload, commissioner_headers)
        data = validate_success(res, 201)
        assert data["auction_budget_dollars"] == 200

    def test_default_veto_quorum_pct_is_50(self, api, commissioner_headers):
        """PRD §3.1: "an optional veto_quorum_pct defaulting to 50 (in the inclusive range 25 to 100)".

        Claim: omitting veto_quorum_pct yields 50.
        """
        payload = create_league_payload()
        payload.pop("veto_quorum_pct", None)
        res = api.create_league(payload, commissioner_headers)
        data = validate_success(res, 201)
        assert data["veto_quorum_pct"] == 50

    def test_default_trade_review_hours_is_48(self, api, commissioner_headers):
        """PRD §3.1: "an optional trade_review_hours defaulting to 48 (in the inclusive range 0 to 168)".

        Claim: omitting trade_review_hours yields 48.
        """
        payload = create_league_payload()
        payload.pop("trade_review_hours", None)
        res = api.create_league(payload, commissioner_headers)
        data = validate_success(res, 201)
        assert data["trade_review_hours"] == 48

    def test_default_waiver_period_hours_is_48(self, api, commissioner_headers):
        """PRD §3.1: "an optional waiver_period_hours defaulting to 48 (in the inclusive range 0 to 168)".

        Claim: omitting waiver_period_hours yields 48.
        """
        payload = create_league_payload()
        payload.pop("waiver_period_hours", None)
        res = api.create_league(payload, commissioner_headers)
        data = validate_success(res, 201)
        assert data["waiver_period_hours"] == 48


class TestLeagueCreateValidation:
    @pytest.mark.parametrize("team_count", [3, 5, 17, 2, 0])
    def test_team_count_invalid_rejected(self, api, commissioner_headers, team_count):
        """PRD §3.1: "a team_count that must be an even number in the inclusive range 4 to 16".

        Claim: odd team_count or out-of-range team_count is rejected
        with ERR_VALIDATION.
        """
        payload = create_league_payload(team_count=team_count)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("roster_size", [11, 21, 0])
    def test_roster_size_out_of_range_rejected(
        self, api, commissioner_headers, roster_size,
    ):
        """PRD §3.1: "a roster_size between 12 and 20 inclusive".

        Claim: roster_size below 12 or above 20 is rejected with
        ERR_VALIDATION.
        """
        payload = create_league_payload(roster_size=roster_size)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("starter_count", [6, 12])
    def test_starter_count_out_of_range_rejected(
        self, api, commissioner_headers, starter_count,
    ):
        """PRD §3.1: "a starter_count between 7 and 11 inclusive".

        Claim: starter_count outside [7, 11] is rejected with ERR_VALIDATION.
        """
        payload = create_league_payload(starter_count=starter_count)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("playoff_team_count", [3, 5, 6, 16])
    def test_playoff_team_count_not_power_of_two_in_set_rejected(
        self, api, commissioner_headers, playoff_team_count,
    ):
        """PRD §3.1: "a playoff_team_count that must be exactly one of 2, 4, or 8".

        Claim: playoff_team_count outside {2,4,8} is rejected.
        """
        payload = create_league_payload(playoff_team_count=playoff_team_count)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("regular_season_weeks", [9, 15])
    def test_regular_season_weeks_out_of_range_rejected(
        self, api, commissioner_headers, regular_season_weeks,
    ):
        """PRD §3.1: "a regular_season_weeks in the inclusive range 10 to 14".

        Claim: regular_season_weeks outside [10, 14] rejected.
        """
        payload = create_league_payload(regular_season_weeks=regular_season_weeks)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("season_year", [2019, 2000])
    def test_season_year_below_minimum_rejected(
        self, api, commissioner_headers, season_year,
    ):
        """PRD §3.1: "a season_year the league is playing (which must be 2020 or later)".

        Claim: season_year < 2020 rejected.
        """
        payload = create_league_payload(season_year=season_year)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)

    @pytest.mark.parametrize("draft_mode", ["snake", "PICK", ""])
    def test_invalid_draft_mode_rejected(self, api, commissioner_headers, draft_mode):
        """PRD §3.1: "a draft_mode of either SNAKE or AUCTION".

        Claim: draft_mode not in {SNAKE, AUCTION} rejected.
        """
        payload = create_league_payload(draft_mode=draft_mode)
        res = api.create_league(payload, commissioner_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Team creation — PRD §3.1, §3.3
# ===========================================================================
class TestTeamCreate:
    def test_team_created_with_faab_budget_initialized(self, api, commissioner_headers):
        """PRD §3.1: "The team's faab_balance_dollars is initialized at team creation to the league's faab_budget_dollars".

        Claim: a freshly created team has faab_balance_dollars equal to
        League.faab_budget_dollars.
        """
        league = create_league(team_count=4, faab_budget_dollars=150)
        res = api.create_team(
            league["id"],
            create_team_payload(manager_user_id=manager_uid("crud-1")),
            commissioner_headers,
        )
        team = validate_success(res, 201)
        assert_team(team)
        assert team["faab_balance_dollars"] == 150

    def test_team_starts_with_zero_auction_balance_until_drafting(
        self, api, commissioner_headers,
    ):
        """PRD §3.1: "its auction_balance_dollars starts at 0 (and is reset to League.auction_budget_dollars at the entry into DRAFTING if the league is AUCTION)".

        Claim: a freshly created team has auction_balance_dollars=0
        while the league is still DRAFT_PENDING.
        """
        league = create_league(team_count=4, draft_mode="AUCTION", auction_budget_dollars=200)
        res = api.create_team(
            league["id"],
            create_team_payload(manager_user_id=manager_uid("crud-2")),
            commissioner_headers,
        )
        team = validate_success(res, 201)
        assert team["auction_balance_dollars"] == 0

    def test_team_draft_position_null_in_draft_pending(self, api, commissioner_headers):
        """PRD §3.1: "draft_position is null while the league is still DRAFT_PENDING and is assigned by the server (taking values 1 through team_count) when the league transitions to DRAFTING."

        Claim: a freshly created team has draft_position = null.
        """
        league = create_league(team_count=4)
        res = api.create_team(
            league["id"],
            create_team_payload(manager_user_id=manager_uid("crud-3")),
            commissioner_headers,
        )
        team = validate_success(res, 201)
        assert team.get("draft_position") is None


# ===========================================================================
# Start-draft — PRD §3.3
# ===========================================================================
class TestStartDraft:
    def test_start_draft_transitions_to_drafting_and_assigns_positions(
        self, api, commissioner_headers,
    ):
        """PRD §3.3: "Starting the draft is a Commissioner-only transition from DRAFT_PENDING into DRAFTING."
        PRD §3.1: "draft_position is null while the league is still DRAFT_PENDING and is assigned by the server (taking values 1 through team_count) when the league transitions to DRAFTING."

        Claim: start-draft moves League.status to DRAFTING and every
        team has draft_position in 1..team_count.
        """
        league, teams = create_league_with_teams(team_count=4)
        res = api.start_draft(league["id"], commissioner_headers)
        league = validate_success(res, 200)
        assert league["status"] == "DRAFTING"
        # Re-list teams to inspect draft_position.
        for t in teams:
            t_after = validate_success(
                api.get_team(league["id"], t["id"], commissioner_headers), 200,
            )
            assert isinstance(t_after.get("draft_position"), int), \
                "PRD §3.1: server assigns draft_position at DRAFT_PENDING → DRAFTING"
            assert 1 <= t_after["draft_position"] <= 4

    def test_start_draft_requires_team_count_matches(self, api, commissioner_headers):
        """PRD §3.3: "It requires three things to be true: the count of Team rows must exactly equal League.team_count".

        Claim: starting the draft when fewer than team_count Teams are
        registered is rejected with ERR_INVALID_STATE.
        """
        league = create_league(team_count=4)
        # Only create 3 teams.
        for i in range(3):
            api.create_team(
                league["id"],
                create_team_payload(manager_user_id=manager_uid(f"under-{i}")),
                commissioner_headers,
            )
        res = api.start_draft(league["id"], commissioner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_draft_seeds_auction_balance_in_auction_mode(
        self, api, commissioner_headers,
    ):
        """PRD §3.3: "each team's auction_balance_dollars is set to League.auction_budget_dollars for AUCTION leagues (and to 0 otherwise)".

        Claim: after start-draft, every team in an AUCTION league has
        auction_balance_dollars == League.auction_budget_dollars.
        """
        league, teams = create_league_with_teams(
            team_count=4, draft_mode="AUCTION", auction_budget_dollars=150,
        )
        api.start_draft(league["id"], commissioner_headers)
        for t in teams:
            t_after = validate_success(
                api.get_team(league["id"], t["id"], commissioner_headers), 200,
            )
            assert t_after["auction_balance_dollars"] == 150, \
                "PRD §3.3: auction_balance_dollars := League.auction_budget_dollars at start-draft"


# ===========================================================================
# Finish-draft — PRD §3.3
# ===========================================================================
class TestFinishDraft:
    def test_finish_draft_transitions_to_regular_season(
        self, api, commissioner_headers,
    ):
        """PRD §3.3: "Finishing the draft is a separate Commissioner-only transition from DRAFTING into REGULAR_SEASON."

        Claim: finish-draft moves League.status to REGULAR_SEASON and
        current_week becomes 1.
        """
        bundle = setup_drafted_league(team_count=4, regular_season_weeks=10)
        league = bundle["league"]
        assert league["status"] == "REGULAR_SEASON"
        assert league["current_week"] == 1, \
            "PRD §3.3: current_week is set to 1 at finish-draft"


# ===========================================================================
# Archive — PRD §3.8
# ===========================================================================
class TestArchive:
    def test_archive_from_non_completed_rejected(self, api, commissioner_headers):
        """PRD §3.8: "A Commissioner may archive a league whose status is COMPLETED, transitioning it to ARCHIVED (the terminal state)."

        Claim: trying to archive a DRAFT_PENDING league is rejected
        with ERR_INVALID_STATE.
        """
        league = create_league(team_count=4)
        res = api.archive_league(league["id"], commissioner_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
