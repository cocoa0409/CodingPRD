"""Admissibility that lives on another entity, and intervals that share a day."""

from test_helpers import (
    AcademicStatus,
    AgreementStatus,
    ApprovalSource,
    BenefitPolicyStatus,
    ClaimDecision,
    ClaimStatus,
    CompletionStatus,
    ERR_ACADEMIC_PROGRESS_NOT_MET,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_CONCURRENT_CREDIT_LIMIT,
    ERR_ENROLLMENT_INVALID_ACADEMIC_STATE,
    ERR_POLICY_PERIOD_OVERLAP,
    FundingModel,
    FundingStatus,
    JobFamily,
    ListingStatus,
    academic_outcome_payload,
    benefit_policy_payload,
    build_meridian_pending_agreement,
    build_northwind_base,
    build_northwind_six_credit_enrolled,
    build_northwind_three_credit_in_progress,
    catalog_listing_payload,
    enrollment_payload,
    reimbursement_claim_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_same_curation_body_fails_on_pending_and_succeeds_on_active(api):
    """One request body, two verdicts, decided entirely by the agreement's status.

    PRD §3.2: "A new agreement's `status` is `PENDING` and its `terminated_on` is null;
    both are system-managed."

    PRD §3.3: "The referenced agreement must have `status` `ACTIVE`, must actually join
    the supplied employer to the school that offers the supplied program, and must have a
    non-empty coverage window; a failure on any of those three counts is
    `ERR_AGREEMENT_NOT_ACTIVE`."

    PRD §3.3: "A curated listing records `approval_source` `CATALOG`, `status` `CURATED`,
    and a null `source_request_id`, and it freezes two computed values."

    Design: Difficulty/cross_entity_state_dependency/catalog_listing_creation_gated_by_partner_agreement_lifecycle
    """
    s = build_meridian_pending_agreement(api)
    pending = s.read_agreement()
    assert pending["status"] == AgreementStatus.PENDING
    assert pending["terminated_on"] is None

    validate_error(
        api.create_catalog_listing(
            catalog_listing_payload(
                employer_id=s.employer_id,
                program_id=s.program_id,
                agreement_id=s.agreement_id,
                expected_agreement_version=pending["version"],
            ),
            s.benefit_admin,
        ),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )
    _, empty_meta = validate_paginated(
        api.list_catalog_listings(s.benefit_admin, {"employer_id": s.employer_id})
    )
    assert empty_meta["total_count"] == 0

    activated = s.activate_agreement()
    assert activated["status"] == AgreementStatus.ACTIVE

    listing = validate_success(
        api.create_catalog_listing(
            catalog_listing_payload(
                employer_id=s.employer_id,
                program_id=s.program_id,
                agreement_id=s.agreement_id,
                expected_agreement_version=activated["version"],
            ),
            s.benefit_admin,
        ),
        201,
    )
    assert listing["approval_source"] == ApprovalSource.CATALOG
    assert listing["status"] == ListingStatus.CURATED
    assert listing["source_request_id"] is None
    assert listing["negotiated_tuition_per_credit_cents"] == 27_000


def test_terminating_the_agreement_suspends_one_listing_and_refuses_the_next(api):
    """The gate closes again from the other side, and the curated listing goes quiet.

    PRD §3.2: "On success the agreement moves `ACTIVE → TERMINATED`, `terminated_on` is
    stamped with the logical clock date, and `version` is incremented by 1."

    PRD §3.2: "Then, in order: every `CatalogListing` under this agreement whose `status`
    is `CURATED` moves to `SUSPENDED`, processed in `created_at` ascending order."

    PRD §2.9: "The referenced agreement has `status` `ACTIVE`, joins the supplied
    `employer_id` to the school of the supplied `program_id`, and has a non-empty
    coverage window; otherwise `ERR_AGREEMENT_NOT_ACTIVE` (409). Applies to
    `POST /catalog-listings`."

    Design: Difficulty/cross_entity_state_dependency/catalog_listing_creation_gated_by_partner_agreement_lifecycle
    """
    s = build_meridian_pending_agreement(api)
    s.activate_agreement()
    s.curate_listing()

    terminated = validate_success(
        api.terminate_partner_agreement(s.agreement_id, s.benefit_admin)
    )
    assert terminated["status"] == AgreementStatus.TERMINATED
    assert terminated["terminated_on"] == "2026-08-01"
    assert s.read_listing()["status"] == ListingStatus.SUSPENDED

    validate_error(
        api.create_catalog_listing(
            catalog_listing_payload(
                employer_id=s.employer_id,
                program_id=s.second_program_id,
                agreement_id=s.agreement_id,
                expected_agreement_version=terminated["version"],
            ),
            s.benefit_admin,
        ),
        ERR_AGREEMENT_NOT_ACTIVE,
        409,
    )
    _, meta = validate_paginated(
        api.list_catalog_listings(s.benefit_admin, {"employer_id": s.employer_id})
    )
    assert meta["total_count"] == 1


def test_a_claim_is_refused_until_a_clearing_outcome_exists_to_admit_it(api):
    """An in-progress term blocks the claim, and a 1.80 pass never becomes an outcome.

    PRD §2.9: "The enrollment's `academic_status` admits the operation — `REGISTERED` to
    confirm registration, `IN_PROGRESS` to post an outcome, `PASSED` to file a claim,
    `REGISTERED` or `IN_PROGRESS` to withdraw, `REGISTERED` or `IN_PROGRESS` to approve
    its invoice for payment; otherwise `ERR_ENROLLMENT_INVALID_ACADEMIC_STATE` (409)."

    PRD §3.6: "A `PASSED` outcome must additionally clear the pinned policy's
    `min_passing_grade_points`: `grade_points` below that floor is refused with
    `ERR_ACADEMIC_PROGRESS_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/reimbursement_claim_gated_by_enrollment_outcome_state
    """
    s = build_northwind_three_credit_in_progress(api)

    validate_error(
        api.create_reimbursement_claim(
            s.enrollment_id,
            reimbursement_claim_payload(92_256, "CSU-2026FA-DOKAFOR-EARLY"),
            s.employee,
        ),
        ERR_ENROLLMENT_INVALID_ACADEMIC_STATE,
        409,
    )
    _, claims_meta = validate_paginated(
        api.list_reimbursement_claims(s.enrollment_id, s.employee)
    )
    assert claims_meta["total_count"] == 0

    s.set_clock("2026-12-20T00:00:00Z")
    validate_error(
        api.create_academic_outcome(
            s.enrollment_id,
            academic_outcome_payload("2026-FA", CompletionStatus.PASSED, 3, 1.80),
            s.school_partner,
        ),
        ERR_ACADEMIC_PROGRESS_NOT_MET,
        422,
    )
    _, outcomes_meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert outcomes_meta["total_count"] == 0
    assert s.read_enrollment()["academic_status"] == AcademicStatus.IN_PROGRESS


def test_the_admitting_outcome_also_fixes_what_the_claim_is_worth(api):
    """A 2.50 pass opens the path and, being under 3.50, keeps the award at 55,354.

    PRD §3.6: "Filing requires the enrollment's `academic_status` to be `PASSED`, its
    `funding_status` to be `RESERVED`, and its `funding_model` to be `REIMBURSEMENT` —
    filing against a direct-bill enrollment is refused with
    `ERR_REIMBURSEMENT_NOT_ALLOWED` — and the enrollment's latest outcome must have
    `completion_status` `PASSED` with `grade_points` at least the policy's
    `min_passing_grade_points`, or the filing is refused with
    `ERR_ACADEMIC_PROGRESS_NOT_MET`."

    PRD §3.6: "A filed claim records its `enrollment_id`, starts with `status`
    `SUBMITTED`, `approved_amount_cents` 0, `platform_admin_fee_cents` 0 and a null
    `decision_note`."

    Design: Difficulty/cross_entity_state_dependency/reimbursement_claim_gated_by_enrollment_outcome_state
    """
    s = build_northwind_three_credit_in_progress(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.PASSED, 3, 2.50)

    passed = s.read_enrollment()
    assert passed["academic_status"] == AcademicStatus.PASSED
    assert passed["credits_earned"] == 3
    assert passed["funding_status"] == FundingStatus.RESERVED

    claim = validate_success(
        api.create_reimbursement_claim(
            s.enrollment_id,
            reimbursement_claim_payload(92_256, "CSU-2026FA-DOKAFOR-01"),
            s.employee,
        ),
        201,
    )
    s.claim_id = claim["id"]
    assert claim["enrollment_id"] == s.enrollment_id
    assert claim["status"] == ClaimStatus.SUBMITTED
    assert claim["amount_requested_cents"] == 92_256
    assert claim["approved_amount_cents"] == 0
    assert claim["platform_admin_fee_cents"] == 0
    assert claim["decision_note"] is None

    decided = s.decide_claim(ClaimDecision.APPROVE)
    assert decided["approved_amount_cents"] == 55_354
    assert decided["approved_amount_cents"] != 64_579
    assert decided["platform_admin_fee_cents"] == 2_768


def test_a_successor_window_starting_where_the_incumbent_ends_activates(api):
    """Half-open windows that merely touch at 2027-07-01 leave two policies ACTIVE.

    PRD §3.1: "A `BenefitAdministrator` may activate only a policy that is still `DRAFT`
    — activating one that is already `ACTIVE` or `SUPERSEDED` is rejected with
    `ERR_POLICY_NOT_DRAFT` — only for its own employer, and only when the policy's
    half-open window does not intersect the window of any other `ACTIVE` policy of the
    same employer; overlap is rejected with `ERR_POLICY_PERIOD_OVERLAP`, while two
    windows that merely touch at a boundary are explicitly not an overlap."

    PRD §3.1: "The policy's owning employer is recorded as `employer_id`, and the
    collection of an employer's versions can be filtered by `status`."

    Design: Difficulty/resource_temporal_overlap/benefit_policy_half_open_windows_allow_adjacency_reject_one_day_overlap
    """
    s = build_northwind_base(api)
    successor = s.draft_policy(
        primary=False,
        effective_from="2027-07-01",
        effective_to="2028-07-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.RETAIL_FRONTLINE, JobFamily.OPERATIONS],
        annual_cap_cents=650_000,
        funding_model=FundingModel.REIMBURSEMENT,
        reimbursement_pct=0.60,
        max_concurrent_credits=9,
        drop_window_days=14,
        service_commitment_months=12,
    )
    assert successor["status"] == BenefitPolicyStatus.DRAFT

    activated = validate_success(
        api.activate_benefit_policy(successor["id"], s.benefit_admin)
    )
    assert activated["status"] == BenefitPolicyStatus.ACTIVE
    assert activated["effective_from"] == "2027-07-01"

    _, active_meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.ACTIVE}
        )
    )
    assert active_meta["total_count"] == 2


