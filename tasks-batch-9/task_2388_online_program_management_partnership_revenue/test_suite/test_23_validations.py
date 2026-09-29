"""The validation ladder: the guards that refuse a request and leave the world unchanged."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    ApiErrorId,
    BURSAR_USER_ID,
    COMPLIANCE_AUDITOR_USER_ID,
    factories,
    fixtures,
    make_bursar_headers,
    make_compliance_auditor_headers,
    make_faculty_chair_headers,
    make_headers,
    make_partner_account_lead_headers,
    make_platform_admin_headers,
    make_provost_headers,
)


class TestAuthenticationLadder:
    def test_a_request_without_the_user_identity_header_is_refused(self, api):
        """Priority 1 fires before any lookup, so an existing partnership still reads as 401.

        PRD: "Every request must carry two headers: `X-User-ID`, naming the acting principal, and
        `X-User-Role`, naming the capacity in which it acts. If either header is absent or empty,
        the request fails with `ERR_MISSING_AUTH_HEADERS`."
        PRD: "Both `X-User-ID` and `X-User-Role` are present and non-empty, on every endpoint —
        otherwise `ERR_MISSING_AUTH_HEADERS` (401)."

        Design: Corner/validations/request_missing_x_user_id_header_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.register_partnership(api)

        headers = {
            key: value for key, value in make_provost_headers().items() if key != "X-User-ID"
        }
        response = api.get_partnership(partnership["id"], headers=headers)

        validate_error(response, ApiErrorId.MISSING_AUTH_HEADERS.value, 401)

    def test_a_request_naming_an_undeclared_role_is_refused(self, api):
        """An unrecognised role fails at priority 2, ahead of the permission check.

        PRD: "Six roles exist and no others are accepted; a value outside this set fails with
        `ERR_UNKNOWN_ROLE`"
        PRD: "`X-User-Role` names one of the six declared roles, on every endpoint — otherwise
        `ERR_UNKNOWN_ROLE` (401)."

        Design: Corner/validations/request_with_invalid_role_header_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.register_partnership(api)

        response = api.get_partnership(
            partnership["id"], headers=make_headers("someone-1", "REGISTRAR")
        )

        validate_error(response, ApiErrorId.UNKNOWN_ROLE.value, 401)


class TestSegregationOfDuties:
    def test_a_statement_cannot_be_approved_by_the_identity_that_authored_it(self, api):
        """The correct role carried by the authoring identity is still refused.

        PRD: "Approval is a `UniversityProvost` act, and the approving `X-User-ID` must differ from
        `authored_by_user_id`; a match is refused with `ERR_SEGREGATION_OF_DUTIES` even though the
        approver holds the correct role."
        PRD: "Segregation of duties holds: the `X-User-ID` approving a settlement statement differs
        from that statement's `authored_by_user_id`, and the `X-User-ID` deciding a counselor
        compliance review differs from that counselor's `last_review_user_id` whenever a prior
        review exists. Breaches yield `ERR_SEGREGATION_OF_DUTIES` (403)."

        Design: Corner/validations/statement_approved_by_its_own_authoring_user_is_rejected
        """
        context = fixtures.build_september_statement(api, credits_completed=None)
        statement = context["statement"]
        assert statement["authored_by_user_id"] == BURSAR_USER_ID
        assert statement["net_payable_cents"] == 73919

        response = api.post_statement_action(
            statement["id"],
            factories.statement_action_payload("APPROVE"),
            headers=make_provost_headers(BURSAR_USER_ID),
        )

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        stored = fixtures.read_statement(api, statement["id"])
        assert stored["status"] == "CALCULATED"
        assert stored["approved_by_user_id"] is None

    def test_a_second_review_by_the_same_auditor_is_refused(self, api):
        """An otherwise legal ELIGIBLE to SUSPENDED edge is blocked by the deciding identity.

        PRD: "Once a first review exists, a second review of the same counselor by the same
        identity is refused with `ERR_SEGREGATION_OF_DUTIES`: consecutive reviews of one counselor
        must be decided by different auditors."
        PRD: "A `decision` of `SUSPEND` takes either `PENDING_COMPLIANCE_REVIEW` or `ELIGIBLE` to
        `SUSPENDED`. Every decision records the acting `X-User-ID` as `last_review_user_id`."

        Design: Corner/validations/second_compliance_review_by_the_same_auditor_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        counselor = fixtures.create_eligible_counselor(api, partnership["id"])
        assert counselor["incentive_eligibility"] == "ELIGIBLE"
        assert counselor["last_review_user_id"] == COMPLIANCE_AUDITOR_USER_ID

        response = api.post_compliance_review(
            counselor["id"],
            factories.compliance_review_payload("SUSPEND", reviewer_note="Follow-up spot check."),
            headers=make_compliance_auditor_headers(),
        )

        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        stored = fixtures.read_counselor(api, counselor["id"])
        assert stored["incentive_eligibility"] == "ELIGIBLE"
        assert stored["last_review_user_id"] == COMPLIANCE_AUDITOR_USER_ID


