"""Resource shapes, declared defaults and derived fields on first read."""

from test_helpers import (
    NON_EXISTENT_UUID,
    AccreditationStatus,
    AgreementStatus,
    BenefitPolicyStatus,
    CompletionStatus,
    DEFAULT_MIN_PASSING_GRADE_POINTS,
    EligibilityStatus,
    EmployerStatus,
    ERR_ENROLLMENT_INVALID_ACADEMIC_STATE,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    FundingModel,
    JobFamily,
    Scenario,
    TaxEntryType,
    academic_outcome_payload,
    assert_append_only_record,
    assert_cap_buckets,
    assert_error_envelope,
    assert_pagination_meta,
    assert_versioned_record,
    benefit_policy_payload,
    build_vantage_direct_bill_paid,
    employee_payload,
    employer_payload,
    make_benefit_administrator_headers,
    partner_agreement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_employer_onboarding_zeroes_the_three_rollups(api):
    """Onboarding an employer defaults status to ACTIVE and zeroes every roll-up.

    PRD §3.1: "The three reporting roll-ups on the employer record —
    `total_disbursed_cents`, `total_admin_fee_cents` and
    `total_imputed_income_cents` — are all initialised to 0 at onboarding and are
    thereafter derived rather than written."

    Design: Corner/entities/employer_creation_returns_zeroed_rollups_and_default_status
    """
    s = Scenario(api)
    response = api.create_employer(
        employer_payload(
            legal_name="Vantage Foods Group",
            benefit_admin_contact_email="benefits@vantage-foods.example",
            fiscal_year_start_month=1,
        ),
        s.platform_admin,
    )
    employer = validate_success(response, 201)

    assert employer["legal_name"] == "Vantage Foods Group"
    assert employer["benefit_admin_contact_email"] == "benefits@vantage-foods.example"
    assert employer["fiscal_year_start_month"] == 1
    assert employer["status"] == EmployerStatus.ACTIVE
    assert employer["total_disbursed_cents"] == 0
    assert employer["total_admin_fee_cents"] == 0
    assert employer["total_imputed_income_cents"] == 0
    assert_versioned_record(employer, expected_version=1)


def test_drafted_agreement_reads_back_pending_with_its_window(api):
    """A freshly drafted agreement is PENDING with a null terminated_on.

    PRD §3.2: "A new agreement's `status` is `PENDING` and its `terminated_on` is
    null; both are system-managed."

    Design: Corner/entities/partner_agreement_retrieval_returns_stored_window_and_pending_status
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_school(
        legal_name="Cascade Valley College",
        state_code="WA",
        contact_email="partners@cascadevalley.example",
    )
    created = validate_success(
        api.create_partner_agreement(
            partner_agreement_payload(
                employer_id=s.employer_id,
                school_id=s.school_id,
                negotiated_discount_pct=0.20,
                direct_bill_enabled=True,
                effective_from="2026-01-01",
                effective_to="2026-12-31",
            ),
            s.platform_admin,
        ),
        201,
    )

    agreement = validate_success(
        api.get_partner_agreement(created["id"], s.platform_admin)
    )
    assert agreement["employer_id"] == s.employer_id
    assert agreement["school_id"] == s.school_id
    assert agreement["status"] == AgreementStatus.PENDING
    assert agreement["terminated_on"] is None
    assert agreement["negotiated_discount_pct"] == 0.20
    assert agreement["direct_bill_enabled"] is True
    assert agreement["effective_from"] == "2026-01-01"
    assert agreement["effective_to"] == "2026-12-31"
    assert_versioned_record(agreement, expected_version=1)


def test_policy_versions_filter_by_status_and_window(api):
    """An employer's policy versions filter by status and page in created_at order.

    PRD §3.1: "The policy's owning employer is recorded as `employer_id`, and the
    collection of an employer's versions can be filtered by `status`."

    Design: Corner/entities/benefit_policy_listing_filters_by_status_and_paginates
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    first = s.draft_policy(effective_from="2026-01-01", effective_to="2027-01-01")
    second = s.draft_policy(
        primary=False, effective_from="2027-01-01", effective_to="2028-01-01"
    )
    third = s.draft_policy(
        primary=False, effective_from="2028-01-01", effective_to="2029-01-01"
    )
    s.activate_policy(first["id"])

    everything, meta = validate_paginated(
        api.list_benefit_policies(s.employer_id, s.benefit_admin)
    )
    assert_pagination_meta(meta, 10, 0, 3, False)
    assert [row["id"] for row in everything] == [first["id"], second["id"], third["id"]]

    active, meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.ACTIVE}
        )
    )
    assert_pagination_meta(meta, 10, 0, 1, False)
    assert active[0]["id"] == first["id"]

    drafts, meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id,
            s.benefit_admin,
            {"status": BenefitPolicyStatus.DRAFT, "limit": 1, "offset": 0},
        )
    )
    assert_pagination_meta(meta, 1, 0, 2, True)
    assert [row["id"] for row in drafts] == [second["id"]]


