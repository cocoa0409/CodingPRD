"""Declared error identifiers: each one reached on its own trigger and told apart from its neighbours."""

import pytest
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_AUDITOR_USER_ID,
    SECOND_COMPLIANCE_AUDITOR_USER_ID,
    factories,
    fixtures,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_faculty_chair_headers,
    make_partner_account_lead_headers,
    make_provost_headers,
)

WEAK_PROGRAM = {
    "program_name": "MA Regional Studies Online",
    "cip_code": "05.0100",
    "delivery_modality": "ASYNCHRONOUS",
    "credential_level": "MASTERS",
    "tuition_per_credit_cents": 40000,
    "credits_to_complete": 30,
    "enrollment_cap": 25,
    "projected_annual_enrollments": 300,
    "competitor_program_count": 24,
    "regional_wage_premium_pct": 8.9,
    "employer_partner_count": 1,
    "prior_year_inquiry_volume": 400,
}


class TestChildEntityLookups:
    def test_each_child_aggregate_reports_its_own_not_found_identifier(self, api):
        """Seven unknown-id probes return seven distinct error identifiers, all at 404.

        PRD: "The `Course` named by the path identifier exists — checked on the single-course read,
        the course amendment and the course design actions — otherwise `ERR_COURSE_NOT_FOUND`
        (404)."
        PRD: "When `prerequisite_course_id` is supplied, it names an existing `Course` belonging to
        the same `Program` — checked on course creation and course amendment — otherwise
        `ERR_PREREQUISITE_COURSE_NOT_FOUND` (404)."
        PRD: "The `EnrollmentCounselor` named by the path identifier or by a `counselor_id` in the
        body exists — checked on every counselor-scoped endpoint and on lead creation — otherwise
        `ERR_COUNSELOR_NOT_FOUND` (404)."
        PRD: "The `Lead` named by the path identifier exists — checked on the single-lead read, the
        funnel advance and the enroll conversion — otherwise `ERR_LEAD_NOT_FOUND` (404)."
        PRD: "The `Enrollment` named by the path identifier exists — checked on every
        enrollment-scoped endpoint — otherwise `ERR_ENROLLMENT_NOT_FOUND` (404)."
        PRD: "The `RemittanceStatement` named by the path identifier exists — checked on the
        single-statement read and the statement actions — otherwise `ERR_STATEMENT_NOT_FOUND`
        (404)."
        PRD: "The `TeachOutPlan` named by the path identifier exists — checked on certification —
        otherwise `ERR_TEACH_OUT_PLAN_NOT_FOUND` (404)."

        Design: Corner/errors/every_child_entity_lookup_with_an_unknown_id_is_not_found
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        fixtures.add_course(api, ps_id, pg_id)
        partner_headers = make_partner_account_lead_headers(ps_id)

        validate_error(
            api.get_course(NON_EXISTENT_UUID, headers=make_faculty_chair_headers()),
            ApiErrorId.COURSE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_course(
                pg_id,
                factories.course_payload(
                    course_code="MBA-503",
                    title="Orphan Prerequisite",
                    design_cost_cents=500000,
                    prerequisite_course_id=NON_EXISTENT_UUID,
                ),
                headers=partner_headers,
            ),
            ApiErrorId.PREREQUISITE_COURSE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_lead(
                factories.lead_payload(
                    pg_id,
                    NON_EXISTENT_UUID,
                    source_channel="ORGANIC",
                    prospect_external_id="P-8001",
                ),
                headers=partner_headers,
            ),
            ApiErrorId.COUNSELOR_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_lead(NON_EXISTENT_UUID, headers=partner_headers),
            ApiErrorId.LEAD_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_enrollment(NON_EXISTENT_UUID, headers=make_bursar_headers()),
            ApiErrorId.ENROLLMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_remittance_statement(NON_EXISTENT_UUID, headers=make_bursar_headers()),
            ApiErrorId.STATEMENT_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.certify_teach_out_plan(
                NON_EXISTENT_UUID,
                factories.certify_payload(),
                headers=make_compliance_auditor_headers(),
            ),
            ApiErrorId.TEACH_OUT_PLAN_NOT_FOUND.value,
            404,
        )


class TestTerminalStateGuards:
    def test_a_withdrawn_enrollment_accepts_no_further_academic_action(self, api):
        """RECORD_PROGRESS against a withdrawn student is refused and the milestone stays at 0.

        PRD: "Both `COMPLETED` and `WITHDRAWN` are terminal enrollment states."
        PRD: "The enrollment's `status` permits the requested academic action or tuition posting; a
        tuition ledger entry may only be posted while the enrollment is `ENROLLED` or `ACTIVE`.
        Breaches yield `ERR_ENROLLMENT_INVALID_STATE` (409)."

        Design: Corner/errors/withdrawn_enrollment_rejects_further_academic_actions
        """
        context = fixtures.build_paid_enrollment(api)
        fixtures.set_clock(api, fixtures.CLOCK_SEP_8)
        withdrawn = fixtures.withdraw_enrollment(
            api,
            context["en_id"],
            "2026-09-08",
            withdrawal_reason="Employer sponsorship withdrawn",
        )
        assert withdrawn["status"] == "WITHDRAWN"

        response = api.post_academic_action(
            context["en_id"],
            factories.academic_action_payload("RECORD_PROGRESS", credits_completed=6),
            headers=make_provost_headers(),
        )

        validate_error(response, ApiErrorId.ENROLLMENT_INVALID_STATE.value, 409)

        stored = fixtures.read_enrollment(api, context["en_id"])
        assert stored["status"] == "WITHDRAWN"
        assert stored["credits_completed"] == 0

    def test_a_second_certification_of_the_same_plan_is_refused(self, api):
        """Certification is not idempotent, so the first auditor's buckets stand.

        PRD: "The teach-out plan's `status` is `DRAFT` when certification is attempted — otherwise
        `ERR_TEACH_OUT_PLAN_INVALID_STATE` (409)."
        PRD: "**Certification and the liability waterfall.** Certification is the
        `ComplianceAuditor`'s act, taking `DRAFT → CERTIFIED`."

        Design: Corner/errors/certifying_an_already_certified_teach_out_plan_is_rejected
        """
        context = fixtures.build_paid_enrollment(api, credits_completed=3)
        pg_id = context["pg_id"]
        fixtures.begin_teach_out(
            api, pg_id, teach_out_reason="Program discontinued after portfolio review"
        )
        plan = fixtures.draft_teach_out_plan(
            api,
            pg_id,
            teach_out_end_date="2027-01-15",
            student_notification_date="2026-09-05",
            partner_obligation_note="Partner funds capped share of teach-out delivery.",
        )
        certified = fixtures.certify_teach_out_plan(
            api, plan["id"], certification_note="Notice period and asset inventory verified."
        )
        assert certified["status"] == "CERTIFIED"

        response = api.certify_teach_out_plan(
            plan["id"],
            factories.certify_payload(certification_note="Duplicate certification attempt."),
            headers=make_compliance_auditor_headers(SECOND_COMPLIANCE_AUDITOR_USER_ID),
        )

        validate_error(response, ApiErrorId.TEACH_OUT_PLAN_INVALID_STATE.value, 409)

        rows, _ = validate_paginated(
            api.list_teach_out_plans(pg_id, headers=make_provost_headers())
        )
        stored = [row for row in rows if row["id"] == plan["id"]][0]
        assert stored["status"] == "CERTIFIED"
        assert stored["certified_by_user_id"] == COMPLIANCE_AUDITOR_USER_ID


class TestSettlementAndReviewStateGuards:
    def test_remitting_before_approval_trips_the_state_guard(self, api):
        """The positive net payable is never consulted: the edge itself does not exist yet.

        PRD: "The statement's `status` permits the requested action, and `requires_recalculation` is
        false when the action is `APPROVE` — otherwise `ERR_STATEMENT_INVALID_STATE` (409)."
        PRD: "From the join there is one exit. A `UniversityBursar` remits with a mandatory
        `remittance_reference`, taking `UNIVERSITY_APPROVED → REMITTED`, which requires
        `net_payable_cents` to be strictly greater than zero — remitting nothing, or a negative
        balance, is refused with `ERR_NOTHING_TO_REMIT`."

        Design: Corner/errors/remit_before_university_approval_is_rejected
        """
        context = fixtures.build_september_statement(api, credits_completed=None)
        statement = context["statement"]
        assert statement["status"] == "CALCULATED"
        assert statement["net_payable_cents"] == 73919

        response = api.post_statement_action(
            statement["id"],
            factories.statement_action_payload("REMIT", remittance_reference="ACH-2026-09"),
            headers=make_bursar_headers(),
        )

        validate_error(response, ApiErrorId.STATEMENT_INVALID_STATE.value, 409)

        stored = fixtures.read_statement(api, statement["id"])
        assert stored["status"] == "CALCULATED"
        assert stored["remitted_at"] is None
        assert fixtures.read_partnership(api, context["ps_id"])["remitted_to_partner_cents"] == 0

    def test_approving_an_already_eligible_counselor_trips_the_review_state_guard(self, api):
        """A different auditor clears segregation of duties and is then stopped by the state.

        PRD: "A `decision` of `APPROVE` takes `PENDING_COMPLIANCE_REVIEW → ELIGIBLE`, and requires
        the counselor's `comp_plan_type` not to be `NONE_ON_FILE` — there is nothing to approve
        before a plan exists — and, when a prior review exists, requires the acting `X-User-ID` to
        differ from the recorded `last_review_user_id`."
        PRD: "The counselor's `incentive_eligibility` permits the requested compliance decision —
        otherwise `ERR_COUNSELOR_INVALID_REVIEW_STATE` (409)."

        Design: Corner/errors/approving_an_already_eligible_counselor_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        counselor = fixtures.create_eligible_counselor(api, partnership["id"])
        assert counselor["incentive_eligibility"] == "ELIGIBLE"

        response = api.post_compliance_review(
            counselor["id"],
            factories.compliance_review_payload(
                "APPROVE", reviewer_note="Independent second approval."
            ),
            headers=make_compliance_auditor_headers(SECOND_COMPLIANCE_AUDITOR_USER_ID),
        )

        validate_error(response, ApiErrorId.COUNSELOR_INVALID_REVIEW_STATE.value, 409)

        stored = fixtures.read_counselor(api, counselor["id"])
        assert stored["incentive_eligibility"] == "ELIGIBLE"
        assert stored["last_review_user_id"] == COMPLIANCE_AUDITOR_USER_ID

    def test_a_prohibited_plan_quarantines_the_counselor_from_the_funnel(self, api):
        """A rejected plan blocks lead creation even under a healthy LAUNCHED program.

        PRD: "A `decision` of `REJECT_PLAN` takes `PENDING_COMPLIANCE_REVIEW →
        PROHIBITED_PLAN_ON_FILE`, after which no lead may be created naming that counselor."
        PRD: "The counselor involved is not in `PROHIBITED_PLAN_ON_FILE`, on lead creation and on
        lead enrollment — otherwise `ERR_COUNSELOR_INCENTIVE_SUSPENDED` (409)."

        Design: Corner/errors/lead_creation_for_a_prohibited_plan_counselor_is_rejected
        """
        context = fixtures.build_launched_program(api, with_counselor=False)
        ps_id = context["ps_id"]
        counselor = fixtures.create_counselor(api, ps_id)
        fixtures.file_compensation_plan(api, ps_id, counselor["id"])
        rejected = fixtures.review_counselor(
            api,
            counselor["id"],
            "REJECT_PLAN",
            reviewer_note="Variable component tied to enrollment volume in practice.",
        )
        assert rejected["incentive_eligibility"] == "PROHIBITED_PLAN_ON_FILE"

        response = api.create_lead(
            factories.lead_payload(
                context["pg_id"], counselor["id"], prospect_external_id="P-7001"
            ),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.COUNSELOR_INCENTIVE_SUSPENDED.value, 409)

        stored = fixtures.read_counselor(api, counselor["id"])
        assert stored["incentive_eligibility"] == "PROHIBITED_PLAN_ON_FILE"
        assert stored["open_pipeline_count"] == 0