class TestTeachOutObligations:
    def test_certification_with_less_than_ninety_days_notice_is_refused(self, api):
        """The notice floor binds at certification, not at drafting, so the plan stays DRAFT.

        PRD: "It also requires adequate student notice: `student_notification_date` must precede
        `teach_out_end_date` by at least 90 whole days, and a shorter notice is refused with
        `ERR_TEACH_OUT_NOTICE_TOO_SHORT`."
        PRD: "`student_notification_date` precedes `teach_out_end_date` by at least the minimum
        notice period, on teach-out certification — otherwise `ERR_TEACH_OUT_NOTICE_TOO_SHORT`
        (422)."

        Design: Corner/validations/teach_out_certification_with_short_notice_is_rejected
        """
        context = fixtures.build_teach_out_program(api)
        plan = fixtures.draft_teach_out_plan(
            api,
            context["pg_id"],
            teach_out_end_date="2026-10-01",
            student_notification_date="2026-09-05",
            asset_transfer_scope="NONE",
        )
        assert plan["status"] == "DRAFT"

        response = api.certify_teach_out_plan(
            plan["id"], factories.certify_payload(), headers=make_compliance_auditor_headers()
        )

        validate_error(response, ApiErrorId.TEACH_OUT_NOTICE_TOO_SHORT.value, 422)

        rows, _ = validate_paginated(
            api.list_teach_out_plans(context["pg_id"], headers=make_provost_headers())
        )
        assert [row["status"] for row in rows if row["id"] == plan["id"]] == ["DRAFT"]

    def test_a_program_cannot_close_without_a_certified_plan(self, api):
        """An empty roster alone does not discharge the obligation.

        PRD: "A close attempted without a certified plan, or with students still active, is refused
        with `ERR_TEACH_OUT_OBLIGATIONS_UNMET`."
        PRD: "Teach-out obligations are discharged: a program may be closed only with a `CERTIFIED`
        teach-out plan in place and no remaining active enrollments, and a partnership may be closed
        out only when every one of its programs has settled into `CLOSED`, `REJECTED` or `DRAFT` and
        no settlement statement is still open. Breaches yield `ERR_TEACH_OUT_OBLIGATIONS_UNMET`
        (409)."

        Design: Corner/validations/program_close_without_a_certified_teach_out_plan_is_rejected
        """
        context = fixtures.build_teach_out_program(api)

        response = api.post_program_lifecycle_action(
            context["pg_id"],
            factories.lifecycle_action_payload("CLOSE"),
            headers=make_provost_headers(),
        )

        validate_error(response, ApiErrorId.TEACH_OUT_OBLIGATIONS_UNMET.value, 409)

        stored = fixtures.read_program(api, context["pg_id"])
        assert stored["status"] == "TEACH_OUT"
        assert stored["active_enrollment_count"] == 0


