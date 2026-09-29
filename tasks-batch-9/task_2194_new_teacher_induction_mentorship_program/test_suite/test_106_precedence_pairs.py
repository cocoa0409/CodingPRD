"""Requests that break two rules at once, where the ladder decides which refusal
the caller hears.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED,
    ERR_DAILY_CREDIT_CAP_REACHED,
    ERR_MATCH_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SEMINAR_SESSION_OVERLAP,
)
from test_helpers.fixtures import (
    build_program,
    create_cohort,
    create_site,
    read_match,
    read_session,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, make_site_lead_headers


class TestMatchStateOutranksDailyCreditCap:
    """A suspended match reports its state even when the day's room is exhausted."""

    @staticmethod
    def _exhausted_day_on_a_suspended_match(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-07T12:00:00Z")
        first = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T09:00:00Z",
            minutes=180,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        second = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T15:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Afternoon one-on-one conversation about classroom management routines",
        )
        verify_contact_log(api, first["id"], lead)
        validate_success(
            api.certification_action(
                program["mentor_id"],
                f.certification_payload(
                    "SUSPEND", reason="Fingerprint clearance expired pending renewal"
                ),
                ADMIN,
            )
        )
        program["lead"] = lead
        program["first_log_id"] = first["id"]
        program["second_log_id"] = second["id"]
        return program

    def test_suspended_match_reports_the_state_error_not_the_cap(
        self, api: InductionApiClient
    ):
        """Both rules are broken and the 409 match-state refusal is what comes back.

        The PRD settles this exact pair on the ladder: "Match-state gating
        outranks every fiscal rule below it, so verifying against a `SUSPENDED`
        match reports the match-state error even when the same-day credit ceiling
        is simultaneously exhausted."

        Design: Difficulty/priority_pair_validation_conflict/match_state_outranks_daily_credit_cap
        """
        program = self._exhausted_day_on_a_suspended_match(api)

        response = api.review_contact_log(
            program["second_log_id"],
            f.review_payload("VERIFY", note="Attempted verification of the second log"),
            program["lead"],
        )
        error = validate_error(response, ERR_MATCH_STATE_INVALID, 409)
        assert error["error_id"] != ERR_DAILY_CREDIT_CAP_REACHED, (
            "the exhausted daily ceiling must not mask the earlier match-state rung"
        )

        log = validate_success(api.get_contact_log(program["second_log_id"], ADMIN))
        assert log["verification_status"] == "SUBMITTED", (
            f"the refused review changes nothing, got {log['verification_status']}"
        )
        assert log["credited_minutes"] == 0, "a refused review credits nothing"

        match = read_match(api, program["match_id"])
        assert match["match_status"] == "SUSPENDED", (
            f"the mentor's suspension carried the match down, got {match['match_status']}"
        )
        assert match["verified_minutes_total"] == 180, (
            f"only the first log's minutes stand, got {match['verified_minutes_total']}"
        )

    def test_the_masked_cap_rule_fires_once_the_match_is_active_again(
        self, api: InductionApiClient
    ):
        """Reinstating the mentor reactivates the match, and then the 422 cap is heard.

        The lower rung is genuinely live; it was only outranked. The PRD states
        it plainly: "If the already-credited total for that match and date has
        reached the full three hours, so that no room at all remains, the
        verification is refused outright with `ERR_DAILY_CREDIT_CAP_REACHED`
        rather than producing a zero-minute credit."

        Design: Difficulty/priority_pair_validation_conflict/match_state_outranks_daily_credit_cap
        """
        program = self._exhausted_day_on_a_suspended_match(api)

        validate_success(
            api.certification_action(
                program["mentor_id"], f.certification_payload("REINSTATE"), ADMIN
            )
        )
        assert read_match(api, program["match_id"])["match_status"] == "ACTIVE", (
            "reinstatement reactivates the suspended match, since the site is OPEN, "
            "the novice is ACTIVE and neither cap is full"
        )

        response = api.review_contact_log(
            program["second_log_id"],
            f.review_payload("VERIFY", note="Attempted verification of the second log"),
            program["lead"],
        )
        validate_error(response, ERR_DAILY_CREDIT_CAP_REACHED, 422)
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 180


