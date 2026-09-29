"""Policy gates, accreditation gates and uniqueness gates on write paths."""

from test_helpers import (
    AccreditationStatus,
    AgreementStatus,
    CredentialType,
    EligibilityStatus,
    ERR_DUPLICATE_LISTING,
    ERR_NON_CATALOG_APPROVAL_DISABLED,
    ERR_SCHOOL_NOT_ACCREDITED,
    FundingModel,
    JobFamily,
    ListingStatus,
    Scenario,
    SkillTrack,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_versioned_record,
    build_vantage_direct_bill_enrolled,
    catalog_listing_payload,
    program_approval_request_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_policy_that_disables_exceptions_refuses_the_non_catalog_request(api):
    """With non_catalog_approval_required false the exception path is closed.

    PRD §2.9: "The employer's current policy has `non_catalog_approval_required`
    set to true; otherwise `ERR_NON_CATALOG_APPROVAL_DISABLED` (422)."

    Design: Corner/validations/non_catalog_request_rejected_when_policy_disables_approval
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
        non_catalog_approval_required=False,
    )
    policy = s.activate_policy()
    assert policy["non_catalog_approval_required"] is False

    s.register_employee()
    s.register_school()
    s.publish_program(
        name="Master of Science in Food Systems",
        credential_type=CredentialType.MASTER,
        skill_track=SkillTrack.SUPPLY_CHAIN,
        list_tuition_per_credit_cents=75_000,
        total_credits=30,
        term_length_weeks=15,
    )

    employee = s.read_employee()
    assert employee["eligibility_status"] == EligibilityStatus.ELIGIBLE
    assert employee["tenure_months"] == 30

    validate_error(
        api.create_program_approval_request(
            program_approval_request_payload(
                employee_id=s.employee_id,
                program_id=s.program_id,
                justification="The master's credential is required for the lead role.",
                requested_annual_cost_cents=900_000,
            ),
            s.employee,
        ),
        ERR_NON_CATALOG_APPROVAL_DISABLED,
        422,
    )

    _, meta = validate_paginated(
        api.list_program_approval_requests(
            s.benefit_admin, {"employee_id": s.employee_id}
        )
    )
    assert meta["total_count"] == 0


def test_a_hybrid_policy_admits_both_funding_models_on_one_listing(api):
    """One HYBRID employer funds a direct-bill term and a reimbursement term at once.

    PRD §3.3: "The `allowed_funding_models` array is the pair `DIRECT_BILL` and
    `REIMBURSEMENT` when the listing's source is `CATALOG` and the agreement's
    `direct_bill_enabled` is true, and the single-element list containing only
    `REIMBURSEMENT` in every other case."

    PRD §3.4: "When the pinned policy's `funding_model` is `HYBRID`, the
    enrollment's `funding_model` must be supplied and may be either `DIRECT_BILL`
    or `REIMBURSEMENT` — the learner picks per enrollment."

    Design: Corner/validations/hybrid_policy_admits_both_funding_models
    """
    s = build_vantage_direct_bill_enrolled(api)
    listing = s.read_listing()
    assert sorted(listing["allowed_funding_models"]) == [
        FundingModel.DIRECT_BILL,
        FundingModel.REIMBURSEMENT,
    ]

    direct = s.read_enrollment()
    assert direct["funding_model"] == FundingModel.DIRECT_BILL
    assert direct["employer_reserved_cents"] == 160_000

    reimbursement = s.enroll(
        primary=False,
        term_code="2026-WI",
        term_start_date="2026-12-20",
        term_end_date="2027-03-20",
        credits=2,
        funding_model=FundingModel.REIMBURSEMENT,
    )
    assert reimbursement["funding_model"] == FundingModel.REIMBURSEMENT
    assert reimbursement["gross_tuition_cents"] == 80_000
    assert reimbursement["employer_reserved_cents"] == 40_000
    assert reimbursement["employee_share_cents"] == 40_000

    employee = s.read_employee()
    assert_cap_buckets(employee, 200_000, 0, 0, 800_000)
    assert_cap_pool_conserved(employee, 1_000_000)


def test_agreement_activation_is_refused_for_an_unaccredited_school(api):
    """PROBATION activates while UNACCREDITED does not.

    PRD §3.2: "A `BenefitAdministrator` activating its own agreement moves it
    `PENDING → ACTIVE`, provided the agreement is still `PENDING` — otherwise
    `ERR_AGREEMENT_INVALID_STATE` — and provided the school's
    `accreditation_status` is not `UNACCREDITED`; an unaccredited school is
    rejected with `ERR_SCHOOL_NOT_ACCREDITED`. A school on `PROBATION` may be
    activated."

    Design: Corner/validations/agreement_activation_rejected_for_unaccredited_school
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_school(
        legal_name="Northgate Career Academy",
        state_code="NV",
        contact_email="partners@northgate-career.example",
        accreditation_status=AccreditationStatus.UNACCREDITED,
    )
    blocked = s.draft_agreement(
        negotiated_discount_pct=0.10,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    probation_school = s.register_school(
        primary=False,
        legal_name="Sunfield Technical College",
        state_code="AZ",
        contact_email="partners@sunfield-tech.example",
        accreditation_status=AccreditationStatus.PROBATION,
    )
    probation_school_id = probation_school["id"]
    allowed = s.draft_agreement(
        primary=False,
        school_id=probation_school_id,
        negotiated_discount_pct=0.10,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    activated = validate_success(
        api.activate_partner_agreement(allowed["id"], s.benefit_admin)
    )
    assert activated["status"] == AgreementStatus.ACTIVE

    validate_error(
        api.activate_partner_agreement(blocked["id"], s.benefit_admin),
        ERR_SCHOOL_NOT_ACCREDITED,
        422,
    )
    still_pending = s.read_agreement(blocked["id"])
    assert still_pending["status"] == AgreementStatus.PENDING
    assert still_pending["terminated_on"] is None
    assert_versioned_record(still_pending, expected_version=1)

    _, meta = validate_paginated(
        api.list_partner_agreements(
            s.benefit_admin,
            {"employer_id": s.employer_id, "status": AgreementStatus.ACTIVE},
        )
    )
    assert meta["total_count"] == 1


def test_a_second_listing_for_the_same_employer_and_program_is_refused(api):
    """Uniqueness holds while the first listing is CURATED and lifts once suspended.

    PRD §3.3: "Curation is also idempotence-guarded: if a `CURATED` listing, or an
    approval request in `SUBMITTED`, `UNDER_REVIEW` or `CHANGES_REQUESTED`, already
    exists for the same employer-and-program pair, the attempt is rejected with
    `ERR_DUPLICATE_LISTING`."

    Design: Corner/validations/duplicate_listing_blocked_for_same_employer_and_program
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
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
    )
    s.activate_policy()
    s.register_school()
    s.publish_program()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    first = s.curate_listing()
    assert first["status"] == ListingStatus.CURATED

    duplicate = catalog_listing_payload(
        employer_id=s.employer_id,
        program_id=s.program_id,
        agreement_id=s.agreement_id,
        expected_agreement_version=s.agreement_version(),
    )
    validate_error(
        api.create_catalog_listing(duplicate, s.benefit_admin),
        ERR_DUPLICATE_LISTING,
        409,
    )

    _, meta = validate_paginated(
        api.list_catalog_listings(s.benefit_admin, {"employer_id": s.employer_id})
    )
    assert meta["total_count"] == 1

    suspended = validate_success(
        api.suspend_catalog_listing(first["id"], s.benefit_admin)
    )
    assert suspended["status"] == ListingStatus.SUSPENDED

    replacement = validate_success(
        api.create_catalog_listing(
            catalog_listing_payload(
                employer_id=s.employer_id,
                program_id=s.program_id,
                agreement_id=s.agreement_id,
                expected_agreement_version=s.agreement_version(),
            ),
            s.benefit_admin,
        ),
        201,
    )
    assert replacement["status"] == ListingStatus.CURATED
    assert replacement["id"] != first["id"]