class TestServiceScopeRules:
    def test_a_domain_cannot_be_assigned_twice_to_one_program(self, api):
        """The split of responsibility is a set, so the second MARKETING row is refused.

        PRD: "A domain may appear at most once per program; a second assignment of the same
        `service_domain` is refused with `ERR_DUPLICATE_SERVICE_DOMAIN`."
        PRD: "The `service_domain` is not already assigned for this program, on service-scope
        assignment creation — otherwise `ERR_DUPLICATE_SERVICE_DOMAIN` (409)."

        Design: Corner/validations/duplicate_service_domain_assignment_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        program = fixtures.create_program(api, partnership["id"])
        fixtures.assign_service_scope(api, program["id"], "MARKETING")

        response = api.create_service_scope_assignment(
            program["id"],
            factories.service_scope_payload(
                "MARKETING",
                responsible_party="UNIVERSITY",
                sla_response_hours=48,
                cost_bearer="UNIVERSITY",
            ),
            headers=make_provost_headers(),
        )

        validate_error(response, ApiErrorId.DUPLICATE_SERVICE_DOMAIN.value, 409)

        _, meta = validate_paginated(
            api.list_service_scope_assignments(
                program["id"], {"limit": 10, "offset": 0}, headers=make_provost_headers()
            )
        )
        assert meta["total_count"] == 1

    def test_course_design_cannot_be_handed_to_the_partner(self, api):
        """A non-delegable domain refuses `PARTNER` as the responsible party.

        PRD: "`COURSE_DESIGN`, `FACULTY_TRAINING` and `ACCESSIBILITY_ACCOMMODATIONS` must always be
        performed by the university; assigning any of them to the partner is refused with
        `ERR_NON_DELEGABLE_SERVICE_DOMAIN`."
        PRD: "an attempt to hand any of them to `PARTNER` is refused with
        `ERR_NON_DELEGABLE_SERVICE_DOMAIN` — even though the same partnership may legitimately make
        the partner the `cost_bearer` for them."

        Design: Corner/validations/non_delegable_course_design_domain_assigned_to_partner_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        program = fixtures.create_program(api, partnership["id"])

        response = api.create_service_scope_assignment(
            program["id"],
            factories.service_scope_payload(
                "COURSE_DESIGN",
                responsible_party="PARTNER",
                sla_response_hours=72,
                cost_bearer="PARTNER",
            ),
            headers=make_provost_headers(),
        )

        validate_error(response, ApiErrorId.NON_DELEGABLE_SERVICE_DOMAIN.value, 422)


class TestCoursePrerequisitesAndOwnership:
    def test_repointing_a_prerequisite_into_a_loop_is_refused(self, api):
        """The amendment that would close a two-node cycle leaves the edge null.

        PRD: "A supplied `prerequisite_course_id` must name an existing course of the same program,
        otherwise `ERR_PREREQUISITE_COURSE_NOT_FOUND`; and the resulting edge must not create a
        cycle when the edges are followed transitively, otherwise `ERR_PREREQUISITE_CYCLE`."
        PRD: "it may revise `title`, `credits`, `design_cost_cents`, `required_for_launch`,
        `ip_license_grant_back` and `prerequisite_course_id`."

        Design: Corner/validations/prerequisite_edge_repointed_into_a_cycle_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        first = fixtures.add_course(api, ps_id, program["id"])
        second = fixtures.add_course(
            api,
            ps_id,
            program["id"],
            course_code="MBA-502",
            title="Managerial Accounting",
            design_cost_cents=900000,
            required_for_launch=False,
            prerequisite_course_id=first["id"],
        )
        assert second["prerequisite_course_id"] == first["id"]

        response = api.amend_course(
            first["id"],
            {"prerequisite_course_id": second["id"]},
            headers=make_faculty_chair_headers(),
        )

        validate_error(response, ApiErrorId.PREREQUISITE_CYCLE.value, 422)

        stored = fixtures.read_course(api, first["id"])
        assert stored["prerequisite_course_id"] is None

    def test_a_partner_owned_course_without_grant_back_cannot_be_approved(self, api):
        """Ownership is policed at APPROVE, so the course is left in FACULTY_REVIEW.

        PRD: "`FACULTY_REVIEW → APPROVED` requires a `faculty_approver_name` supplied on the action
        — the faculty member of record, recorded onto the course and null until then — and it
        requires the content-ownership rule to hold: a course may be approved when its
        `content_owner` is `UNIVERSITY`, or when its `content_owner` is `PARTNER` or `JOINT` *and*
        its `ip_license_grant_back` is true."
        PRD: "A partner-owned or jointly-owned course without the grant-back licence is refused
        with `ERR_FACULTY_IP_OWNERSHIP_VIOLATION`, because the university would otherwise lose the
        ability to keep teaching its own curriculum after the partner leaves."

        Design: Corner/validations/course_approval_with_partner_ownership_and_no_grant_back_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        course = fixtures.add_course(
            api,
            ps_id,
            program["id"],
            course_code="MBA-590",
            title="Partner Capstone Studio",
            content_owner="PARTNER",
            design_cost_cents=1200000,
            required_for_launch=True,
            ip_license_grant_back=False,
        )
        fixtures.start_course_design(api, ps_id, course["id"])
        fixtures.submit_course_for_faculty_review(api, ps_id, course["id"])

        response = api.post_course_design_action(
            course["id"],
            factories.design_action_payload(
                "APPROVE", faculty_approver_name=fixtures.FACULTY_APPROVER_NAME
            ),
            headers=make_faculty_chair_headers(),
        )

        validate_error(response, ApiErrorId.FACULTY_IP_OWNERSHIP_VIOLATION.value, 422)

        stored = fixtures.read_course(api, course["id"])
        assert stored["design_status"] == "FACULTY_REVIEW"