def test_unknown_enrollment_id_is_its_own_not_found(api):
    """A path enrollment that names nothing yields the enrollment's own 404.

    PRD §2.9: "The `Enrollment` named in the path exists; otherwise
    `ERR_ENROLLMENT_NOT_FOUND` (404)."

    Design: Corner/entities/enrollment_fetch_with_unknown_uuid_returns_enrollment_not_found
    """
    headers = make_benefit_administrator_headers(NON_EXISTENT_UUID)
    response = api.get_enrollment(NON_EXISTENT_UUID, headers)

    validate_error(response, ERR_ENROLLMENT_NOT_FOUND)
    assert_error_envelope(response.json())


def test_policy_draft_without_annual_cap_is_a_schema_violation(api):
    """A draft missing the required annual_cap_cents is refused and nothing persists.

    PRD §2.9: "Schema — required fields present, types and enum members valid, ISO
    dates parseable, `credits` between 1 and 30 inclusive, amount fields at least
    1, `effective_to` strictly after `effective_from`, `term_end_date` strictly
    after `term_start_date`, `grade_points` supplied exactly when
    `completion_status` is `PASSED` or `FAILED`, `termination_date` supplied
    exactly when `employment_status` is being set to `TERMINATED`, `limit` between
    1 and 100 inclusive, `offset` at least 0; otherwise `ERR_INVALID_REQUEST`
    (400)."

    Design: Corner/entities/benefit_policy_draft_missing_annual_cap_is_rejected
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )

    payload = benefit_policy_payload()
    payload.pop("annual_cap_cents")
    validate_error(
        api.create_benefit_policy(s.employer_id, payload, s.benefit_admin),
        ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(
        api.list_benefit_policies(s.employer_id, s.benefit_admin)
    )
    assert meta["total_count"] == 0


def test_policy_optional_flags_take_their_declared_defaults(api):
    """Omitting both optional policy flags yields 2.00 and true.

    PRD §3.1: "Two further fields are optional: `min_passing_grade_points`, which
    defaults to 2.00 and sets the grade-point floor for a term to count as
    academic progress, and `non_catalog_approval_required`, which defaults to true
    and, when false, closes the non-catalog exception path entirely."

    Design: Corner/entities/benefit_policy_omitted_optional_flags_take_declared_defaults
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )

    payload = benefit_policy_payload(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
    )
    assert "min_passing_grade_points" not in payload
    assert "non_catalog_approval_required" not in payload

    policy = validate_success(
        api.create_benefit_policy(s.employer_id, payload, s.benefit_admin), 201
    )
    assert policy["min_passing_grade_points"] == DEFAULT_MIN_PASSING_GRADE_POINTS
    assert policy["non_catalog_approval_required"] is True
    assert policy["status"] == BenefitPolicyStatus.DRAFT
    assert policy["employer_id"] == s.employer_id
    assert_versioned_record(policy, expected_version=1)


