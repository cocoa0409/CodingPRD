"""Entry states, transition preconditions and terminal-state refusals."""

from test_helpers import (
    AcademicStatus,
    ApprovalDecision,
    ApprovalRequestStatus,
    ApprovalSource,
    BenefitPolicyStatus,
    CompletionStatus,
    ERR_ENROLLMENT_INVALID_ACADEMIC_STATE,
    ERR_INVOICE_INVALID_STATE,
    ERR_LISTING_NOT_CURATED,
    ERR_POLICY_NOT_DRAFT,
    FundingModel,
    FundingStatus,
    InvoiceStatus,
    ListingStatus,
    PersistenceTier,
    PostedByRole,
    academic_outcome_payload,
    approval_decision_payload,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_employee_share_tracks_money_axis,
    assert_enrollment_axes,
    assert_persistence,
    assert_versioned_record,
    build_vantage_base,
    build_vantage_direct_bill_billed,
    build_vantage_exception_path,
    build_vantage_reimbursement_enrolled,
    build_vantage_reimbursement_in_progress,
    enrollment_payload,
    program_approval_request_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_enrollment_enters_registered_reserved_and_medium_tier(api):
    """A fresh four-credit reimbursement term reserves 80,000 and scores 30.

    PRD §3.4: "The new enrollment starts with `academic_status` `REGISTERED` on the
    academic axis and `funding_status` `RESERVED` on the money axis, with
    `credits_earned` 0, `employer_settled_cents` 0, `employer_disbursed_cents` 0
    and `last_session_date` null."

    Design: Corner/state_machines/enrollment_starts_registered_and_reserved_with_medium_persistence_tier
    """
    s = build_vantage_base(api)
    enrollment = validate_success(
        api.create_enrollment(
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
        ),
        201,
    )

    assert_enrollment_axes(
        enrollment, AcademicStatus.REGISTERED, FundingStatus.RESERVED
    )
    assert enrollment["credits_earned"] == 0
    assert enrollment["employer_settled_cents"] == 0
    assert enrollment["employer_disbursed_cents"] == 0
    assert enrollment["last_session_date"] is None
    assert enrollment["plan_year"] == 2026
    assert enrollment["drop_deadline_date"] == "2026-09-15"
    assert enrollment["gross_tuition_cents"] == 160_000
    assert enrollment["employer_reserved_cents"] == 80_000
    assert enrollment["employee_share_cents"] == 80_000
    assert_employee_share_tracks_money_axis(enrollment)
    assert_persistence(enrollment, 30)
    assert enrollment["persistence_tier"] == PersistenceTier.MEDIUM
    assert_versioned_record(enrollment, expected_version=1)

    employee = s.read_employee()
    assert employee["version"] == 2
    assert_cap_buckets(employee, 80_000, 0, 0, 920_000)
    assert_cap_pool_conserved(employee, 1_000_000)


def test_confirmation_needs_the_listing_to_be_still_curated(api):
    """Suspending the listing blocks confirmation and leaves both axes untouched.

    PRD §3.3: "Suspension is intentionally narrow — enrollments already sitting on
    the listing continue completely unchanged — but a suspended listing can no
    longer be enrolled against and can no longer have a registration confirmed on
    it, and both of those refusals also carry `ERR_LISTING_NOT_CURATED`."

    Design: Corner/state_machines/confirm_registration_precondition_requires_curated_listing
    """
    s = build_vantage_reimbursement_enrolled(api)
    suspended = validate_success(
        api.suspend_catalog_listing(s.listing_id, s.benefit_admin)
    )
    assert suspended["status"] == ListingStatus.SUSPENDED

    validate_error(
        api.confirm_registration(s.enrollment_id, s.school_partner),
        ERR_LISTING_NOT_CURATED,
    )

    enrollment = s.read_enrollment()
    assert_enrollment_axes(
        enrollment, AcademicStatus.REGISTERED, FundingStatus.RESERVED
    )
    assert enrollment["employer_reserved_cents"] == 80_000


def test_approved_exception_request_creates_a_full_price_listing(api):
    """Approval materialises a CURATED listing at the undiscounted list price.

    PRD §3.3: "A `decision` of `APPROVE` moves the request `UNDER_REVIEW →
    APPROVED`, records the supplied note in `decision_note`, and materialises a
    brand-new catalog listing for the requesting employee's employer: `program_id`
    copied from the request, `agreement_id` null because no agreement exists,
    `source_request_id` set to the request's own `id`, `approval_source`
    `APPROVED_EXCEPTION`, `status` `CURATED`,
    `negotiated_tuition_per_credit_cents` equal to the program's
    `list_tuition_per_credit_cents` with no discount applied at all, and
    `allowed_funding_models` containing only `REIMBURSEMENT`."

    Design: Corner/state_machines/approved_non_catalog_request_materialises_exception_listing
    """
    s = build_vantage_exception_path(api)
    request = validate_success(
        api.create_program_approval_request(
            program_approval_request_payload(
                employee_id=s.employee_id,
                program_id=s.program_id,
                justification="The master's credential is required for the lead role.",
                requested_annual_cost_cents=900_000,
            ),
            s.employee,
        ),
        201,
    )
    assert request["status"] == ApprovalRequestStatus.SUBMITTED
    assert request["revision_count"] == 0
    assert request["decision_note"] is None

    reviewed = validate_success(
        api.review_program_approval_request(request["id"], s.benefit_admin)
    )
    assert reviewed["status"] == ApprovalRequestStatus.UNDER_REVIEW

    decided = validate_success(
        api.decide_program_approval_request(
            request["id"],
            approval_decision_payload(
                ApprovalDecision.APPROVE, "Approved as a strategic exception."
            ),
            s.benefit_admin,
        )
    )
    assert decided["status"] == ApprovalRequestStatus.APPROVED
    assert decided["decision_note"] == "Approved as a strategic exception."

    listings, meta = validate_paginated(
        api.list_catalog_listings(
            s.benefit_admin, {"source_request_id": request["id"]}
        )
    )
    assert meta["total_count"] == 1
    listing = listings[0]
    assert listing["program_id"] == s.program_id
    assert listing["agreement_id"] is None
    assert listing["source_request_id"] == request["id"]
    assert listing["approval_source"] == ApprovalSource.APPROVED_EXCEPTION
    assert listing["status"] == ListingStatus.CURATED
    assert listing["negotiated_tuition_per_credit_cents"] == 75_000
    assert listing["allowed_funding_models"] == [FundingModel.REIMBURSEMENT]


def test_an_issued_invoice_cannot_be_paid_before_it_is_approved(api):
    """Disbursement demands APPROVED_FOR_PAYMENT, so paying an ISSUED invoice fails.

    PRD §3.5: "Disbursement requires the invoice to be `APPROVED_FOR_PAYMENT`, the
    enrollment's `academic_status` not to be `WITHDRAWN`, and the enrollment's
    `funding_status` to be `BILLED`."

    Design: Corner/state_machines/paying_an_issued_invoice_before_approval_is_rejected
    """
    s = build_vantage_direct_bill_billed(api)
    invoice = s.first_invoice()
    assert invoice["status"] == InvoiceStatus.ISSUED

    validate_error(
        api.pay_invoice(invoice["id"], s.platform_admin), ERR_INVOICE_INVALID_STATE
    )

    still_issued = s.first_invoice()
    assert still_issued["status"] == InvoiceStatus.ISSUED
    assert still_issued["paid_on"] is None
    assert s.read_enrollment()["funding_status"] == FundingStatus.BILLED

    approved = validate_success(
        api.approve_invoice_for_payment(invoice["id"], s.benefit_admin)
    )
    assert approved["status"] == InvoiceStatus.APPROVED_FOR_PAYMENT

    paid = validate_success(api.pay_invoice(invoice["id"], s.platform_admin))
    assert paid["status"] == InvoiceStatus.PAID
    assert paid["paid_on"] == "2026-08-01"
    assert s.read_enrollment()["funding_status"] == FundingStatus.SETTLED


def test_a_withdrawn_term_refuses_a_later_outcome(api):
    """Withdrawal is terminal on the academic axis and synthesizes its own outcome.

    PRD §3.7: "Withdrawal is the learner's own exit, permitted while the
    enrollment's `academic_status` is either `REGISTERED` or `IN_PROGRESS`; from
    both states the academic axis moves to `WITHDRAWN`, and in both cases an
    `AcademicOutcome` is appended with `completion_status` `WITHDRAWN`,
    `grade_points` null, `credits_earned` 0 and `posted_by_role` `SYSTEM`."

    Design: Corner/state_machines/withdrawn_enrollment_rejects_further_outcome_posting
    """
    s = build_vantage_reimbursement_in_progress(api)
    withdrawn = validate_success(
        api.withdraw_enrollment(s.enrollment_id, s.employee)
    )
    assert_enrollment_axes(
        withdrawn, AcademicStatus.WITHDRAWN, FundingStatus.RELEASED
    )

    outcomes, meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert meta["total_count"] == 1
    assert outcomes[0]["completion_status"] == CompletionStatus.WITHDRAWN
    assert outcomes[0]["grade_points"] is None
    assert outcomes[0]["credits_earned"] == 0
    assert outcomes[0]["posted_by_role"] == PostedByRole.SYSTEM

    validate_error(
        api.create_academic_outcome(
            s.enrollment_id,
            academic_outcome_payload("2026-FA", CompletionStatus.PASSED, 4, 3.60),
            s.school_partner,
        ),
        ERR_ENROLLMENT_INVALID_ACADEMIC_STATE,
    )
    _, meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert meta["total_count"] == 1


def test_activating_an_already_active_policy_is_refused(api):
    """Activation is admissible only from DRAFT, so the second call is refused.

    PRD §3.1: "A `BenefitAdministrator` may activate only a policy that is still
    `DRAFT` — activating one that is already `ACTIVE` or `SUPERSEDED` is rejected
    with `ERR_POLICY_NOT_DRAFT` — only for its own employer, and only when the
    policy's half-open window does not intersect the window of any other `ACTIVE`
    policy of the same employer; overlap is rejected with
    `ERR_POLICY_PERIOD_OVERLAP`, while two windows that merely touch at a boundary
    are explicitly not an overlap."

    Design: Corner/state_machines/second_activation_of_an_active_policy_is_rejected
    """
    s = build_vantage_base(api)
    active = validate_success(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.ACTIVE}
        )
    )
    assert len(active) == 1
    assert active[0]["id"] == s.policy_id

    validate_error(
        api.activate_benefit_policy(s.policy_id, s.benefit_admin),
        ERR_POLICY_NOT_DRAFT,
    )

    _, meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.ACTIVE}
        )
    )
    assert meta["total_count"] == 1