class TestMarketingBudgetGuard:
    def test_a_spend_one_cent_over_the_remaining_envelope_is_refused(self, api):
        """The guard reads the live balance and the refused entry leaves it untouched.

        PRD: "A `SPEND` entry must fit inside the envelope: its `amount_cents` may not exceed the
        partnership's current `marketing_budget_remaining_cents`, and an entry that would overspend
        is refused with `ERR_MARKETING_BUDGET_EXCEEDED`."
        PRD: "A spend entry's `amount_cents` is no greater than the partnership's
        `marketing_budget_remaining_cents`, on marketing ledger posting — otherwise
        `ERR_MARKETING_BUDGET_EXCEEDED` (422)."

        Design: Corner/validations/marketing_spend_over_the_remaining_budget_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        assert fixtures.read_partnership(api, ps_id)["marketing_budget_remaining_cents"] == 4000000

        response = api.create_marketing_spend_entry(
            program["id"],
            factories.marketing_spend_payload(amount_cents=4000001, spend_date="2026-08-01"),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.MARKETING_BUDGET_EXCEEDED.value, 422)

        stored = fixtures.read_partnership(api, ps_id)
        assert stored["marketing_budget_remaining_cents"] == 4000000

    def test_a_spend_exactly_at_the_remaining_envelope_is_accepted(self, api):
        """The inclusive twin: the envelope may be spent to exactly zero.

        PRD: "Alternatively the provost signs with `EXECUTE`, taking `UNDER_REVIEW → EXECUTED`:
        `executed_date` is set to the `executed_date` supplied on the action if one was supplied and
        otherwise to the logical clock's date, `marketing_budget_remaining_cents` is opened up to
        equal `marketing_budget_cents`, and `version` increments."
        PRD: "`marketing_budget_remaining_cents` is `marketing_budget_cents` less that posted net,
        and `unrecouped_marketing_spend_cents` is that posted net less the sum of
        `marketing_recoupment_cents` over the partnership's statements whose `status` is
        `REMITTED`."

        Design: Corner/validations/marketing_spend_exactly_at_the_remaining_budget_is_accepted
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)

        response = api.create_marketing_spend_entry(
            program["id"],
            factories.marketing_spend_payload(amount_cents=4000000, spend_date="2026-08-01"),
            headers=make_partner_account_lead_headers(ps_id),
        )
        entry = validate_success(response, 201)

        assert entry["amount_cents"] == 4000000

        stored = fixtures.read_partnership(api, ps_id)
        assert stored["marketing_budget_remaining_cents"] == 0
        assert stored["unrecouped_marketing_spend_cents"] == 4000000


