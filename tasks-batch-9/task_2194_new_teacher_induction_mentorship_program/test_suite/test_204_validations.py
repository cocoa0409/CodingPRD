"""Field, temporal, cross-entity, aggregate and conditional validation rules and
the boundary cases that sit either side of each one.
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
    ERR_CONTACT_DATE_OUT_OF_WINDOW,
    ERR_PERIOD_NOT_CLOSED,
    ERR_PREREQUISITE_NOT_ATTAINED,
    ERR_SITE_CLOSED,
)
from test_helpers.assertions import (
    assert_date_component,
    assert_instant_equals,
    assert_money_cents,
    assert_two_decimals,
    ids_of,
)
from test_helpers.constants import CLOCK_INITIAL_UTC
from test_helpers.fixtures import (
    attainment_decision_request,
    attainment_for,
    attest_attainment,
    build_program,
    create_cohort,
    create_novice,
    create_site,
    define_milestone,
    read_attainment,
    read_match,
    read_mentor,
    read_novice,
    read_session,
    read_site,
    revoke_attainment,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
    verify_contact_log,
)
from test_helpers.test_users import ADMIN, PAYROLL_PREP, make_mentor_headers, make_site_lead_headers


class TestContactDateWindow:
    """Both ends of the contact-date window are closed."""

    def test_contact_date_outside_match_life_rejected(self, api: InductionApiClient):
        """A date two days before activation and one in the future are both refused.

        The PRD closes the window at both ends: "The `contact_date` must fall inside
        the relationship's active life: on or after the calendar date of the match's
        `activated_at` and, once the match has ended, on or before the calendar date
        of its `ended_at`; it must also not be in the future relative to the logical
        clock."

        Design: Corner/validations/contact_date_outside_match_life_rejected
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-04T12:00:00Z")

        before_activation = api.create_contact_log(
            f.contact_log_payload(
                program["match_id"],
                "2026-07-30T09:00:00Z",
                60,
                "ONE_ON_ONE",
                description="Pre-activation planning conversation",
            ),
            mentor_headers,
        )
        validate_error(before_activation, ERR_CONTACT_DATE_OUT_OF_WINDOW, 422)

        in_the_future = api.create_contact_log(
            f.contact_log_payload(
                program["match_id"],
                "2026-08-05T09:00:00Z",
                60,
                "ONE_ON_ONE",
                description="Planning conversation scheduled for tomorrow",
            ),
            mentor_headers,
        )
        validate_error(in_the_future, ERR_CONTACT_DATE_OUT_OF_WINDOW, 422)

        _, meta = validate_paginated(
            api.list_contact_logs(ADMIN, {"match_id": program["match_id"]})
        )
        assert meta["total_count"] == 0, (
            f"neither refused log was stored, got total_count {meta['total_count']}"
        )
        match = read_match(api, program["match_id"])
        assert match["match_status"] == "ACTIVE", (
            f"the refusals leave the relationship alone, got {match['match_status']}"
        )
        assert match["verified_minutes_total"] == 0

    def test_contact_date_on_activation_day_accepted(self, api: InductionApiClient):
        """The lower bound is inclusive, so the day of activation itself is in.

        The PRD spells out the granularity mismatch: "Note that the comparison is
        made at date granularity against timestamp-granularity boundaries: a log
        dated the same calendar day as activation is accepted even when its clock
        time precedes the exact `activated_at` instant."

        Design: Corner/validations/contact_date_on_activation_day_accepted
        """
        program = build_program(api)
        set_clock(api, "2026-08-04T12:00:00Z")

        log = validate_success(
            api.create_contact_log(
                f.contact_log_payload(
                    program["match_id"],
                    "2026-08-01T09:00:00Z",
                    60,
                    "ONE_ON_ONE",
                    description="First planning conference on the day of activation",
                ),
                make_mentor_headers(program["mentor_id"]),
            ),
            201,
        )
        assert_date_component(log["contact_date"], "2026-08-01", "contact_date")
        assert log["verification_status"] == "SUBMITTED", (
            f"a new log opens as submitted, got {log['verification_status']}"
        )
        assert log["submitted_by_user_id"] == program["mentor_id"], (
            f"the acting mentor is stamped, got {log['submitted_by_user_id']}"
        )
        assert log["resubmit_count"] == 0
        assert log["credited_minutes"] == 0, (
            f"nothing is credited before verification, got {log['credited_minutes']}"
        )

        stored = validate_success(api.get_contact_log(log["id"], ADMIN))
        assert stored["verified_by_user_id"] is None, (
            f"no verifier yet, got {stored['verified_by_user_id']}"
        )
        assert stored["verified_at"] is None, (
            f"and no verification instant, got {stored['verified_at']}"
        )


