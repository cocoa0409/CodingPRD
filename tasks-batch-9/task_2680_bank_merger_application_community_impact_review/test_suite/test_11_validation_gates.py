"""Validation gates: the filing rating checks, conditional body rules and aggregate emptiness."""
import pytest

from test_helpers import ApiErrorId, TEST_USERS, api_client, make_filer_headers
from test_helpers.assertions import assert_benefits_plan, assert_public_comment, assert_same_instant
from test_helpers.factories import merger_application_payload
from test_helpers.fixtures import (
    accept_application,
    application_under_review,
    auto_comment_period,
    close_comment_period,
    create_acquirer,
    create_regulatory_schedule,
    create_target,
    file_comment,
    granite_market_world,
    propose_plan,
    read_analysis,
    read_application,
    read_comment,
    read_plan,
    reset_clock_to_epoch,
    respond_to_comment,
    set_clock,
    submit_application,
)
from test_helpers.test_users import SECOND_COMMENTER_USER_ID
from prd_bench_local_runner.testing import validate_error, validate_success

ANALYST = TEST_USERS["analyst_headers"]


class TestFilingRatingGates:
    """The Community Reinvestment record and the management rating gate the filing."""

    def test_01_a_needs_to_improve_cra_record_blocks_the_filing(self):
        """PRD §3.4: "The acquirer's `latest_cra_rating` must be `OUTSTANDING` or `SATISFACTORY`,
        and a rating of `NEEDS_TO_IMPROVE` or `SUBSTANTIAL_NONCOMPLIANCE` yields
        `ERR_CRA_RATING_INSUFFICIENT`."
        PRD §2.5: "The acquirer's Community Reinvestment Act record is adequate at submission —
        `ERR_CRA_RATING_INSUFFICIENT`."
        PRD §2.5: "A current regulatory-basis pro forma schedule exists at submission —
        `ERR_PRO_FORMA_SCHEDULE_MISSING`."

        Design: Corner/validations/needs_to_improve_cra_record_blocks_submission
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer(latest_cra_rating="NEEDS_TO_IMPROVE")
        target = create_target()
        payload = merger_application_payload(acquirer["id"], target["id"])
        application = validate_success(
            api_client.create_merger_application(payload, make_filer_headers(acquirer["id"])), 201
        )

        response = api_client.submit_merger_application(
            application["id"], make_filer_headers(acquirer["id"])
        )

        validate_error(response, ApiErrorId.ERR_CRA_RATING_INSUFFICIENT.value, 422)
        assert read_application(application["id"], acquirer["id"])["filing_status"] == "DRAFT"

    def test_02_a_conditional_management_rating_still_permits_the_filing(self):
        """PRD §3.2: "The composite is then banded into `management_rating`: a composite of 70.00 or
        more is `SATISFACTORY`, a composite of at least 55.00 but below 70.00 is `CONDITIONAL`, and
        anything below 55.00 is `UNSATISFACTORY`."
        PRD §3.4: "The application's `management_rating` must be `SATISFACTORY` or `CONDITIONAL`; a
        rating of `UNSATISFACTORY` yields `ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY`."

        Design: Corner/validations/conditional_management_rating_still_permits_submission
        """
        reset_clock_to_epoch()
        acquirer = create_acquirer()
        target = create_target()
        payload = merger_application_payload(
            acquirer["id"], target["id"], officer_experience_score=60, risk_management_score=60,
            compliance_history_score=60, integration_readiness_score=60,
        )
        application = validate_success(
            api_client.create_merger_application(payload, make_filer_headers(acquirer["id"])), 201
        )
        assert application["management_composite_score"] == pytest.approx(60.00, abs=0.005), (
            f"Expected 60.00, got {application['management_composite_score']}"
        )
        assert application["management_rating"] == "CONDITIONAL"
        create_regulatory_schedule(application["id"], acquirer["id"])

        submitted = submit_application(application["id"], acquirer["id"])

        assert submitted["filing_status"] == "SUBMITTED", (
            "the gate rejects only UNSATISFACTORY, so a CONDITIONAL rating passes"
        )
        assert submitted["management_rating"] == "CONDITIONAL"


class TestConditionalResponseBody:
    """A response body is demanded by the disposition, not by the endpoint."""

    def test_03_only_the_responded_disposition_requires_a_response_body(self):
        """PRD §3.7: "A `disposition` of `ACKNOWLEDGED` drives `RECEIVED → ACKNOWLEDGED` and stamps
        `responded_at`, but an acknowledgement does **not** resolve the protest — an `ACKNOWLEDGED`
        comment still counts as unresolved."
        PRD §3.7: "A `disposition` of `RESPONDED` drives either `RECEIVED → RESPONDED` or
        `ACKNOWLEDGED → RESPONDED`, requires a `response_body` that is present and non-blank on pain
        of `ERR_RESPONSE_BODY_REQUIRED`, and records `response_body` and `responded_at`."

        Design: Corner/validations/response_body_is_required_only_for_the_responded_disposition
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        set_clock("2026-08-10T00:00:00Z")
        comment = file_comment(world["period"]["id"], commenter_user_id=SECOND_COMMENTER_USER_ID,
                               commenter_name="Rowan Delgado", commenter_type="INDIVIDUAL",
                               stance="OPPOSE", substantive=False,
                               body="Branch hours have already been cut.")

        acknowledged = respond_to_comment(comment["id"], acquirer_id, disposition="ACKNOWLEDGED")

        assert_public_comment(acknowledged)
        assert acknowledged["status"] == "ACKNOWLEDGED", (
            "an acknowledgement needs no response body at all"
        )
        assert_same_instant(acknowledged["responded_at"], "2026-08-10T00:00:00Z", "responded_at")

        response = api_client.respond_to_public_comment(
            comment["id"], {"disposition": "RESPONDED"}, make_filer_headers(acquirer_id)
        )

        validate_error(response, ApiErrorId.ERR_RESPONSE_BODY_REQUIRED.value, 422)
        stored = read_comment(comment["id"])
        assert stored["status"] == "ACKNOWLEDGED", "the refused full response changes nothing"
        assert stored["response_body"] is None

    def test_04_the_same_responded_disposition_succeeds_with_a_body(self):
        """PRD §3.7: "A `disposition` of `RESPONDED` drives either `RECEIVED → RESPONDED` or
        `ACKNOWLEDGED → RESPONDED`, requires a `response_body` that is present and non-blank on pain
        of `ERR_RESPONSE_BODY_REQUIRED`, and records `response_body` and `responded_at`."

        Design: Corner/validations/response_body_is_required_only_for_the_responded_disposition
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        set_clock("2026-08-10T00:00:00Z")
        comment = file_comment(world["period"]["id"], commenter_user_id=SECOND_COMMENTER_USER_ID,
                               commenter_name="Rowan Delgado", commenter_type="INDIVIDUAL",
                               stance="OPPOSE", substantive=False,
                               body="Branch hours have already been cut.")
        respond_to_comment(comment["id"], acquirer_id, disposition="ACKNOWLEDGED")

        answered = respond_to_comment(
            comment["id"], acquirer_id, disposition="RESPONDED",
            response_body="Lobby hours at the Kestrel offices are restored to the prior schedule.",
        )

        assert answered["status"] == "RESPONDED", (
            "the rule is conditional on the disposition, not on the endpoint"
        )
        assert answered["response_body"] == \
            "Lobby hours at the Kestrel offices are restored to the prior schedule."


class TestAggregateAndRollupGates:
    """An empty collective and an unsettled posture each refuse the operation."""

    def test_05_executing_a_plan_with_no_line_items_is_refused(self):
        """PRD §3.9: "Execution is the filer's commitment and drives `PROPOSED → EXECUTED`. The
        acting `X-User-ID` must equal the application's `acquirer_id`; the plan must carry at least
        one commitment line item with a `total_committed_usd` greater than 0, an empty or unfunded
        plan being refused with `ERR_EMPTY_BENEFITS_PLAN`; and the application's `filing_status` must
        be `UNDER_REVIEW`, `RECOMMENDED` or `DECIDED`."
        PRD §3.9: "A new plan is created with `status` `PROPOSED`, every monetary aggregate at 0 —
        `total_committed_usd`, `annual_target_total_usd`, `quarterly_target_total_usd`,
        `credited_to_date_usd` and `remaining_commitment_usd` — with `compliance_status`
        `COMPLIANT`, `consecutive_deficient_periods` at 0 and `filed_report_count` at 0."

        Design: Corner/validations/executing_a_plan_with_no_line_items_is_rejected
        """
        world = application_under_review()
        acquirer_id = world["acquirer"]["id"]
        plan = propose_plan(world["application"]["id"], acquirer_id, term_years=3)

        response = api_client.execute_benefits_plan(plan["id"], make_filer_headers(acquirer_id))

        validate_error(response, ApiErrorId.ERR_EMPTY_BENEFITS_PLAN.value, 422)
        stored = read_plan(plan["id"])
        assert_benefits_plan(stored)
        assert stored["status"] == "PROPOSED", "the refused execution leaves the plan proposed"
        assert stored["total_committed_usd"] == 0
        assert stored["quarterly_target_total_usd"] == 0

    def test_06_a_blocked_posture_refuses_the_recommendation(self):
        """PRD §3.5: "Otherwise, if any analysis has `screen_result` `PRESUMPTIVE_VIOLATION` and
        `mitigation_satisfied` false, the posture is `BLOCKED`."
        PRD §3.10: "Beyond those, the application's `management_rating` must not be
        `UNSATISFACTORY`, or the recommendation is refused with
        `ERR_MANAGEMENT_ASSESSMENT_UNSATISFACTORY`, and its `competitive_posture` must not be
        `BLOCKED`, or it is refused with `ERR_COMPETITIVE_POSTURE_BLOCKED`."
        PRD §2.5: "Every overlapping market has been analyzed before a recommendation —
        `ERR_MARKET_ANALYSIS_MISSING`."

        Design: Corner/validations/posture_rollup_must_be_settled_before_the_recommendation_gate_runs
        """
        world = granite_market_world()
        application_id = world["application"]["id"]
        acquirer_id = world["acquirer"]["id"]
        create_regulatory_schedule(application_id, acquirer_id)
        submit_application(application_id, acquirer_id)
        accept_application(application_id)
        period = auto_comment_period(application_id)
        close_comment_period(period["id"])
        set_clock("2026-09-15T00:00:00Z")

        response = api_client.recommend_merger_application(
            application_id, {"recommendation": "APPROVE"}, ANALYST
        )

        validate_error(response, ApiErrorId.ERR_COMPETITIVE_POSTURE_BLOCKED.value, 422)
        analysis = read_analysis(world["analysis"]["id"])
        assert analysis["screen_result"] == "PRESUMPTIVE_VIOLATION"
        assert analysis["mitigation_satisfied"] is False
        application = read_application(application_id, acquirer_id)
        assert application["competitive_posture"] == "BLOCKED", (
            "the roll-up ran on analysis creation; the gate only reads its result"
        )
        assert application["filing_status"] == "UNDER_REVIEW", (
            "the analysis exists, so the market-analysis check is not what refused the call"
        )
