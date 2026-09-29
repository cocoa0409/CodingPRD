"""Declared transitions, their side effects, and the states that refuse them."""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_faculty_chair_headers,
    make_partner_account_lead_headers,
    make_provost_headers,
)


@pytest.fixture
def draft_partnership(api):
    """One freshly registered partnership at version 1 with the clock at the default instant."""
    fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
    return fixtures.register_partnership(api)


class TestPartnershipLifecycle:
    def test_registration_lands_in_the_declared_initial_state(self, api, draft_partnership):
        """DRAFT, not UNDER_REVIEW, with the review counter and signature date empty.

        PRD: "A newly registered partnership is `DRAFT` with `version` 1. Its
        `marketing_budget_remaining_cents` is initialised to 0 rather than to the budget: no media
        money is available until the contract is executed. `change_request_count` starts at 0,
        `executed_date` and `wind_down_effective_date` are both null, and every computed ledger
        field — `collected_tuition_cents`, `recognized_revenue_cents`,
        `contract_year_recognized_cents`, `remitted_to_partner_cents`, `holdback_balance_cents`,
        `unrecouped_marketing_spend_cents` — starts at zero."

        Design: Corner/state_machines/partnership_starts_in_the_declared_initial_state
        """
        assert draft_partnership["status"] == "DRAFT"
        assert draft_partnership["change_request_count"] == 0
        assert draft_partnership["executed_date"] is None

    def test_submit_for_review_advances_the_draft_and_recomputes_the_expiry(
        self, api, draft_partnership
    ):
        """The forward edge bumps the version and re-derives the term's end.

        PRD: "The `PartnerAccountLead` submits the draft for review with `SUBMIT_FOR_REVIEW`,
        taking `DRAFT → UNDER_REVIEW`; this is legal only while the partnership is `DRAFT`, only
        when a `FEE_FOR_SERVICE` partnership has a `fee_schedule_monthly_cents` strictly greater
        than 0 and a `REVENUE_SHARE` partnership has it at exactly 0, and it recomputes
        `expiry_date` and increments the partnership's `version`."

        Design: Corner/state_machines/submit_for_review_moves_partnership_draft_to_under_review
        """
        partnership = fixtures.submit_partnership_for_review(api, draft_partnership["id"])

        assert partnership["status"] == "UNDER_REVIEW"
        assert partnership["version"] == 2
        assert partnership["expiry_date"] == "2033-07-31"

    def test_request_changes_returns_the_draft_and_counts_the_round(self, api, draft_partnership):
        """The backward edge of the review cycle records that it was taken.

        PRD: "A `UniversityProvost` reviewing the submission may push it back with
        `REQUEST_CHANGES`, taking `UNDER_REVIEW → DRAFT`, adding one to `change_request_count` and
        incrementing `version`; this loop may repeat any number of times, and
        `change_request_count` is the record of how many times it did."

        Design: Corner/state_machines/request_changes_returns_partnership_to_draft_and_counts_the_round
        """
        ps_id = draft_partnership["id"]
        fixtures.submit_partnership_for_review(api, ps_id)

        response = api.post_contract_action(
            ps_id,
            factories.contract_action_payload(
                "REQUEST_CHANGES", change_request_note="Revise the marketing envelope."
            ),
            headers=make_provost_headers(),
        )
        partnership = validate_success(response, 200)

        assert partnership["status"] == "DRAFT"
        assert partnership["change_request_count"] == 1
        assert partnership["version"] == 3

    def test_execute_is_refused_on_a_draft_that_was_never_submitted(self, api, draft_partnership):
        """EXECUTE is declared only out of UNDER_REVIEW, so the draft is left untouched.

        PRD: "An action that does not match a legal transition out of the partnership's current
        `status` is refused with `ERR_PARTNERSHIP_INVALID_STATE`."
        PRD: "The partnership's `status` permits the requested contract action or child write —
        otherwise `ERR_PARTNERSHIP_INVALID_STATE` (409). Concretely: contract actions must match a
        legal transition of the partnership lifecycle; `Program` creation, counselor
        compensation-plan filing, marketing spend posting and statement creation all require
        `status` to be `EXECUTED`; a terms amendment is accepted only while `status` is `DRAFT`,
        `UNDER_REVIEW` or `EXECUTED`."

        Design: Corner/state_machines/execute_from_draft_is_rejected_as_invalid_state
        """
        ps_id = draft_partnership["id"]
        response = api.post_contract_action(
            ps_id,
            factories.contract_action_payload("EXECUTE", executed_date="2026-08-01"),
            headers=make_provost_headers(),
        )

        validate_error(response, ApiErrorId.PARTNERSHIP_INVALID_STATE.value, 409)

        stored = fixtures.read_partnership(api, ps_id)
        assert stored["status"] == "DRAFT"
        assert stored["version"] == 1

    def test_a_closed_out_contract_accepts_nothing_further(self, api):
        """CLOSED_OUT is terminal, so even the very first forward edge is refused.

        PRD: "Later, the provost may begin the exit with `WIND_DOWN` (`EXECUTED → WIND_DOWN`) or
        finish it with `CLOSE_OUT` (`WIND_DOWN → CLOSED_OUT`); both are described in §3.9.
        `CLOSED_OUT` is terminal."
        PRD: "Teach-out obligations are discharged: a program may be closed only with a
        `CERTIFIED` teach-out plan in place and no remaining active enrollments, and a partnership
        may be closed out only when every one of its programs has settled into `CLOSED`,
        `REJECTED` or `DRAFT` and no settlement statement is still open."

        Design: Corner/state_machines/closed_out_partnership_is_terminal_and_rejects_further_contract_actions
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        fixtures.wind_down_partnership(api, ps_id)
        closed = validate_success(
            api.post_contract_action(
                ps_id,
                factories.contract_action_payload("CLOSE_OUT"),
                headers=make_provost_headers(),
            ),
            200,
        )

        assert closed["status"] == "CLOSED_OUT"
        assert closed["version"] == 5

        response = api.post_contract_action(
            ps_id,
            factories.contract_action_payload("SUBMIT_FOR_REVIEW"),
            headers=make_partner_account_lead_headers(ps_id),
        )
        validate_error(response, ApiErrorId.PARTNERSHIP_INVALID_STATE.value, 409)
        assert fixtures.read_partnership(api, ps_id)["status"] == "CLOSED_OUT"


class TestProgramAndCourseEdges:
    def test_submitting_an_already_submitted_program_is_refused(self, api):
        """SUBMIT is not idempotent and the second attempt changes nothing.

        PRD: "The program's `status` permits the requested lifecycle action or child write —
        otherwise `ERR_PROGRAM_INVALID_STATE` (409). Concretely: lifecycle actions must match a
        legal transition; `Course` creation and `ServiceScopeAssignment` creation require `status`
        to be `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED`; `Lead` creation requires `LAUNCHED`;
        `TeachOutPlan` creation requires `TEACH_OUT`. The check also guards lead advance and lead
        enrollment, both of which require the lead's program to be `LAUNCHED`."
        PRD: "A `UniversityProvost` may return the submission with `REQUEST_REVISION`, taking
        `SUBMITTED → REVISION_REQUESTED` and adding one to the program's `revision_round`; the
        payload may carry a `revision_note`."

        Design: Corner/state_machines/program_submit_twice_second_attempt_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        fixtures.create_approved_course(api, ps_id, pg_id)
        fixtures.assign_service_scope(api, pg_id, "MARKETING")
        fixtures.submit_program(api, ps_id, pg_id)

        response = api.post_program_lifecycle_action(
            pg_id,
            factories.lifecycle_action_payload("SUBMIT"),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.PROGRAM_INVALID_STATE.value, 409)

        stored = fixtures.read_program(api, pg_id)
        assert stored["status"] == "SUBMITTED"
        assert stored["revision_round"] == 0

    def test_approving_a_course_still_in_design_is_refused(self, api):
        """APPROVE is declared only out of FACULTY_REVIEW, so no approver is recorded.

        PRD: "`FACULTY_REVIEW → APPROVED` requires a `faculty_approver_name` supplied on the
        action — the faculty member of record, recorded onto the course and null until then — and
        it requires the content-ownership rule to hold: a course may be approved when its
        `content_owner` is `UNIVERSITY`, or when its `content_owner` is `PARTNER` or `JOINT`
        *and* its `ip_license_grant_back` is true."
        PRD: "The course's `design_status` permits the requested design action, including the
        prerequisite gate on `SUBMIT_FOR_FACULTY_REVIEW` (the course named by
        `prerequisite_course_id` must itself be in `FACULTY_REVIEW` or `APPROVED`) and the
        dependent-course gate on `RETIRE`; and a course amendment is accepted only while
        `design_status` is `NOT_STARTED`, `IN_DESIGN` or `DESIGN_SUSPENDED`. Breaches yield
        `ERR_COURSE_INVALID_DESIGN_STATE` (409)."

        Design: Corner/state_machines/course_approve_from_in_design_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        course = fixtures.add_course(api, ps_id, program["id"])
        fixtures.start_course_design(api, ps_id, course["id"])

        response = api.post_course_design_action(
            course["id"],
            factories.design_action_payload(
                "APPROVE", faculty_approver_name=fixtures.FACULTY_APPROVER_NAME
            ),
            headers=make_faculty_chair_headers(),
        )

        validate_error(response, ApiErrorId.COURSE_INVALID_DESIGN_STATE.value, 409)

        stored = fixtures.read_course(api, course["id"])
        assert stored["design_status"] == "IN_DESIGN"
        assert stored["faculty_approver_name"] is None


class TestEnrollmentAndLeadEdges:
    def test_the_first_payment_activates_the_enrollment_and_syncs_the_cash_ledger(self, api):
        """One request flips the status and lands the money on both ledgers.

        PRD: "The very first `PAYMENT` entry has a further effect: it takes the enrollment
        `ENROLLED → ACTIVE`, because a student who has paid something is academically live."
        PRD: "That transition is a system event rather than a client action, and it fires exactly
        when the enrollment is `ENROLLED` and `collected_cents` is greater than zero after the
        posting."

        Design: Corner/state_machines/first_payment_activates_the_enrollment_and_syncs_the_cash_ledger
        """
        context = fixtures.build_launched_program(api)
        lead = fixtures.create_applied_lead(
            api, context["ps_id"], context["pg_id"], context["co_id"]
        )
        enrollment = fixtures.enroll_lead(api, lead["id"])
        assert enrollment["status"] == "ENROLLED"

        fixtures.set_clock(api, fixtures.CLOCK_SEP_5)
        fixtures.post_tuition_entry(api, enrollment["id"])

        stored = fixtures.read_enrollment(api, enrollment["id"])
        assert stored["status"] == "ACTIVE"
        assert stored["collected_cents"] == 562500

        partnership = fixtures.read_partnership(api, context["ps_id"])
        assert partnership["collected_tuition_cents"] == 562500

        program = fixtures.read_program(api, context["pg_id"])
        assert program["active_enrollment_count"] == 1
        assert program["total_enrollment_count"] == 1

    def test_a_disqualified_lead_cannot_be_revived_by_applying(self, api):
        """DISQUALIFIED is terminal and the pipeline count already reflects it.

        PRD: "`DISQUALIFY` takes a lead in `NEW`, `CONTACTED` or `APPLIED` to `DISQUALIFIED` and
        requires a `disqualification_reason` of `NOT_QUALIFIED`, `UNREACHABLE`,
        `WITHDREW_INTEREST` or `PROGRAM_TEACH_OUT` to be supplied; the same terminal state is also
        reached automatically by the teach-out cascade, which supplies `PROGRAM_TEACH_OUT`
        itself."
        PRD: "Both `ENROLLED` and `DISQUALIFIED` are terminal. Every advance recomputes the
        counselor's `open_pipeline_count`. An action the lead's `status` does not permit is refused
        with `ERR_LEAD_INVALID_STATE`."

        Design: Corner/state_machines/disqualified_lead_is_terminal_so_apply_cannot_revive_it
        """
        context = fixtures.build_launched_program(api)
        ps_id = context["ps_id"]
        lead = fixtures.create_lead(api, ps_id, context["pg_id"], context["co_id"])
        fixtures.contact_lead(api, ps_id, lead["id"], 6)
        fixtures.disqualify_lead(api, ps_id, lead["id"], reason="NOT_QUALIFIED")

        response = api.advance_lead(
            lead["id"],
            factories.advance_payload("APPLY"),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.LEAD_INVALID_STATE.value, 409)

        stored = fixtures.read_lead(api, lead["id"])
        assert stored["status"] == "DISQUALIFIED"
        assert stored["disqualification_reason"] == "NOT_QUALIFIED"
        assert fixtures.read_counselor(api, context["co_id"])["open_pipeline_count"] == 0


class TestStatementStalingCycle:
    def test_a_withdrawal_stales_the_open_statement_and_recalculation_restores_it(self, api):
        """The CALCULATED to STALE to CALCULATED loop, with the approval cleared on the way back.

        PRD: "Every statement of the partnership whose `status` is `CALCULATED` or
        `UNIVERSITY_APPROVED`, and whose fully closed period contains the enrollment's
        `term_start_date`, moves to `STALE` with `requires_recalculation` set to true."
        PRD: "A `UniversityBursar` brings it back with recalculation, taking `STALE →
        CALCULATED`: every computed money field is recomputed against current data under the
        recompute semantics, `requires_recalculation` returns to false, and `approved_by_user_id`
        is cleared to null so that a previously granted approval cannot survive a restatement."

        Design: Corner/state_machines/withdrawal_stales_the_open_statement_and_recalculate_restores_calculated
        """
        context = fixtures.build_paid_enrollment(api, final_clock=fixtures.CLOCK_OCT_1)
        statement = fixtures.cut_statement(api, context["ps_id"])
        assert statement["status"] == "CALCULATED"
        assert statement["recognized_revenue_cents"] == 159198
        assert statement["net_payable_cents"] == 86962

        fixtures.withdraw_enrollment(
            api,
            context["en_id"],
            "2026-09-08",
            withdrawal_reason="Employer sponsorship withdrawn",
        )
        staled = fixtures.read_statement(api, statement["id"])
        assert staled["status"] == "STALE"
        assert staled["requires_recalculation"] is True

        recalculated = fixtures.recalculate_statement(api, statement["id"])

        enrollment = fixtures.read_enrollment(api, context["en_id"])
        assert enrollment["status"] == "WITHDRAWN"
        assert enrollment["refunded_cents"] == 281250

        assert recalculated["status"] == "CALCULATED"
        assert recalculated["requires_recalculation"] is False
        assert recalculated["recognized_revenue_cents"] == 159198
        assert recalculated["net_payable_cents"] == 86962
        assert recalculated["approved_by_user_id"] is None
