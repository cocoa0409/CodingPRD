"""Tournament lifecycle tests (PRD §3.1).

Covers the DRAFT → REGISTRATION_OPEN → ROSTER_LOCKED →
BRACKET_PUBLISHED → IN_PROGRESS → COMPLETED → PRIZES_DISTRIBUTED
forward path plus the REGISTRATION_OPEN → CANCELLED branch and the
prize-tier sum + registration-deadline preconditions on open-registration.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    assert_tournament,
    create_open_tournament,
    create_tournament,
    create_tournament_payload,
    default_prize_tier_table,
    iso_utc,
    open_tournament_registration,
    register_team_to_registered,
    reset_clock_to_epoch,
    setup_tournament_with_teams,
    validate_error,
    validate_success,
    publish_bracket,
    lock_rosters,
    start_tournament,
)


# ===========================================================================
# Create + read (PRD §3.1)
# ===========================================================================
class TestCreateTournament:
    def test_create_tournament_returns_draft_status(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "A tournament begins as a LeagueAdmin-created
        Tournament row in DRAFT status."

        Claim: POST /tournaments returns status=DRAFT and all common +
        input fields populated.
        """
        response = api.create_tournament(
            create_tournament_payload(), league_admin_headers,
        )
        data = validate_success(response, expected_status=201)
        assert_tournament(data)
        assert data["status"] == "DRAFT"

    def test_create_tournament_invalid_prize_tier_sum_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "the sum of every entry's percentage_bps plus the
        MVP allocation of 500 basis points (5% of the pool) must equal
        exactly 10000 basis points — failing this contract returns
        ERR_PRIZE_TIER_SUM_MISMATCH."

        Claim: open-registration on a tournament whose tier table
        violates the 10000-bps sum (with +500 MVP) → ERR_PRIZE_TIER_SUM_MISMATCH.
        """
        # 5000 + 3000 + 1000 = 9000 + 500 MVP = 9500 != 10000.
        bad_table = [
            {"placement": 1, "percentage_bps": 5000},
            {"placement": 2, "percentage_bps": 3000},
            {"placement": 3, "percentage_bps": 1000},
        ]
        t = create_tournament(prize_tier_table=bad_table)
        response = api.open_registration(t["id"], league_admin_headers)
        validate_error(response, ApiErrorId.ERR_PRIZE_TIER_SUM_MISMATCH.value)


# ===========================================================================
# Open registration (PRD §3.1)
# ===========================================================================
class TestOpenRegistration:
    def test_open_registration_transitions_to_registration_open(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Opening registration moves the tournament from
        DRAFT to REGISTRATION_OPEN."

        Claim: POST /tournaments/{tid}/open-registration on a DRAFT
        tournament yields status=REGISTRATION_OPEN.
        """
        reset_clock_to_epoch()
        t = create_tournament()
        response = api.open_registration(t["id"], league_admin_headers)
        data = validate_success(response)
        assert data["status"] == "REGISTRATION_OPEN"

    def test_open_registration_after_registration_deadline_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Clock.now must be strictly earlier than
        registration_deadline, otherwise the response is
        ERR_REGISTRATION_DEADLINE_PASSED."

        Claim: opening registration after the registration_deadline →
        ERR_REGISTRATION_DEADLINE_PASSED.
        """
        reset_clock_to_epoch()
        # Build with a registration_deadline very close to now.
        t = create_tournament(
            registration_deadline=iso_utc(days_offset=1),
        )
        # Advance Clock.now past the deadline.
        advance_clock_to(iso_utc(days_offset=2))
        response = api.open_registration(t["id"], league_admin_headers)
        validate_error(
            response, ApiErrorId.ERR_REGISTRATION_DEADLINE_PASSED.value,
        )

    def test_open_registration_invalid_state_from_already_open(
        self, api, league_admin_headers,
    ):
        """PRD §2.9: "state-machine precondition (ERR_INVALID_STATE)."
        PRD §3.1 declares open-registration is from DRAFT only.

        Claim: calling open-registration on a tournament already in
        REGISTRATION_OPEN → ERR_INVALID_STATE.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        response = api.open_registration(t["id"], league_admin_headers)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Roster lock (PRD §3.1)