def test_tenure_and_eligibility_are_computed_from_the_clock_and_policy(api):
    """Three learners under one policy get three different derived verdicts.

    PRD §3.1: "Tenure is derived, never supplied: `tenure_months` counts the whole
    months from `hire_date` to the logical clock date, where a month completes
    once the day-of-month is reached or passed."

    Design: Corner/entities/employee_tenure_and_eligibility_are_derived_not_supplied
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

    rosa = validate_success(
        api.create_employee(
            s.employer_id,
            employee_payload(
                full_name="Rosa Delgado",
                work_email="rosa.delgado@vantage-foods.example",
                hire_date="2024-01-15",
                weekly_hours=40,
                job_family=JobFamily.OPERATIONS,
            ),
            s.benefit_admin,
        ),
        201,
    )
    owen = validate_success(
        api.create_employee(
            s.employer_id,
            employee_payload(
                full_name="Owen Kaur",
                work_email="owen.kaur@vantage-foods.example",
                hire_date="2024-01-15",
                weekly_hours=12,
                job_family=JobFamily.OPERATIONS,
            ),
            s.benefit_admin,
        ),
        201,
    )
    mira = validate_success(
        api.create_employee(
            s.employer_id,
            employee_payload(
                full_name="Mira Vance",
                work_email="mira.vance@vantage-foods.example",
                hire_date="2024-01-15",
                weekly_hours=40,
                job_family=JobFamily.CORPORATE,
            ),
            s.benefit_admin,
        ),
        201,
    )

    assert rosa["tenure_months"] == 30
    assert rosa["eligibility_status"] == EligibilityStatus.ELIGIBLE
    assert_cap_buckets(rosa, 0, 0, 0, 1_000_000)

    assert owen["tenure_months"] == 30
    assert owen["eligibility_status"] == EligibilityStatus.INELIGIBLE_HOURS

    assert mira["tenure_months"] == 30
    assert mira["eligibility_status"] == EligibilityStatus.INELIGIBLE_JOB_FAMILY

    for employee in (rosa, owen, mira):
        assert employee["cap_plan_year"] == 2026
        assert employee["cap_reserved_cents"] == 0
        assert employee["cap_disbursed_cents"] == 0
        assert employee["cap_clawback_hold_cents"] == 0
        assert employee["taxable_excluded_cents_ytd"] == 0
        assert employee["imputed_income_cents_ytd"] == 0
        assert employee["open_repayment_balance_cents"] == 0
        assert employee["coaching_hold"] is False


def test_negotiated_discount_above_the_ceiling_is_refused(api):
    """0.61 is out of range while 0.60 is exactly on the inclusive ceiling.

    PRD §2.5: "`negotiated_discount_pct` accepts at most four decimal places and
    must be at least 0 and at most 0.60"

    Design: Corner/entities/partner_agreement_discount_above_sixty_percent_is_rejected
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_school(
        legal_name="Cascade Valley College",
        state_code="WA",
        contact_email="partners@cascadevalley.example",
        accreditation_status=AccreditationStatus.ACCREDITED,
    )

    validate_error(
        api.create_partner_agreement(
            partner_agreement_payload(
                employer_id=s.employer_id,
                school_id=s.school_id,
                negotiated_discount_pct=0.61,
                effective_from="2026-01-01",
                effective_to="2026-12-31",
            ),
            s.platform_admin,
        ),
        ERR_INVALID_REQUEST,
    )
    _, meta = validate_paginated(
        api.list_partner_agreements(s.platform_admin, {"employer_id": s.employer_id})
    )
    assert meta["total_count"] == 0

    accepted = validate_success(
        api.create_partner_agreement(
            partner_agreement_payload(
                employer_id=s.employer_id,
                school_id=s.school_id,
                negotiated_discount_pct=0.60,
                effective_from="2026-01-01",
                effective_to="2026-12-31",
            ),
            s.platform_admin,
        ),
        201,
    )
    assert accepted["negotiated_discount_pct"] == 0.60


def test_outcome_and_ledger_rows_have_no_version_and_cannot_be_overwritten(api):
    """History rows carry only id and created_at, and a term cannot be re-reported.

    PRD §2.4: "Three record types are append-only history and therefore carry only
    `id` and `created_at` — they have no `updated_at` and no `version` field at
    all: `AcademicOutcome`, `TaxLedgerEntry` and `CoachingSession`."

    Design: Corner/entities/academic_outcome_and_tax_ledger_entry_are_append_only
    """
    s = build_vantage_direct_bill_paid(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.PASSED, 4, 3.60)

    outcomes, meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert meta["total_count"] == 1
    assert_append_only_record(outcomes[0])
    assert outcomes[0]["posted_on"] == "2026-12-20"
    assert outcomes[0]["completion_status"] == CompletionStatus.PASSED

    entries, meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"enrollment_id": s.enrollment_id}
        )
    )
    assert meta["total_count"] == 1
    assert_append_only_record(entries[0])
    assert entries[0]["entry_type"] == TaxEntryType.BENEFIT

    validate_error(
        api.create_academic_outcome(
            s.enrollment_id,
            academic_outcome_payload("2026-FA", CompletionStatus.PASSED, 4, 3.90),
            s.school_partner,
        ),
        ERR_ENROLLMENT_INVALID_ACADEMIC_STATE,
    )
    still_one, meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert meta["total_count"] == 1
    assert still_one[0]["id"] == outcomes[0]["id"]