class TestProgramReadinessGates:
    def test_a_courseless_program_cannot_be_submitted(self, api):
        """A passing screening score does not excuse an empty curriculum.

        PRD: "A program starts `DRAFT` and reaches `SUBMITTED` through the partner's `SUBMIT`
        action, which requires the program to be `DRAFT`, the parent partnership to be `EXECUTED`,
        at least one course to exist for the program — otherwise `ERR_NO_COURSES_DEFINED` — and the
        recomputed `demand_score_screening` to be at least 45.00."
        PRD: "The program has at least one course, on the program lifecycle action `SUBMIT` —
        otherwise `ERR_NO_COURSES_DEFINED` (409)."

        Design: Corner/errors/program_submit_with_no_courses_defined_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)

        response = api.post_program_lifecycle_action(
            program["id"],
            factories.lifecycle_action_payload("SUBMIT"),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.NO_COURSES_DEFINED.value, 409)

        stored = fixtures.read_program(api, program["id"])
        assert stored["status"] == "DRAFT"
        assert stored["demand_score_screening"] == pytest.approx(74.50, abs=0.005)

    def test_an_unassigned_required_domain_blocks_approval_first(self, api):
        """The scope gate surfaces ahead of the design gate the program would have passed.

        PRD: "It requires the program to be `SUBMITTED`; every domain named in
        `required_service_domains` to have a service-scope assignment, failing which the request is
        refused with `ERR_SERVICE_SCOPE_INCOMPLETE`; every course of the program whose
        `required_for_launch` is true to have reached `APPROVED` design status, failing which the
        refusal is `ERR_COURSE_DESIGN_INCOMPLETE`; and the freshly recomputed
        `demand_score_confirmed` to be at least 62.00, failing which the refusal is
        `ERR_DEMAND_SCORE_BELOW_APPROVAL_THRESHOLD`."
        PRD: "These checks are evaluated in the order in which §2.5 lists them, so an incomplete
        service-scope split surfaces before an unfinished course design, which in turn surfaces
        before a short confirmed score."

        Design: Corner/errors/program_approve_without_the_required_scope_assignment_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        course = fixtures.create_approved_course(api, ps_id, pg_id)
        assert course["design_status"] == "APPROVED"
        fixtures.submit_program(api, ps_id, pg_id)

        response = api.post_program_lifecycle_action(
            pg_id, factories.lifecycle_action_payload("APPROVE"), headers=make_provost_headers()
        )

        validate_error(response, ApiErrorId.SERVICE_SCOPE_INCOMPLETE.value, 409)

        assert fixtures.read_program(api, pg_id)["status"] == "SUBMITTED"

    def test_an_unapproved_launch_required_course_blocks_approval_next(self, api):
        """With the scope split complete, the design gate becomes the observable one.

        PRD: "Every launch-required course of the program is `APPROVED`, on the program lifecycle
        action `APPROVE` — otherwise `ERR_COURSE_DESIGN_INCOMPLETE` (409)."
        PRD: "`required_for_launch` defaults to true and marks the course as one that must reach
        approved design status before the program may launch"

        Design: Corner/errors/program_approve_with_an_unapproved_required_course_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        course = fixtures.add_course(api, ps_id, pg_id)
        fixtures.start_course_design(api, ps_id, course["id"])
        fixtures.assign_service_scope(api, pg_id, "MARKETING")
        fixtures.submit_program(api, ps_id, pg_id)

        response = api.post_program_lifecycle_action(
            pg_id, factories.lifecycle_action_payload("APPROVE"), headers=make_provost_headers()
        )

        validate_error(response, ApiErrorId.COURSE_DESIGN_INCOMPLETE.value, 409)

        assert fixtures.read_program(api, pg_id)["status"] == "SUBMITTED"
        assert fixtures.read_course(api, course["id"])["design_status"] == "IN_DESIGN"

    def test_a_weak_proposal_misses_the_screening_threshold_by_a_tenth(self, api):
        """44.90 against a 45.00 floor, with the courseless gate already satisfied.

        PRD: "A score below that threshold is refused with
        `ERR_DEMAND_SCORE_BELOW_SUBMIT_THRESHOLD`; the comparison is inclusive, so exactly 45.00
        passes."
        PRD: "The **screening** variant takes the effective projection to be
        `projected_annual_enrollments` itself, accepting the partner's unverified number at face
        value, and writes its result to `demand_score_screening`."

        Design: Corner/errors/program_submit_below_the_screening_threshold_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id, **WEAK_PROGRAM)
        pg_id = program["id"]
        fixtures.add_course(
            api,
            ps_id,
            pg_id,
            course_code="MA-501",
            title="Regional Economies",
            design_cost_cents=400000,
            required_for_launch=False,
        )

        response = api.post_program_lifecycle_action(
            pg_id,
            factories.lifecycle_action_payload("SUBMIT"),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.DEMAND_SCORE_BELOW_SUBMIT_THRESHOLD.value, 422)

        stored = fixtures.read_program(api, pg_id)
        assert stored["demand_score_screening"] == pytest.approx(44.90, abs=0.005)
        assert stored["status"] == "DRAFT"
