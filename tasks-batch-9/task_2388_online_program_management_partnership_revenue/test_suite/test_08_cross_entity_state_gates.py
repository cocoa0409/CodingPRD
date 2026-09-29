"""Transitions whose blocking state lives on another entity entirely."""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_partner_account_lead_headers,
)


class TestLeadApplyIsGatedOnItsProgram:
    @pytest.fixture
    def contacted_lead_under_suspended_program(self, api):
        """Lead P-1001 sitting in CONTACTED while its program has been SUSPENDED."""
        context = fixtures.build_launched_program(api)
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

        lead = fixtures.create_lead(api, ps_id, pg_id, co_id)
        fixtures.contact_lead(api, ps_id, lead["id"], 6)
        fixtures.suspend_program(api, pg_id)

        context["ld_id"] = lead["id"]
        return context

    def test_apply_is_refused_while_the_program_is_suspended(
        self, api, contacted_lead_under_suspended_program
    ):
        """The lead's own transition is legal, but its program is not LAUNCHED.

        PRD: "`APPLY` takes `CONTACTED → APPLIED`, requires the lead's program to still be
        `LAUNCHED`, and stamps `qualified_at` with the logical clock instant."
        PRD: "The check also guards lead advance and lead enrollment, both of which require the
        lead's program to be `LAUNCHED`."

        Design: Difficulty/cross_entity_state_dependency/lead_apply_is_gated_on_the_program_being_launched
        """
        context = contacted_lead_under_suspended_program
        response = api.advance_lead(
            context["ld_id"],
            factories.advance_payload("APPLY"),
            headers=make_partner_account_lead_headers(context["ps_id"]),
        )

        validate_error(response, ApiErrorId.PROGRAM_INVALID_STATE.value, 409)
        assert fixtures.read_lead(api, context["ld_id"])["status"] == "CONTACTED"

    def test_resuming_the_program_lets_the_identical_request_through(
        self, api, contacted_lead_under_suspended_program
    ):
        """Nothing about the lead changed; restoring the program's state is enough.

        PRD: "`RESUME` takes `SUSPENDED → LAUNCHED`, requires the parent partnership to still be
        `EXECUTED` and the logical clock date to be no later than the partnership's `expiry_date`,
        and reopens lead creation."
        PRD: "Every advance recomputes the counselor's `open_pipeline_count`."

        Design: Difficulty/cross_entity_state_dependency/lead_apply_is_gated_on_the_program_being_launched
        """
        context = contacted_lead_under_suspended_program
        api.advance_lead(
            context["ld_id"],
            factories.advance_payload("APPLY"),
            headers=make_partner_account_lead_headers(context["ps_id"]),
        )

        resumed = fixtures.resume_program(api, context["pg_id"])
        assert resumed["status"] == "LAUNCHED"

        applied = fixtures.apply_lead(api, context["ps_id"], context["ld_id"])
        assert applied["status"] == "APPLIED"
        assert fixtures.read_counselor(api, context["co_id"])["open_pipeline_count"] == 1


class TestCourseReviewIsGatedOnItsPrerequisite:
    @pytest.fixture
    def dependent_course_in_design(self, api):
        """MBA-502 in IN_DESIGN behind MBA-501, which has not started design at all."""
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]

        prerequisite = fixtures.add_course(api, ps_id, pg_id)
        dependent = fixtures.add_course(
            api,
            ps_id,
            pg_id,
            course_code="MBA-502",
            title="Advanced Analytics",
            content_owner="PARTNER",
            design_cost_cents=900000,
            required_for_launch=False,
            prerequisite_course_id=prerequisite["id"],
            ip_license_grant_back=True,
        )
        fixtures.start_course_design(api, ps_id, dependent["id"])

        return {
            "ps_id": ps_id,
            "pg_id": pg_id,
            "c1_id": prerequisite["id"],
            "c2_id": dependent["id"],
        }

    def test_review_is_refused_while_the_prerequisite_has_not_started(
        self, api, dependent_course_in_design
    ):
        """A dependent course may not be reviewed ahead of the material it builds on.

        PRD: "The partner then hands the content to faculty with `SUBMIT_FOR_FACULTY_REVIEW`,
        taking `IN_DESIGN → FACULTY_REVIEW`; this requires either that the course has no
        `prerequisite_course_id`, or that the course its `prerequisite_course_id` names has itself
        reached `FACULTY_REVIEW` or `APPROVED`, so content cannot be reviewed ahead of the
        material it builds on."
        PRD: "The course's `design_status` permits the requested design action, including the
        prerequisite gate on `SUBMIT_FOR_FACULTY_REVIEW` (the course named by
        `prerequisite_course_id` must itself be in `FACULTY_REVIEW` or `APPROVED`) and the
        dependent-course gate on `RETIRE`; and a course amendment is accepted only while
        `design_status` is `NOT_STARTED`, `IN_DESIGN` or `DESIGN_SUSPENDED`. Breaches yield
        `ERR_COURSE_INVALID_DESIGN_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/course_faculty_review_is_gated_on_its_prerequisite_course_design_state
        """
        context = dependent_course_in_design
        response = api.post_course_design_action(
            context["c2_id"],
            factories.design_action_payload("SUBMIT_FOR_FACULTY_REVIEW"),
            headers=make_partner_account_lead_headers(context["ps_id"]),
        )

        validate_error(response, ApiErrorId.COURSE_INVALID_DESIGN_STATE.value, 409)
        assert fixtures.read_course(api, context["c2_id"])["design_status"] == "IN_DESIGN"
        assert fixtures.read_course(api, context["c1_id"])["design_status"] == "NOT_STARTED"

    def test_the_same_request_succeeds_once_the_prerequisite_reaches_review(
        self, api, dependent_course_in_design
    ):
        """Moving the prerequisite into FACULTY_REVIEW opens the gate for its dependent.

        PRD: "An optional `prerequisite_course_id` declares a self-referential prerequisite edge
        to another course of the same program, and is null when the course has no prerequisite."
        PRD: "The partner starts work with `START_DESIGN`, taking `NOT_STARTED → IN_DESIGN`, which
        is legal only while the parent program is `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`,
        `APPROVED` or `LAUNCHED`."

        Design: Difficulty/cross_entity_state_dependency/course_faculty_review_is_gated_on_its_prerequisite_course_design_state
        """
        context = dependent_course_in_design
        api.post_course_design_action(
            context["c2_id"],
            factories.design_action_payload("SUBMIT_FOR_FACULTY_REVIEW"),
            headers=make_partner_account_lead_headers(context["ps_id"]),
        )

        fixtures.start_course_design(api, context["ps_id"], context["c1_id"])
        fixtures.submit_course_for_faculty_review(api, context["ps_id"], context["c1_id"])
        dependent = fixtures.submit_course_for_faculty_review(
            api, context["ps_id"], context["c2_id"]
        )

        assert dependent["design_status"] == "FACULTY_REVIEW"
        assert dependent["prerequisite_course_id"] == context["c1_id"]
        assert fixtures.read_course(api, context["c1_id"])["design_status"] == "FACULTY_REVIEW"