class TestClosedSiteBlocksNewAttachment:
    """The identical enrolment body succeeds against one site and fails against another."""

    def test_novice_enrolment_blocked_by_closed_site(self, api: InductionApiClient):
        """Validity depends on the site's state, not on anything in the request body.

        Closure is forward-looking only, and the PRD says what it stops: "What
        closure prevents is *new* attachment: registering a mentor, enrolling a
        novice or proposing a match against a `CLOSED` site is refused with
        `ERR_SITE_CLOSED`."

        Design: Corner/validations/novice_enrolment_blocked_by_closed_site
        """
        open_site = create_site(api)
        closed_site = create_site(
            api, name="Southbank Middle", site_code="SB002", region_code="SOUTH"
        )
        validate_success(
            api.close_site(
                closed_site["id"],
                f.close_site_payload(reason="Campus consolidated into Northgate High"),
                ADMIN,
            )
        )
        cohort = create_cohort(api)

        enrolled = validate_success(
            api.create_novice(
                f.novice_payload(open_site["id"], cohort["id"], full_name="Dana Pike"), ADMIN
            ),
            201,
        )
        assert enrolled["program_status"] == "ENROLLED"
        assert enrolled["site_id"] == open_site["id"]

        refused = api.create_novice(
            f.novice_payload(closed_site["id"], cohort["id"], full_name="Ira Vance"), ADMIN
        )
        validate_error(refused, ERR_SITE_CLOSED, 422)

        stored_closed = read_site(api, closed_site["id"])
        assert stored_closed["status"] == "CLOSED"
        assert_instant_equals(stored_closed["closed_at"], CLOCK_INITIAL_UTC, "closed_at")

        assert validate_success(api.get_cohort(cohort["id"], ADMIN))[
            "enrolled_novice_count"
        ] == 1, "the refused enrolment did not increment the cohort counter"

        rows, meta = validate_paginated(
            api.list_novices(ADMIN, {"cohort_id": cohort["id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the accepted novice exists, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [enrolled["id"]]


class TestStipendPeriodClosure:
    """The period boundary is strict against the logical clock."""

    def test_stipend_period_must_be_strictly_closed(self, api: InductionApiClient):
        """A period_end equal to the clock is refused; one behind it is accepted.

        The PRD makes the comparison strict on one side and inclusive on the other:
        "The period must be closed: `period_end` must be strictly in the past
        relative to the logical clock, or the draft is refused with
        `ERR_PERIOD_NOT_CLOSED`, and `period_end` must be strictly after
        `period_start`."

        Design: Corner/validations/stipend_period_must_be_strictly_closed
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-04T12:00:00Z")
        log = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Planning conference on proportional reasoning",
        )
        verify_contact_log(api, log["id"], lead)
        set_clock(api, "2026-08-05T00:00:00Z")
        mentor_version = read_mentor(api, program["mentor_id"])["version"]

        open_period = api.create_disbursement(
            f.disbursement_payload(
                program["mentor_id"],
                mentor_version,
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-05T00:00:00Z",
            ),
            PAYROLL_PREP,
        )
        validate_error(open_period, ERR_PERIOD_NOT_CLOSED, 422)

        draft = validate_success(
            api.create_disbursement(
                f.disbursement_payload(
                    program["mentor_id"],
                    mentor_version,
                    period_start="2026-08-01T00:00:00Z",
                    period_end="2026-08-04T12:00:00Z",
                ),
                PAYROLL_PREP,
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        assert draft["eligible_log_count"] == 1, (
            "a log verified at exactly the upper bound is inside the closed interval, "
            f"got eligible_log_count {draft['eligible_log_count']}"
        )
        assert_money_cents(draft["gross_cents"], 4200, "gross_cents")

        rows, meta = validate_paginated(
            api.list_disbursements(ADMIN, {"mentor_id": program["mentor_id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused draft was never stored, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [draft["id"]]


class TestCohortWeeklySeminarBudget:
    """The four-hour budget is an ISO-week aggregate, not a rolling seven days."""

    def test_third_ninety_minute_session_exceeds_weekly_cap(self, api: InductionApiClient):
        """Three legal, non-overlapping 90-minute sessions do not fit in one ISO week.

        The PRD defines the window by its Monday boundary: "For the ISO week
        containing the proposed session's start — Monday at 00:00:00 UTC up to but
        not including the following Monday at 00:00:00 UTC — the system sums the
        `scheduled_minutes` of every `SCHEDULED` or `HELD` session of that cohort
        whose `scheduled_start` falls in that week, adds the proposed session's own
        minutes, and refuses the booking if the total exceeds four hours."

        Design: Corner/validations/third_ninety_minute_session_exceeds_weekly_cap
        """
        cohort = create_cohort(api, seminar_sessions_required=4)
        schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:30:00Z",
            topic="Classroom routines",
        )
        schedule_seminar_session(
            api,
            cohort["id"],
            2,
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:30:00Z",
            topic="Formative assessment",
        )

        third_in_week = api.create_seminar_session(
            f.seminar_session_payload(
                cohort["id"],
                3,
                "2026-08-07T09:00:00Z",
                "2026-08-07T10:30:00Z",
                topic="Family engagement",
            ),
            ADMIN,
        )
        validate_error(third_in_week, ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED, 422)

        next_week = validate_success(
            api.create_seminar_session(
                f.seminar_session_payload(
                    cohort["id"],
                    4,
                    "2026-08-10T09:00:00Z",
                    "2026-08-10T10:30:00Z",
                    topic="Family engagement",
                ),
                ADMIN,
            ),
            201,
        )
        assert next_week["scheduled_minutes"] == 90, (
            f"the identical session in the next week is fine, got "
            f"{next_week['scheduled_minutes']}"
        )
        assert next_week["status"] == "SCHEDULED"

        rows, meta = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": cohort["id"]})
        )
        assert meta["total_count"] == 3, (
            f"three sessions survive, got total_count {meta['total_count']}"
        )
        assert 3 not in [row["session_index"] for row in rows], (
            "the refused Friday session was never stored"
        )
        assert read_session(api, next_week["id"])["credited_attendance_count"] == 0


class TestConditionalPrerequisiteRule:
    """The prerequisite rule fires only for a milestone that names one."""

    def test_prerequisite_check_applies_only_when_prerequisite_named(
        self, api: InductionApiClient
    ):
        """The same REOPEN decision is refused on the dependent row and allowed on its parent.

        Reopening carries the prerequisite condition with it: "A `REVOKED` row is
        reopened to `IN_PROGRESS` by a `ProgramAdmin`, which clears `revoke_reason`
        back to null and requires the prerequisite still to be `ATTAINED`; this
        closes the `IN_PROGRESS → ATTAINED → REVOKED → IN_PROGRESS` cycle, so a
        milestone can be earned again after the missing evidence is rebuilt."

        Design: Corner/validations/prerequisite_check_applies_only_when_prerequisite_named
        """
        site = create_site(api)
        cohort = create_cohort(api)
        parent = define_milestone(
            api, "IND_M1", 1, title="Orientation complete", gates_license_recommendation=False
        )
        dependent = define_milestone(
            api,
            "IND_M2",
            2,
            title="Mid-year review complete",
            gates_license_recommendation=False,
            prerequisite_milestone_id=parent["id"],
        )
        novice = create_novice(api, site["id"], cohort["id"], full_name="Dana Pike")
        parent_row = attainment_for(api, novice["id"], parent["id"])
        dependent_row = attainment_for(api, novice["id"], dependent["id"])

        attest_attainment(api, parent_row["id"], evidence_note="Orientation roster on file")
        attest_attainment(
            api, dependent_row["id"], evidence_note="Mid-year review notes on file"
        )
        revoke_attainment(
            api,
            dependent_row["id"],
            revoke_reason="Mid-year review packet was filed against the wrong novice",
        )
        revoke_attainment(
            api,
            parent_row["id"],
            revoke_reason="Orientation roster signature could not be authenticated",
        )

        refused = attainment_decision_request(api, dependent_row["id"], "REOPEN", ADMIN)
        validate_error(refused, ERR_PREREQUISITE_NOT_ATTAINED, 422)

        reopened = validate_success(
            attainment_decision_request(api, parent_row["id"], "REOPEN", ADMIN)
        )
        assert reopened["status"] == "IN_PROGRESS", (
            "the parent names no prerequisite so the rule does not apply to it, got "
            f"{reopened['status']}"
        )
        assert reopened["revoke_reason"] is None, (
            f"reopening clears the revocation reason, got {reopened['revoke_reason']}"
        )

        dependent_after = read_attainment(api, dependent_row["id"])
        assert dependent_after["status"] == "REVOKED", (
            f"the refused reopening changed nothing, got {dependent_after['status']}"
        )
        assert dependent_after["revocation_count"] == 1
        assert read_attainment(api, parent_row["id"])["revocation_count"] == 1, (
            "reopening does not reset the revocation counter"
        )

        final_novice = read_novice(api, novice["id"])
        assert final_novice["attained_milestone_count"] == 0, (
            f"neither milestone is attained now, got {final_novice['attained_milestone_count']}"
        )
        assert_two_decimals(
            final_novice["readiness_index_snapshot"], 0.00, "readiness_index_snapshot"
        )