def test_a_window_overlapping_one_single_day_of_the_incumbent_is_refused(api):
    """[2027-06-30, 2027-07-01) touches the successor but bites the incumbent's last day.

    PRD §2.9: "The activating policy's half-open window does not intersect the window of
    any other policy of the same employer whose `status` is `ACTIVE`, where two windows
    that merely touch — one's `effective_to` equal to the other's `effective_from` — do
    not intersect; otherwise `ERR_POLICY_PERIOD_OVERLAP` (409). Applies to
    `POST /benefit-policies/{id}/activate`."

    PRD §3.1: "A freshly drafted policy always has `status` `DRAFT` — the field is
    system-managed and cannot be supplied — and drafting recomputes nothing; no
    employee's eligibility changes while a policy sits in draft."

    Design: Difficulty/resource_temporal_overlap/benefit_policy_half_open_windows_allow_adjacency_reject_one_day_overlap
    """
    s = build_northwind_base(api)
    successor = s.draft_policy(
        primary=False,
        effective_from="2027-07-01",
        effective_to="2028-07-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.RETAIL_FRONTLINE, JobFamily.OPERATIONS],
        annual_cap_cents=650_000,
        funding_model=FundingModel.REIMBURSEMENT,
        reimbursement_pct=0.60,
        max_concurrent_credits=9,
        drop_window_days=14,
        service_commitment_months=12,
    )
    s.activate_policy(successor["id"])

    straddler = validate_success(
        api.create_benefit_policy(
            s.employer_id,
            benefit_policy_payload(
                effective_from="2027-06-30",
                effective_to="2027-07-01",
                min_tenure_months=6,
                min_weekly_hours=20,
                eligible_job_families=[JobFamily.RETAIL_FRONTLINE],
                annual_cap_cents=100_000,
                funding_model=FundingModel.REIMBURSEMENT,
                reimbursement_pct=0.60,
                max_concurrent_credits=9,
                drop_window_days=14,
                service_commitment_months=12,
            ),
            s.benefit_admin,
        ),
        201,
    )
    validate_error(
        api.activate_benefit_policy(straddler["id"], s.benefit_admin),
        ERR_POLICY_PERIOD_OVERLAP,
        409,
    )

    drafts, draft_meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.DRAFT}
        )
    )
    assert draft_meta["total_count"] == 1
    assert drafts[0]["id"] == straddler["id"]

    _, active_meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.ACTIVE}
        )
    )
    assert active_meta["total_count"] == 2


