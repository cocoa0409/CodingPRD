"""Which error wins when two rules are broken by one request."""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_bursar_headers,
    make_partner_account_lead_headers,
)


class TestProgramStateOutranksEnrollmentCap:
    @pytest.fixture
    def capped_and_suspended_program(self, api):
        """A one-seat program already at capacity and then SUSPENDED, with a second APPLIED lead."""
        context = fixtures.build_launched_program(api, program_overrides={"enrollment_cap": 1})
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

        first = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        fixtures.enroll_lead(api, first["id"])
        second = fixtures.create_applied_lead(
            api,
            ps_id,
            pg_id,
            co_id,
            hours_to_first_contact=9,
            prospect_external_id="P-1002",
            source_channel="PAID_SOCIAL",
        )
        fixtures.suspend_program(api, pg_id)

        context["ld2_id"] = second["id"]
        return context

    def test_conversion_reports_the_program_state_error_not_the_cap_error(
        self, api, capped_and_suspended_program
    ):
        """Both the state gate and the capacity gate are broken; the earlier check reports.

        PRD: "Multiple checks frequently apply to one call, and the order in which they run is
        part of the contract: a request that violates several rules must fail with the error
        belonging to the *earliest* applicable check. The ladder below is evaluated strictly top
        to bottom."
        PRD: "The program's `status` permits the requested lifecycle action or child write —
        otherwise `ERR_PROGRAM_INVALID_STATE` (409). Concretely: lifecycle actions must match a
        legal transition; `Course` creation and `ServiceScopeAssignment` creation require `status`
        to be `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED`; `Lead` creation requires `LAUNCHED`;
        `TeachOutPlan` creation requires `TEACH_OUT`. The check also guards lead advance and lead
        enrollment, both of which require the lead's program to be `LAUNCHED`."
        PRD: "The program's `total_enrollment_count` is strictly below its `enrollment_cap` before
        the enrollment is created, on lead enrollment — otherwise `ERR_ENROLLMENT_CAP_REACHED`
        (409)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_program_state_error_wins_over_enrollment_cap_reached
        """
        context = capped_and_suspended_program
        response = api.enroll_lead(
            context["ld2_id"], factories.enroll_payload(student_external_id="S-2002"), headers=make_bursar_headers()
        )

        validate_error(response, ApiErrorId.PROGRAM_INVALID_STATE.value, 409)

    def test_refused_conversion_leaves_the_cap_counter_and_the_lead_untouched(
        self, api, capped_and_suspended_program
    ):
        """The rejected request writes nothing on either the program or the lead.

        PRD: "The program's `active_enrollment_count` and `total_enrollment_count` each increase
        by one, the program's `blended_cac_cents` is recomputed against the new denominator, and
        the counselor's `open_pipeline_count` is recomputed."

        Design: Difficulty/priority_pair_validation_conflict/suspended_program_state_error_wins_over_enrollment_cap_reached
        """
        context = capped_and_suspended_program
        api.enroll_lead(
            context["ld2_id"], factories.enroll_payload(student_external_id="S-2002"), headers=make_bursar_headers()
        )

        program = fixtures.read_program(api, context["pg_id"])
        assert program["total_enrollment_count"] == 1
        assert program["status"] == "SUSPENDED"
        assert fixtures.read_lead(api, context["ld2_id"])["status"] == "APPLIED"


class TestIncentiveBanOutranksVariableEnvelope:
    @pytest.fixture
    def counselor_without_a_plan(self, api):
        """A freshly onboarded counselor: no plan on file, review still pending."""
        context = fixtures.build_launched_program(api, with_counselor=False)
        counselor = fixtures.create_counselor(api, context["ps_id"])
        context["co_id"] = counselor["id"]
        return context

    def test_prohibited_shape_reports_the_ban_error_not_the_envelope_error(
        self, api, counselor_without_a_plan
    ):
        """A per-enrollment commission at half the base breaks both rules and reports the ban.

        PRD: "A `variable_basis` of `ENROLLMENT_COUNT` or `APPLICATION_COUNT` is always
        prohibited, and a `comp_plan_type` of `PER_ENROLLMENT_COMMISSION` or
        `PER_APPLICATION_BOUNTY` is always prohibited: paying per head enrolled or per
        application filed is exactly what the ban forbids."
        PRD: "The ban screen runs before the envelope check, so a plan that is both prohibited
        in shape and oversized in variable pay reports `ERR_INCENTIVE_COMP_PROHIBITED`."

        Design: Difficulty/priority_pair_validation_conflict/prohibited_incentive_plan_error_wins_over_variable_envelope_breach
        """
        context = counselor_without_a_plan
        payload = factories.compensation_plan_payload(
            comp_plan_type="PER_ENROLLMENT_COMMISSION",
            annual_base_cents=6000000,
            variable_component_cents=3000000,
            variable_basis="ENROLLMENT_COUNT",
        )
        response = api.file_compensation_plan(
            context["co_id"], payload, headers=make_partner_account_lead_headers(context["ps_id"])
        )

        validate_error(response, ApiErrorId.INCENTIVE_COMP_PROHIBITED.value, 422)

    def test_refused_filing_persists_none_of_the_request_only_enum_members(
        self, api, counselor_without_a_plan
    ):
        """The four request-only members are never persisted, so the counselor keeps its blank plan.

        PRD: "So that prohibited shapes are expressible and therefore rejectable,
        `comp_plan_type` accepts two request-only members, `PER_ENROLLMENT_COMMISSION` and
        `PER_APPLICATION_BOUNTY`, and `variable_basis` accepts two request-only members,
        `ENROLLMENT_COUNT` and `APPLICATION_COUNT`; none of the four is ever persisted."
        PRD: "A new counselor has no plan: `comp_plan_type` is `NONE_ON_FILE`, `annual_base_cents`
        and `variable_component_cents` are 0, `variable_basis` is `NONE`, and both state
        dimensions sit at their initial values — `performance_status` at `NOT_RATED` and
        `incentive_eligibility` at `PENDING_COMPLIANCE_REVIEW`."

        Design: Difficulty/priority_pair_validation_conflict/prohibited_incentive_plan_error_wins_over_variable_envelope_breach
        """
        context = counselor_without_a_plan
        payload = factories.compensation_plan_payload(
            comp_plan_type="PER_ENROLLMENT_COMMISSION",
            annual_base_cents=6000000,
            variable_component_cents=3000000,
            variable_basis="ENROLLMENT_COUNT",
        )
        api.file_compensation_plan(
            context["co_id"], payload, headers=make_partner_account_lead_headers(context["ps_id"])
        )

        counselor = fixtures.read_counselor(api, context["co_id"])
        assert counselor["comp_plan_type"] == "NONE_ON_FILE"
        assert counselor["variable_component_cents"] == 0
        assert counselor["variable_basis"] == "NONE"
        assert counselor["incentive_eligibility"] == "PENDING_COMPLIANCE_REVIEW"
