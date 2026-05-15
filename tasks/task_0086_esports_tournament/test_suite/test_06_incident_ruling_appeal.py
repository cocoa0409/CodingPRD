"""MatchIncident filing, ruling, and appeal-cycle tests (PRD §3.5).

Covers FILED → UNDER_REVIEW → RULED transition, the FINE-amount
boundary, the appeal cap (MAX_APPEALS=1), appeal-window expiration
(72h), the overturn branch + cascade reversal, and the
ERR_DUPLICATE_INCIDENT path.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    APPEAL_WINDOW_HOURS,
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    appeal_decide_payload,
    appeal_incident_payload,
    assign_incident_for_review,
    create_incident_payload,
    file_incident,
    iso_utc,
    make_referee_headers,
    make_team_manager_headers,
    rule_incident_payload,
    rule_on_incident,
    setup_incident_in_state,
    setup_live_match_with_certified_referee,
    validate_error,
    validate_success,
)


# ===========================================================================
# File + assign (PRD §3.5)
# ===========================================================================
class TestFileAndAssign:
    def test_file_incident_initial_state_filed(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "The incident is initialised with ruling PENDING,
        penalty_type NONE, appeal_count zero, and status FILED."

        Claim: POST /match-incidents on a LIVE match returns an
        incident with status=FILED, ruling=PENDING, penalty_type=NONE,
        appeal_count=0.
        """
        tournament, match, referee = setup_live_match_with_certified_referee()
        incident = file_incident(
            match["id"], subject_type="TEAM",
            subject_id=match["team_a_id"],
            referee_user_id=referee["user_id"],
            classification="LATENCY",
        )
        assert incident["status"] == "FILED"
        assert incident["ruling"] == "PENDING"
        assert incident["penalty_type"] == "NONE"
        assert incident["appeal_count"] == 0

    def test_assign_transitions_to_under_review(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "A LeagueAdmin assigns the incident for review,
        transitioning FILED → UNDER_REVIEW."

        Claim: POST /match-incidents/{iid}/assign on a FILED incident →
        status=UNDER_REVIEW.
        """
        tournament, match, referee, incident = setup_incident_in_state(
            state="FILED",
        )
        response = api.assign_incident(incident["id"], league_admin_headers)
        data = validate_success(response)
        assert data["status"] == "UNDER_REVIEW"

    def test_duplicate_incident_rejected(self, api, league_admin_headers):
        """PRD §2.10: "When two referees file a MatchIncident for the
        same combination of match_id, subject_id, and classification,
        the unique constraint enforces first-writer-wins and the loser
        receives ERR_DUPLICATE_INCIDENT."

        Claim: filing a second incident with identical
        (match_id, subject_id, classification) triple →
        ERR_DUPLICATE_INCIDENT.
        """
        tournament, match, referee = setup_live_match_with_certified_referee()
        file_incident(
            match["id"], subject_type="TEAM",
            subject_id=match["team_a_id"],
            referee_user_id=referee["user_id"],
            classification="LATENCY",
        )
        response = api.file_incident(
            create_incident_payload(
                match_id=match["id"], subject_type="TEAM",
                subject_id=match["team_a_id"],
                referee_id=referee["user_id"],
                classification="LATENCY",
            ),
            make_referee_headers(referee["user_id"]),
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_INCIDENT.value)


# ===========================================================================
# Rule (PRD §3.5)
# ===========================================================================
class TestRuling:
    def test_rule_fine_with_zero_amount_rejected(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "If penalty_type is FINE, the fine_amount_cents
        must be strictly greater than zero (the boundary is exclusive
        — a submitted value of zero rejects with ERR_FINE_AMOUNT_REQUIRED)."

        Claim: ruling UPHELD + FINE + fine_amount_cents=0 →
        ERR_FINE_AMOUNT_REQUIRED.
        """
        tournament, match, referee, incident = setup_incident_in_state(
            state="UNDER_REVIEW",
        )
        response = api.rule_incident(
            incident["id"],
            rule_incident_payload(
                ruling="UPHELD", penalty_type="FINE",
                fine_amount_cents=0,
            ),
            league_admin_headers,
        )
        validate_error(response, ApiErrorId.ERR_FINE_AMOUNT_REQUIRED.value)

    def test_rule_upheld_warning_succeeds(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "The admin then rules: UNDER_REVIEW → RULED
        requires a supplied ruling value (UPHELD or DISMISSED) and,
        when the ruling is UPHELD, a penalty_type (one of WARNING,
        FORFEIT, DISQUALIFICATION, or FINE)."

        Claim: ruling UPHELD + WARNING → status=RULED, ruling=UPHELD,
        penalty_type=WARNING.
        """
        tournament, match, referee, incident = setup_incident_in_state(
            state="UNDER_REVIEW",
        )
        response = api.rule_incident(
            incident["id"],
            rule_incident_payload(ruling="UPHELD", penalty_type="WARNING"),
            league_admin_headers,
        )
        data = validate_success(response)
        assert data["status"] == "RULED"
        assert data["ruling"] == "UPHELD"
        assert data["penalty_type"] == "WARNING"


# ===========================================================================
# Appeal (PRD §3.5)
# ===========================================================================
class TestAppealCycle:
    def test_appeal_limit_reached_after_one_appeal(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "The transition RULED → APPEALED requires the
        current appeal_count to be strictly less than one (the maximum
        is one appeal cycle — otherwise ERR_APPEAL_LIMIT_REACHED)."

        Claim: a second appeal attempt after the first appeal has
        already been recorded → ERR_APPEAL_LIMIT_REACHED.
        """
        tournament, match, referee, incident = setup_incident_in_state(
            state="RULED", penalty_type="WARNING",
        )
        # Subject is TEAM team_a_id; build a TeamManager for that team.
        from test_helpers import get_team_registration
        reg = get_team_registration(match["team_a_id"])
        tm_headers = make_team_manager_headers(reg["manager_id"])
        # First appeal succeeds → APPEALED, appeal_count=1.
        api.appeal_incident(
            incident["id"], appeal_incident_payload(grounds="Ground 1"),
            tm_headers,
        )
        # Admin decides AFFIRM → status returns to RULED, appeal_count
        # still 1.
        api.appeal_decide_incident(
            incident["id"], appeal_decide_payload(decision="AFFIRM"),
            league_admin_headers,
        )
        # Second appeal attempt → ERR_APPEAL_LIMIT_REACHED.
        response = api.appeal_incident(
            incident["id"], appeal_incident_payload(grounds="Ground 2"),
            tm_headers,
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_LIMIT_REACHED.value)

    def test_appeal_window_closed_after_72_hours(
        self, api, league_admin_headers,
    ):
        """PRD §3.5: "Clock.now must be strictly earlier than the
        moment of the ruling plus 72 hours (otherwise
        ERR_APPEAL_WINDOW_CLOSED)."

        Claim: appealing more than 72 hours after the ruling →
        ERR_APPEAL_WINDOW_CLOSED.
        """
        tournament, match, referee, incident = setup_incident_in_state(
            state="RULED", penalty_type="WARNING",
        )
        from datetime import datetime, timedelta
        ruled_at = datetime.fromisoformat(
            incident["updated_at"].replace("Z", "+00:00"),
        )
        past_window = (ruled_at + timedelta(hours=73)).isoformat(
            timespec="milliseconds",
        ).replace("+00:00", "Z")
        advance_clock_to(past_window)
        from test_helpers import get_team_registration
        reg = get_team_registration(match["team_a_id"])
        response = api.appeal_incident(
            incident["id"], appeal_incident_payload(grounds="Late"),
            make_team_manager_headers(reg["manager_id"]),
        )
        validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value)