class TestTuitionRefundGuard:
    def test_a_refund_one_cent_over_the_collected_amount_is_refused(self, api):
        """The bound is per enrollment, and the ledger keeps both counters where they were.

        PRD: "A manual `REFUND` may not exceed what remains collected — its `amount_cents` must be
        no greater than the enrollment's `collected_cents` less its `refunded_cents` — and an
        over-refund is refused with `ERR_REFUND_EXCEEDS_COLLECTED`."
        PRD: "A refund entry's `amount_cents` is no greater than the enrollment's collected amount
        less its already-refunded amount, on tuition ledger posting — otherwise
        `ERR_REFUND_EXCEEDS_COLLECTED` (422)."

        Design: Corner/validations/refund_over_the_net_collected_amount_is_rejected
        """
        context = fixtures.build_paid_enrollment(api)

        response = api.create_tuition_payment(
            context["en_id"],
            factories.tuition_payment_payload(
                entry_type="REFUND",
                amount_cents=562501,
                posted_date="2026-09-05",
                reference_note="Overstated refund",
            ),
            headers=make_bursar_headers(),
        )

        validate_error(response, ApiErrorId.REFUND_EXCEEDS_COLLECTED.value, 422)

        stored = fixtures.read_enrollment(api, context["en_id"])
        assert stored["collected_cents"] == 562500
        assert stored["refunded_cents"] == 0


class TestSettlementGuards:
    def test_a_period_that_has_not_fully_elapsed_cannot_be_cut(self, api):
        """With the clock on 2026-10-01 an October period is still running.

        PRD: "`period_end` must fall strictly before the logical clock date: a period that has not
        fully elapsed cannot be settled, and an attempt to do so is refused with
        `ERR_PERIOD_NOT_ELAPSED`."
        PRD: "an `open_statement_count` of the partnership's statements that have not reached
        `REMITTED` and are not absent from the settlement pipeline — that is, statements in
        `CALCULATED`, `UNIVERSITY_APPROVED`, `DISPUTED`, `RESOLVED_ADJUSTED` or `STALE`"

        Design: Corner/validations/statement_for_a_period_that_has_not_fully_elapsed_is_rejected
        """
        context = fixtures.build_paid_enrollment(api, final_clock=fixtures.CLOCK_OCT_1)
        ps_id = context["ps_id"]

        response = api.create_remittance_statement(
            ps_id,
            factories.statement_payload(
                fixtures.current_partnership_version(api, ps_id),
                period_start="2026-10-01",
                period_end="2026-10-31",
            ),
            headers=make_bursar_headers(),
        )

        validate_error(response, ApiErrorId.PERIOD_NOT_ELAPSED.value, 422)

        summary = validate_success(api.get_revenue_summary(ps_id, headers=make_bursar_headers()))
        assert summary["open_statement_count"] == 0

    def test_an_approved_statement_with_nothing_payable_cannot_be_remitted(self, api):
        """An August period precedes the term, so the statement is approvable but not payable.

        PRD: "For any given date, the elapsed count is zero when that date falls before
        `term_start_date`, and otherwise is the number of days from `term_start_date` to that date
        counting the first day, capped at the term length so a term cannot over-recognise past its
        end."
        PRD: "A `UniversityBursar` remits with a mandatory `remittance_reference`, taking
        `UNIVERSITY_APPROVED → REMITTED`, which requires `net_payable_cents` to be strictly greater
        than zero — remitting nothing, or a negative balance, is refused with
        `ERR_NOTHING_TO_REMIT`."

        Design: Corner/validations/remit_on_a_zero_net_payable_statement_is_rejected
        """
        context = fixtures.build_paid_enrollment(api, final_clock=fixtures.CLOCK_OCT_1)
        ps_id = context["ps_id"]
        statement = fixtures.cut_statement(
            api, ps_id, period_start="2026-08-01", period_end="2026-08-31"
        )
        assert statement["recognized_revenue_cents"] == 0
        assert statement["net_payable_cents"] == 0

        approved = fixtures.approve_statement(api, statement["id"])
        assert approved["status"] == "UNIVERSITY_APPROVED"

        response = api.post_statement_action(
            statement["id"],
            factories.statement_action_payload("REMIT", remittance_reference="ACH-2026-08"),
            headers=make_bursar_headers(),
        )

        validate_error(response, ApiErrorId.NOTHING_TO_REMIT.value, 409)

        stored = fixtures.read_statement(api, statement["id"])
        assert stored["status"] == "UNIVERSITY_APPROVED"
        assert fixtures.read_partnership(api, ps_id)["remitted_to_partner_cents"] == 0


