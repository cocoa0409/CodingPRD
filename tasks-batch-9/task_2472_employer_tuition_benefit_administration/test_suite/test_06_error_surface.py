"""Not-found resolution, state locks and the specific refusal each gate raises."""

from test_helpers import (
    AcademicStatus,
    ApprovalDecision,
    ApprovalRequestStatus,
    ClaimDecision,
    CompletionStatus,
    EligibilityStatus,
    EmploymentStatus,
    ERR_AGREEMENT_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_EMPLOYEE_NOT_ELIGIBLE,
    ERR_EMPLOYEE_NOT_FOUND,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_INVOICE_NOT_FOUND,
    ERR_LISTING_NOT_FOUND,
    ERR_NO_ACTIVE_POLICY,
    ERR_OBLIGATION_INVALID_STATE,
    ERR_OBLIGATION_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_REIMBURSEMENT_NOT_ALLOWED,
    ERR_REPAYMENT_EXCEEDS_BALANCE,
    ERR_REQUEST_INVALID_STATE,
    ERR_REQUEST_NOT_FOUND,
    ERR_SCHOOL_NOT_FOUND,
    FundingModel,
    FundingStatus,
    JobFamily,
    ObligationReason,
    ObligationStatus,
    Scenario,
    approval_decision_payload,
    assert_obligation_identity,
    build_vantage_direct_bill_clawed_back,
    build_vantage_direct_bill_paid,
    build_vantage_exception_path,
    build_vantage_reimbursement_enrolled,
    catalog_listing_payload,
    claim_decision_payload,
    employee_patch_payload,
    enrollment_payload,
    make_benefit_administrator_headers,
    make_coach_headers,
    make_platform_admin_headers,
    program_approval_request_payload,
    reimbursement_claim_payload,
    repayment_payment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_EMPLOYER_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PROGRAM_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_ANY_ID = "44444444-4444-4444-8444-444444444444"


def test_an_unknown_path_employer_is_reported_as_the_employer_not_found(api):
    """Every /employers/{id} route resolves its container before anything else.

    PRD §2.9: "The `Employer` named in the path exists; otherwise
    `ERR_EMPLOYER_NOT_FOUND` (404). Applies to `GET /employers/{id}`, `GET
    /employers/{id}/utilization-report`, `POST /employers/{id}/benefit-policies`,
    `GET /employers/{id}/benefit-policies`, `POST /employers/{id}/employees`, `GET
    /employers/{id}/employees`."

    Design: Corner/errors/employer_not_found_on_unknown_path_employer
    """
    platform_admin = make_platform_admin_headers()
    benefit_admin = make_benefit_administrator_headers(UNKNOWN_EMPLOYER_ID)

    validate_error(
        api.get_employer(UNKNOWN_EMPLOYER_ID, platform_admin),
        ERR_EMPLOYER_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_utilization_report(UNKNOWN_EMPLOYER_ID, platform_admin),
        ERR_EMPLOYER_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_benefit_policies(UNKNOWN_EMPLOYER_ID, platform_admin),
        ERR_EMPLOYER_NOT_FOUND,
        404,
    )
    validate_error(
        api.list_employees(UNKNOWN_EMPLOYER_ID, benefit_admin),
        ERR_EMPLOYER_NOT_FOUND,
        404,
    )


def test_a_listing_body_naming_an_unknown_program_raises_program_not_found(api):
    """A body reference that names nothing raises its own entity's not-found error.

    PRD §2.9: "Body-referenced resources exist, checked in the order the fields are
    declared in the endpoint's input list — `employer_id`, then `school_id`, then
    `employee_id`, then `program_id`, then `agreement_id`, then
    `catalog_listing_id`, then `enrollment_id` — and each missing reference raises
    the not-found error of its own entity type: `ERR_EMPLOYER_NOT_FOUND`,
    `ERR_SCHOOL_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND` or
    `ERR_ENROLLMENT_NOT_FOUND`, each 404."

    Design: Corner/errors/program_not_found_when_listing_body_references_unknown_program
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_school()
    s.publish_program()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()

    validate_error(
        api.create_catalog_listing(
            catalog_listing_payload(
                employer_id=s.employer_id,
                program_id=UNKNOWN_PROGRAM_ID,
                agreement_id=s.agreement_id,
                expected_agreement_version=s.agreement_version(),
            ),
            s.benefit_admin,
        ),
        ERR_PROGRAM_NOT_FOUND,
        404,
    )

    _, meta = validate_paginated(
        api.list_catalog_listings(s.benefit_admin, {"employer_id": s.employer_id})
    )
    assert meta["total_count"] == 0


def test_enrolling_without_any_active_policy_is_refused(api):
    """A catalog and an employee are not enough; a current policy is required.

    PRD §2.9: "The employer has exactly one current benefit policy — `status` of
    `ACTIVE`, with `effective_from` on or before the logical clock date and
    `effective_to` strictly after it; otherwise `ERR_NO_ACTIVE_POLICY` (409).
    Applies to `POST /enrollments` and `POST /program-approval-requests`."

    Design: Corner/errors/enrollment_without_any_active_policy_is_refused
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_employee()
    s.register_school()
    s.publish_program()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()

    employee = s.read_employee()
    assert employee["eligibility_status"] == EligibilityStatus.INELIGIBLE_NO_POLICY
    assert employee["cap_plan_year"] == 2026
    assert employee["cap_available_cents"] == 0
    assert employee["coaching_hold"] is False

    validate_error(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=employee["version"],
                term_code="2026-FA",
                term_start_date="2026-09-01",
                term_end_date="2026-12-15",
                credits=4,
                funding_model=FundingModel.REIMBURSEMENT,
            ),
            s.employee,
        ),
        ERR_NO_ACTIVE_POLICY,
        409,
    )

    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 0