class TestSeminarOverlapOutranksWeeklyMinuteCap:
    """A session that both overlaps and busts the week reports the overlap."""

    @staticmethod
    def _week_at_the_cap(api: InductionApiClient) -> dict:
        create_site(api)
        cohort = create_cohort(api)
        first = schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-03T14:00:00Z",
            "2026-08-03T16:00:00Z",
            topic="Classroom routines seminar",
        )
        second = schedule_seminar_session(
            api,
            cohort["id"],
            2,
            "2026-08-04T14:00:00Z",
            "2026-08-04T16:00:00Z",
            topic="Formative assessment seminar",
        )
        return {
            "cohort_id": cohort["id"],
            "first_id": first["id"],
            "second_id": second["id"],
        }

    def test_overlapping_proposal_reports_the_overlap_not_the_weekly_cap(
        self, api: InductionApiClient
    ):
        """A third 120-minute session overlapping Monday's is refused as an overlap.

        Rung 25 precedes rung 26 on the ladder: "The proposed seminar window
        clears the cohort overlap check — otherwise `ERR_SEMINAR_SESSION_OVERLAP`
        (HTTP 409), per §2.11." Only then comes: "The cohort's weekly seminar
        minute budget is not exceeded — otherwise
        `ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED` (HTTP 422), per §2.11."

        Design: Difficulty/priority_pair_validation_conflict/seminar_overlap_outranks_weekly_minute_cap
        """
        context = self._week_at_the_cap(api)

        response = api.create_seminar_session(
            f.seminar_session_payload(
                context["cohort_id"],
                3,
                "2026-08-03T15:00:00Z",
                "2026-08-03T17:00:00Z",
                topic="Family engagement seminar",
            ),
            ADMIN,
        )
        error = validate_error(response, ERR_SEMINAR_SESSION_OVERLAP, 409)
        assert error["error_id"] != ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED, (
            "the 360-minute week must not mask the earlier overlap rung"
        )

        rows, meta = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": context["cohort_id"]})
        )
        assert meta["total_count"] == 2, (
            f"the refused proposal was not stored, got total_count {meta['total_count']}"
        )
        assert read_session(api, context["first_id"])["status"] == "SCHEDULED"
        assert read_session(api, context["second_id"])["status"] == "SCHEDULED"
        assert len(rows) == 2

    def test_the_masked_weekly_cap_fires_for_a_clear_window_in_the_same_week(
        self, api: InductionApiClient
    ):
        """Moved to Wednesday the proposal no longer overlaps, and the 422 cap is heard.

        The weekly budget is the rule that was outranked, and the PRD fixes its
        boundary: "Every individual session may be legally sized and
        non-overlapping and the collective weekly load still be refused. A total
        of exactly 240 minutes is accepted; 241 is not."

        Design: Difficulty/priority_pair_validation_conflict/seminar_overlap_outranks_weekly_minute_cap
        """
        context = self._week_at_the_cap(api)

        response = api.create_seminar_session(
            f.seminar_session_payload(
                context["cohort_id"],
                3,
                "2026-08-05T14:00:00Z",
                "2026-08-05T16:00:00Z",
                topic="Family engagement seminar",
            ),
            ADMIN,
        )
        validate_error(response, ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED, 422)

        _, meta = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": context["cohort_id"]})
        )
        assert meta["total_count"] == 2, (
            f"the week keeps only its two 120-minute sessions, got {meta['total_count']}"
        )


class TestDutyConflictOutranksDailyCreditCap:
    """Reviewing your own submission is refused as a duty conflict, not as a cap."""

    @staticmethod
    def _lead_submitted_log_on_an_exhausted_day(api: InductionApiClient) -> dict:
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-07T12:00:00Z")
        first = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T09:00:00Z",
            minutes=180,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
        )
        verify_contact_log(api, first["id"], lead)
        second = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-06T16:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            headers=lead,
            description="Late afternoon coaching conversation entered by the site lead",
        )
        program["lead"] = lead
        program["second_log_id"] = second["id"]
        return program

    def test_self_review_reports_the_duty_conflict_not_the_cap(
        self, api: InductionApiClient
    ):
        """The submitting lead's own verification is a 403, even with zero room left.

        Rung 22 sits well above the fiscal rungs: "Separation of duties holds —
        otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), per §2.9. This sits
        above every referential and fiscal rule, so attesting your own evidence
        against an unattained prerequisite reports the duty conflict, not the
        prerequisite gap."

        Design: Difficulty/priority_pair_validation_conflict/duty_conflict_outranks_daily_credit_cap
        """
        program = self._lead_submitted_log_on_an_exhausted_day(api)

        response = api.review_contact_log(
            program["second_log_id"],
            f.review_payload("VERIFY", note="Site lead verifying the log it submitted"),
            program["lead"],
        )
        error = validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)
        assert error["error_id"] != ERR_DAILY_CREDIT_CAP_REACHED, (
            "the exhausted daily ceiling must not mask the duty rung above it"
        )

        log = validate_success(api.get_contact_log(program["second_log_id"], ADMIN))
        assert log["submitted_by_user_id"] == program["lead"]["X-User-ID"], (
            "the log records the lead as its submitter, which is what the duty rule "
            f"compares against, got {log['submitted_by_user_id']}"
        )
        assert log["verification_status"] == "SUBMITTED", (
            f"the refused review changes nothing, got {log['verification_status']}"
        )
        assert log["verified_by_user_id"] is None, (
            "no verifier is recorded for a refused review"
        )
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 180

    def test_a_different_reviewer_hears_the_masked_cap_instead(
        self, api: InductionApiClient
    ):
        """With the duty rule satisfied, the same request reports the 422 cap.

        The duty rule compares two identities and nothing else: "A contact log's
        `verified_by_user_id` may not equal its `submitted_by_user_id`."

        Design: Difficulty/priority_pair_validation_conflict/duty_conflict_outranks_daily_credit_cap
        """
        program = self._lead_submitted_log_on_an_exhausted_day(api)

        response = api.review_contact_log(
            program["second_log_id"],
            f.review_payload("VERIFY", note="Program office verifying the lead's entry"),
            ADMIN,
        )
        validate_error(response, ERR_DAILY_CREDIT_CAP_REACHED, 422)
        assert read_match(api, program["match_id"])["verified_minutes_total"] == 180