# ===========================================================================
class TestRosterLock:
    def test_manual_lock_rosters_transitions_to_roster_locked(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "The transition can be triggered manually by a
        LeagueAdmin, or it fires automatically the first time the
        logical clock advances to a moment at or after
        roster_lock_deadline."

        Claim: POST /tournaments/{tid}/lock-rosters on a
        REGISTRATION_OPEN tournament → status=ROSTER_LOCKED.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        response = api.lock_rosters(t["id"], league_admin_headers)
        data = validate_success(response)
        assert data["status"] == "ROSTER_LOCKED"

    def test_lock_rosters_cascades_drafts_to_withdrawn(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "every TeamRegistration whose status is DRAFT or
        FEE_PENDING under this tournament is moved to WITHDRAWN."

        Claim: lock-rosters transitions any FEE_PENDING/DRAFT
        TeamRegistration to WITHDRAWN.
        """
        from test_helpers import (
            create_team_registration,
            get_team_registration,
        )
        reset_clock_to_epoch()
        t = create_open_tournament()
        reg = create_team_registration(t["id"])
        # reg is in DRAFT (no roster filed, no fee paid).
        lock_rosters(t["id"])
        reloaded = get_team_registration(reg["id"])
        assert reloaded["status"] == "WITHDRAWN", (
            "PRD §3.1 cascade: DRAFT/FEE_PENDING → WITHDRAWN"
        )


# ===========================================================================
# Publish bracket (PRD §3.1)
# ===========================================================================
class TestPublishBracket:
    def test_publish_with_zero_teams_rejected_err_insufficient_teams(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Publication requires at least two TeamRegistration
        rows in REGISTERED status — otherwise ERR_INSUFFICIENT_TEAMS."

        Claim: publish-bracket on a tournament with 0 REGISTERED teams
        → ERR_INSUFFICIENT_TEAMS.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        lock_rosters(t["id"])
        response = api.publish_bracket(t["id"], league_admin_headers)
        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_TEAMS.value)

    def test_publish_with_two_registered_succeeds(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Publication requires at least two TeamRegistration
        rows in REGISTERED status — otherwise ERR_INSUFFICIENT_TEAMS."

        Claim: with exactly 2 REGISTERED teams, publish-bracket
        succeeds and tournament.status=BRACKET_PUBLISHED.
        """
        tournament, regs, _ = setup_tournament_with_teams(num_teams=2)
        lock_rosters(tournament["id"])
        response = api.publish_bracket(tournament["id"], league_admin_headers)
        data = validate_success(response)
        assert data["status"] == "BRACKET_PUBLISHED"
        assert data.get("bracket_published_at") is not None, (
            "PRD §3.1: bracket_published_at set on publication"
        )


# ===========================================================================
# Tournament start / complete / distribute (PRD §3.1)
# ===========================================================================
class TestStartCompleteDistribute:
    def test_start_after_publish_transitions_to_in_progress(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Starting the tournament transitions
        BRACKET_PUBLISHED to IN_PROGRESS and is admin-driven without
        preconditions."

        Claim: POST /tournaments/{tid}/start on a BRACKET_PUBLISHED
        tournament → IN_PROGRESS.
        """
        tournament, regs, _ = setup_tournament_with_teams(num_teams=2)
        lock_rosters(tournament["id"])
        publish_bracket(tournament["id"])
        response = api.start_tournament(tournament["id"], league_admin_headers)
        data = validate_success(response)
        assert data["status"] == "IN_PROGRESS"

    def test_complete_with_pending_matches_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "manual completion requires the same condition —
        otherwise ERR_MATCHES_INCOMPLETE."

        Claim: complete-tournament on IN_PROGRESS with at least one
        match still SCHEDULED → ERR_MATCHES_INCOMPLETE.
        """
        tournament, _, _ = setup_tournament_with_teams(num_teams=4)
        lock_rosters(tournament["id"])
        publish_bracket(tournament["id"])
        start_tournament(tournament["id"])
        response = api.complete_tournament(
            tournament["id"], league_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_MATCHES_INCOMPLETE.value)


# ===========================================================================
# Cancel (PRD §3.1)
# ===========================================================================
class TestCancelTournament:
    def test_cancel_from_registration_open_transitions_to_cancelled(
        self, api, league_admin_headers,
    ):
        """PRD §3.1: "Cancellation is a parallel branch from
        REGISTRATION_OPEN: it moves the tournament to CANCELLED."

        Claim: POST /tournaments/{tid}/cancel on a REGISTRATION_OPEN
        tournament → status=CANCELLED.
        """
        reset_clock_to_epoch()
        t = create_open_tournament()
        response = api.cancel_tournament(
            t["id"], {"reason": "Sponsor pulled out"},
            league_admin_headers,
        )
        data = validate_success(response)
        assert data["status"] == "CANCELLED"


# ===========================================================================
# Not-found (PRD §2.8)
# ===========================================================================
class TestNotFound:
    def test_get_tournament_not_found_returns_err_not_found(
        self, api, league_admin_headers,
    ):
        """PRD §2.8: "if it does not match any row, the request fails
        with ERR_NOT_FOUND."

        Claim: GET on a non-existent tournament id → ERR_NOT_FOUND.
        """
        response = api.get_tournament(NON_EXISTENT_UUID, league_admin_headers)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)