def test_a_direct_bill_enrollment_cannot_file_a_reimbursement_claim(api):
    """Only rule 31 can produce this error, and a passed direct-bill term proves it.

    PRD §2.9: "The enrollment's `funding_model` is `REIMBURSEMENT`; otherwise
    `ERR_REIMBURSEMENT_NOT_ALLOWED` (409). Applies to `POST
    /enrollments/{id}/reimbursement-claims`."

    Design: Corner/errors/direct_bill_enrollment_cannot_file_a_reimbursement_claim
    """
    s = build_vantage_direct_bill_paid(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.PASSED, 4, 3.60)

    enrollment = s.read_enrollment()
    assert enrollment["academic_status"] == AcademicStatus.PASSED
    assert enrollment["funding_model"] == FundingModel.DIRECT_BILL

    validate_error(
        api.create_reimbursement_claim(
            s.enrollment_id,
            reimbursement_claim_payload(160_000, "CVC-2026FA-RDELGADO-DB"),
            s.employee,
        ),
        ERR_REIMBURSEMENT_NOT_ALLOWED,
        409,
    )

    _, meta = validate_paginated(
        api.list_reimbursement_claims(s.enrollment_id, s.benefit_admin)
    )
    assert meta["total_count"] == 0
    assert s.read_enrollment()["employer_disbursed_cents"] == 160_000

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 160_000
    assert employer["total_admin_fee_cents"] == 0


def test_a_repeat_enrollment_for_the_same_listing_and_term_is_refused(api):
    """The slot is held until the earlier term is WITHDRAWN or FAILED.

    PRD §3.4: "A repeat enrollment for the same employee, listing and `term_code`
    is refused with `ERR_DUPLICATE_ENROLLMENT` unless the earlier one is
    `WITHDRAWN` or `FAILED`, which are the two outcomes that release the slot."

    Design: Corner/errors/duplicate_enrollment_for_same_listing_and_term_is_refused
    """
    s = build_vantage_reimbursement_enrolled(api)

    def repeat():
        return api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=s.employee_version(),
                term_code="2026-FA",
                term_start_date="2026-09-01",
                term_end_date="2026-12-15",
                credits=4,
                funding_model=FundingModel.REIMBURSEMENT,
            ),
            s.employee,
        )

    validate_error(repeat(), ERR_DUPLICATE_ENROLLMENT, 409)

    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 1
    assert s.read_employee()["cap_reserved_cents"] == 80_000

    s.withdraw()
    replacement = validate_success(repeat(), 201)
    assert replacement["id"] != s.enrollment_id
    assert replacement["term_code"] == "2026-FA"
    assert replacement["employer_reserved_cents"] == 80_000