def test_one_shared_calendar_day_makes_the_credit_sums_add_up(api):
    """Six credits ending 2026-12-15 plus four starting 2026-12-15 is ten, over nine.

    PRD §3.4: "The concurrent-credit ceiling is then checked: the system sums `credits`
    across the employee's enrollments whose `academic_status` is `REGISTERED` or
    `IN_PROGRESS` and whose closed term interval shares at least one calendar day with
    the new term's closed interval — a single shared day is an overlap — adds the new
    enrollment's own `credits`, and refuses with `ERR_CONCURRENT_CREDIT_LIMIT` when that
    total exceeds the policy's `max_concurrent_credits`."

    Design: Difficulty/resource_temporal_overlap/employee_concurrent_credit_ceiling_counts_shared_end_day
    """
    s = build_northwind_six_credit_enrolled(api)
    first = s.read_enrollment()
    assert first["credits"] == 6
    assert first["gross_tuition_cents"] == 184_512
    assert first["employer_reserved_cents"] == 110_707

    validate_error(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=s.employee_version(),
                term_code="2026-WI",
                term_start_date="2026-12-15",
                term_end_date="2027-03-30",
                credits=4,
            ),
            s.employee,
        ),
        ERR_CONCURRENT_CREDIT_LIMIT,
        422,
    )
    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 1


def test_starting_one_day_past_the_shared_day_clears_the_ceiling(api):
    """[2026-12-16, 2027-03-30] intersects nothing, so four more credits are funded.

    PRD §3.4: "`gross_tuition_cents` is the listing's already-rounded
    `negotiated_tuition_per_credit_cents` multiplied by the enrollment's `credits`."

    PRD §2.6: "`cap_available_cents` is the governing policy's `annual_cap_cents` minus
    the reserved bucket minus the disbursed bucket minus the clawback-hold bucket."

    Design: Difficulty/resource_temporal_overlap/employee_concurrent_credit_ceiling_counts_shared_end_day
    """
    s = build_northwind_six_credit_enrolled(api)
    second = validate_success(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=s.employee_version(),
                term_code="2026-WI",
                term_start_date="2026-12-16",
                term_end_date="2027-03-30",
                credits=4,
            ),
            s.employee,
        ),
        201,
    )
    assert second["gross_tuition_cents"] == 123_008
    assert second["employer_reserved_cents"] == 73_805

    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 2

    employee = s.read_employee()
    assert employee["cap_reserved_cents"] == 184_512
    assert employee["cap_available_cents"] == 415_488