class TestLaunchWindowAndContractTerm:
    def test_a_launch_on_the_exclusive_end_of_the_window_is_refused(self, api):
        """The window is half-open, so its end date is not a legal launch day.

        PRD: "Finally, `launch_window_start` and `launch_window_end` bound the dates on which the
        program may go live, and the window is half-open: the start date is included and the end
        date is not."
        PRD: "The logical clock's date must fall inside the half-open launch window — on or after
        `launch_window_start` and strictly before `launch_window_end` — with a date outside that
        interval refused as `ERR_OUTSIDE_LAUNCH_WINDOW`."

        Design: Corner/validations/launch_on_the_exclusive_end_of_the_launch_window_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        program = fixtures.create_program(api, ps_id)
        pg_id = program["id"]
        fixtures.create_approved_course(api, ps_id, pg_id)
        fixtures.assign_service_scope(api, pg_id, "MARKETING")
        fixtures.submit_program(api, ps_id, pg_id)
        approved = fixtures.approve_program(api, pg_id)
        assert approved["launch_window_end"] == "2026-12-31"

        fixtures.set_clock(api, fixtures.CLOCK_DEC_31)
        response = api.post_program_lifecycle_action(
            pg_id,
            factories.lifecycle_action_payload("LAUNCH"),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.OUTSIDE_LAUNCH_WINDOW.value, 422)

        assert fixtures.read_program(api, pg_id)["status"] == "APPROVED"

    def test_a_lead_cannot_be_created_after_the_contract_has_expired(self, api):
        """Every entity is still valid; only the clock has moved past `expiry_date`.

        PRD: "Creation is refused with `ERR_PROGRAM_INVALID_STATE` when the program is not
        `LAUNCHED` — including while it is `SUSPENDED` — with `ERR_CONTRACT_TERM_EXPIRED` when the
        logical clock date is past the partnership's `expiry_date`, and with
        `ERR_COUNSELOR_INCENTIVE_SUSPENDED` when the named counselor's `incentive_eligibility` is
        `PROHIBITED_PLAN_ON_FILE`."
        PRD: "The logical clock date is no later than the partnership's `expiry_date`, on the
        program lifecycle actions `LAUNCH` and `RESUME`, on lead creation, on lead enrollment and on
        statement creation — otherwise `ERR_CONTRACT_TERM_EXPIRED` (409)."

        Design: Corner/validations/lead_creation_after_the_contract_expiry_date_is_rejected
        """
        context = fixtures.build_launched_program(api)
        ps_id = context["ps_id"]
        assert fixtures.read_partnership(api, ps_id)["expiry_date"] == "2033-07-31"

        fixtures.set_clock(api, fixtures.CLOCK_PAST_EXPIRY)
        response = api.create_lead(
            factories.lead_payload(
                context["pg_id"], context["co_id"], prospect_external_id="P-9001"
            ),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.CONTRACT_TERM_EXPIRED.value, 409)


class TestContractEconomicsCoherence:
    def test_a_revenue_share_contract_cannot_carry_a_monthly_fee(self, api):
        """The two economic models are mutually exclusive from registration onward.

        PRD: "The fee schedule and the contract structure must agree at all times: a
        `fee_schedule_monthly_cents` greater than zero is only legal when `contract_structure` is
        `FEE_FOR_SERVICE`, and a partnership on `REVENUE_SHARE` must hold
        `fee_schedule_monthly_cents` at exactly 0. A registration or amendment that violates this is
        refused with `ERR_FEE_STRUCTURE_MISMATCH`, and the same coherence is re-checked when the
        contract is submitted for review."
        PRD: "The fee schedule and the contract structure agree, on partnership registration, on
        the terms amendment and on the contract action `SUBMIT_FOR_REVIEW` — otherwise
        `ERR_FEE_STRUCTURE_MISMATCH` (422)."

        Design: Corner/validations/fee_schedule_on_a_revenue_share_partnership_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)

        response = api.create_partnership(
            factories.partnership_payload(
                contract_structure="REVENUE_SHARE",
                fee_schedule_monthly_cents=250000,
                exclusivity_cip_codes=factories.OMIT,
                bundled_services_exception_claimed=factories.OMIT,
            ),
            headers=make_platform_admin_headers(),
        )

        validate_error(response, ApiErrorId.FEE_STRUCTURE_MISMATCH.value, 422)