def test_a_repayment_larger_than_the_balance_is_refused(api):
    """160,001 is one cent too much while exactly 160,000 settles the obligation.

    PRD §2.9: "The payment's `amount_cents` is at most the obligation's
    `balance_cents`; otherwise `ERR_REPAYMENT_EXCEEDS_BALANCE` (422). Applies to
    `POST /repayment-obligations/{id}/payments`."

    Design: Corner/errors/repayment_payment_above_balance_is_refused
    """
    s = build_vantage_direct_bill_clawed_back(api)
    obligation = s.first_obligation()
    assert obligation["trigger_reason"] == ObligationReason.ACADEMIC_FAILURE
    assert obligation["principal_cents"] == 160_000
    assert obligation["paid_cents"] == 0
    assert obligation["waived_cents"] == 0
    assert obligation["balance_cents"] == 160_000
    assert obligation["status"] == ObligationStatus.ASSESSED
    assert_obligation_identity(obligation)

    validate_error(
        api.create_repayment_payment(
            s.obligation_id, repayment_payment_payload(160_001), s.employee
        ),
        ERR_REPAYMENT_EXCEEDS_BALANCE,
        422,
    )

    employee = s.read_employee()
    assert employee["open_repayment_balance_cents"] == 160_000
    assert employee["cap_clawback_hold_cents"] == 160_000

    settled = validate_success(
        api.create_repayment_payment(
            s.obligation_id, repayment_payment_payload(160_000), s.employee
        )
    )
    assert settled["paid_cents"] == 160_000
    assert settled["balance_cents"] == 0
    assert settled["status"] == ObligationStatus.SETTLED
    assert_obligation_identity(settled)


def test_an_employee_on_leave_is_not_eligible_to_enrol(api):
    """LEAVE is not ACTIVE, so the employment gate blocks the enrollment.

    PRD §3.1: "The verdict is measured against the employer's current policy — the
    unique policy whose `status` is `ACTIVE` and whose `effective_from` is on or
    before the logical clock date while its `effective_to` is strictly after it —
    and resolves as follows, stopping at the first match: no current policy yields
    `INELIGIBLE_NO_POLICY`; an `employment_status` other than `ACTIVE` yields
    `INELIGIBLE_EMPLOYMENT`; `tenure_months` below the policy's
    `min_tenure_months` yields `INELIGIBLE_TENURE`; `weekly_hours` below the
    policy's `min_weekly_hours` yields `INELIGIBLE_HOURS`; a `job_family` that is
    not a member of the policy's `eligible_job_families` yields
    `INELIGIBLE_JOB_FAMILY`; and anything that survives all five yields
    `ELIGIBLE`."

    Design: Corner/errors/employee_on_leave_is_not_eligible_to_enrol
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.OPERATIONS],
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
    )
    s.activate_policy()
    s.register_employee()
    s.register_school()
    s.publish_program()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()

    on_leave = validate_success(
        api.patch_employee(
            s.employee_id,
            employee_patch_payload(employment_status=EmploymentStatus.LEAVE),
            s.benefit_admin,
        )
    )
    assert on_leave["employment_status"] == EmploymentStatus.LEAVE
    assert on_leave["eligibility_status"] == EligibilityStatus.INELIGIBLE_EMPLOYMENT
    assert on_leave["termination_date"] is None
    assert on_leave["weekly_hours"] == 40
    assert on_leave["tenure_months"] == 30

    def enrol():
        return api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=s.employee_version(),
                term_code="2026-FA",
                term_start_date="2026-09-01",
                term_end_date="2026-12-15",
                credits=4,
                funding_model=FundingModel.REIMBURSEMENT,
            ),
            s.employee,
        )

    validate_error(enrol(), ERR_EMPLOYEE_NOT_ELIGIBLE, 422)
    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 0

    reinstated = validate_success(
        api.patch_employee(
            s.employee_id,
            employee_patch_payload(employment_status=EmploymentStatus.ACTIVE),
            s.benefit_admin,
        )
    )
    assert reinstated["eligibility_status"] == EligibilityStatus.ELIGIBLE
    validate_success(enrol(), 201)


def test_each_unknown_path_id_raises_its_own_entity_not_found(api):
    """One unknown uuid walked across the path-resolution rules, error by error.

    PRD §2.9: "Nested paths resolve left to right, so a sub-resource identifier is
    only looked up after its container has been found, and the first identifier in
    the path that names nothing produces that container's own not-found error."

    Design: Corner/errors/unknown_path_ids_raise_each_entity_specific_not_found
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_employee()

    platform_admin = s.platform_admin
    benefit_admin = s.benefit_admin
    coach = make_coach_headers()
    unknown = UNKNOWN_ANY_ID

    validate_error(
        api.get_employer(unknown, platform_admin), ERR_EMPLOYER_NOT_FOUND, 404
    )
    validate_error(
        api.activate_benefit_policy(unknown, benefit_admin),
        ERR_POLICY_NOT_FOUND,
        404,
    )
    validate_error(api.get_employee(unknown, coach), ERR_EMPLOYEE_NOT_FOUND, 404)
    validate_error(
        api.get_school(unknown, platform_admin), ERR_SCHOOL_NOT_FOUND, 404
    )
    validate_error(
        api.list_programs(unknown, platform_admin), ERR_SCHOOL_NOT_FOUND, 404
    )
    validate_error(
        api.get_partner_agreement(unknown, platform_admin),
        ERR_AGREEMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_catalog_listing(unknown, platform_admin), ERR_LISTING_NOT_FOUND, 404
    )
    validate_error(
        api.get_program_approval_request(unknown, benefit_admin),
        ERR_REQUEST_NOT_FOUND,
        404,
    )
    validate_error(api.get_enrollment(unknown, coach), ERR_ENROLLMENT_NOT_FOUND, 404)
    validate_error(
        api.list_enrollment_invoices(unknown, benefit_admin),
        ERR_ENROLLMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.approve_invoice_for_payment(unknown, benefit_admin),
        ERR_INVOICE_NOT_FOUND,
        404,
    )
    validate_error(
        api.decide_reimbursement_claim(
            unknown, claim_decision_payload(ClaimDecision.APPROVE), benefit_admin
        ),
        ERR_CLAIM_NOT_FOUND,
        404,
    )
    validate_error(
        api.waive_repayment_obligation(unknown, benefit_admin),
        ERR_OBLIGATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_program_approval_request(
            program_approval_request_payload(
                employee_id=s.employee_id, program_id=unknown
            ),
            s.employee,
        ),
        ERR_PROGRAM_NOT_FOUND,
        404,
    )


def test_a_decided_approval_request_is_locked_against_a_second_decision(api):
    """APPROVED is terminal, so review, decide and resubmit all refuse afterwards.

    PRD §2.9: "The approval request's `status` admits the transition — `SUBMITTED`
    to take it into review, `UNDER_REVIEW` to decide it, `CHANGES_REQUESTED` to
    resubmit it; otherwise `ERR_REQUEST_INVALID_STATE` (409)."

    Design: Corner/errors/decided_approval_request_is_locked_against_a_second_decision
    """
    s = build_vantage_exception_path(api)
    request = s.open_approval_request()
    s.review_request()
    approved = s.decide_request(ApprovalDecision.APPROVE, "Approved as an exception.")
    assert approved["status"] == ApprovalRequestStatus.APPROVED

    validate_error(
        api.review_program_approval_request(request["id"], s.benefit_admin),
        ERR_REQUEST_INVALID_STATE,
        409,
    )
    validate_error(
        api.decide_program_approval_request(
            request["id"],
            approval_decision_payload(ApprovalDecision.REJECT, "Changed our mind."),
            s.benefit_admin,
        ),
        ERR_REQUEST_INVALID_STATE,
        409,
    )
    validate_error(
        api.resubmit_program_approval_request(request["id"], None, s.employee),
        ERR_REQUEST_INVALID_STATE,
        409,
    )

    final = validate_success(
        api.get_program_approval_request(request["id"], s.benefit_admin)
    )
    assert final["status"] == ApprovalRequestStatus.APPROVED
    assert final["revision_count"] == 0

    _, meta = validate_paginated(
        api.list_catalog_listings(
            s.benefit_admin, {"source_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_waived_obligation_is_locked_against_further_money_movement(api):
    """Waiving clears the balance but keeps the hold, and both actions then refuse.

    PRD §2.9: "The obligation's `status` is `ASSESSED` or `PARTIALLY_PAID`;
    otherwise `ERR_OBLIGATION_INVALID_STATE` (409). Applies to `POST
    /repayment-obligations/{id}/payments` and `POST
    /repayment-obligations/{id}/waive`."

    Design: Corner/errors/waived_obligation_is_locked_against_further_money_movement
    """
    s = build_vantage_direct_bill_clawed_back(api)
    s.first_obligation()

    waived = s.waive_obligation()
    assert waived["status"] == ObligationStatus.WAIVED
    assert waived["waived_cents"] == 160_000
    assert waived["paid_cents"] == 0
    assert waived["balance_cents"] == 0
    assert_obligation_identity(waived)

    employee = s.read_employee()
    assert employee["open_repayment_balance_cents"] == 0
    assert employee["cap_clawback_hold_cents"] == 160_000
    assert employee["cap_available_cents"] == 840_000

    validate_error(
        api.create_repayment_payment(
            s.obligation_id, repayment_payment_payload(1), s.employee
        ),
        ERR_OBLIGATION_INVALID_STATE,
        409,
    )
    validate_error(
        api.waive_repayment_obligation(s.obligation_id, s.benefit_admin),
        ERR_OBLIGATION_INVALID_STATE,
        409,
    )

    assert s.read_enrollment()["funding_status"] == FundingStatus.CLAWED_BACK