class TestCompensationLimits:
    def test_a_permitted_plan_over_the_variable_envelope_is_refused(self, api):
        """`GRADUATION_MILESTONE` clears the ban, so only the one-fifth ceiling can bite.

        PRD: "A second fiscal limit applies to plans that clear the ban:
        `variable_component_cents` may not exceed 20 percent of `annual_base_cents` — one fifth of
        declared annual base pay is the whole variable envelope — and a plan that exceeds it is
        refused with `ERR_COMP_EXCEEDS_APPROVED_ENVELOPE`."
        PRD: "A `comp_plan_type` of `FIXED_SALARY` or `GRADUATION_MILESTONE` is always permitted,
        the latter paired with the `GRADUATION_COUNT` basis."

        Design: Corner/validations/graduation_milestone_plan_over_the_variable_envelope_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]
        counselor = fixtures.create_counselor(api, ps_id)

        response = api.file_compensation_plan(
            counselor["id"],
            factories.compensation_plan_payload(
                comp_plan_type="GRADUATION_MILESTONE",
                annual_base_cents=6000000,
                variable_component_cents=1300000,
                variable_basis="GRADUATION_COUNT",
            ),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.COMP_EXCEEDS_APPROVED_ENVELOPE.value, 422)

        stored = fixtures.read_counselor(api, counselor["id"])
        assert stored["comp_plan_type"] == "NONE_ON_FILE"

    def test_a_qualitative_plan_is_prohibited_without_the_bundled_services_claim(self, api):
        """The same plan shape turns on the parent partnership's exception flag.

        PRD: "A `comp_plan_type` of `SALARY_PLUS_QUALITATIVE` paired with a `variable_basis` of
        `QUALITATIVE_MULTI_FACTOR` is permitted only when the parent partnership's
        `bundled_services_exception_claimed` is true, since the qualitative multi-factor shape
        relies on the bundled-services exception; without the claim it is refused."
        PRD: "`bundled_services_exception_claimed` defaults to false and declares whether the
        partnership claims the bundled-services exception that permits counselor salary adjustments
        not based solely on enrollment counts."

        Design: Corner/validations/qualitative_plan_without_the_bundled_services_exception_is_rejected
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(
            api,
            university_name="Lakeshore University",
            university_ipeds_id="224999",
            exclusivity_cip_codes=factories.OMIT,
            bundled_services_exception_claimed=factories.OMIT,
        )
        ps_id = partnership["id"]
        assert partnership["bundled_services_exception_claimed"] is False

        counselor = fixtures.create_counselor(
            api,
            ps_id,
            full_name="Dana Ilk",
            employer="PARTNER",
            monthly_base_salary_cents=480000,
        )

        response = api.file_compensation_plan(
            counselor["id"],
            factories.compensation_plan_payload(
                comp_plan_type="SALARY_PLUS_QUALITATIVE",
                annual_base_cents=5760000,
                variable_component_cents=100000,
                variable_basis="QUALITATIVE_MULTI_FACTOR",
            ),
            headers=make_partner_account_lead_headers(ps_id),
        )

        validate_error(response, ApiErrorId.INCENTIVE_COMP_PROHIBITED.value, 422)

        stored = fixtures.read_counselor(api, counselor["id"])
        assert stored["comp_plan_type"] == "NONE_ON_FILE"
        assert stored["incentive_eligibility"] == "PENDING_COMPLIANCE_REVIEW"
