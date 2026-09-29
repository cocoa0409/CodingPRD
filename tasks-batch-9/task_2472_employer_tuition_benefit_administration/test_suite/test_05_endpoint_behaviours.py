"""Action endpoints, the term-close batch and collection filtering."""

from test_helpers import (
    AcademicStatus,
    ClaimDecision,
    ClaimStatus,
    CompletionStatus,
    EligibilityStatus,
    EmploymentStatus,
    ERR_COACHING_HOLD_ACTIVE,
    FundingModel,
    FundingStatus,
    JobFamily,
    PersistenceTier,
    PostedByRole,
    Scenario,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_enrollment_axes,
    assert_persistence,
    assert_term_close_counts,
    assert_tier_bands_score,
    build_vantage_reimbursement_in_progress,
    build_vantage_reimbursement_passed,
    claim_decision_payload,
    employee_patch_payload,
    enrollment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_patching_weekly_hours_recomputes_eligibility_in_both_directions(api):
    """Dropping to 15 hours flips the verdict and restoring 40 flips it back.

    PRD §3.1: "Employment facts change, and a `BenefitAdministrator` may patch
    `weekly_hours`, `job_family`, `employment_status` and `termination_date` on an
    employee. Any such patch recomputes `eligibility_status`; a patch to
    `TERMINATED` yields `INELIGIBLE_EMPLOYMENT` and additionally runs the
    early-departure cascade described in §3.7."

    Design: Corner/endpoints/patch_employee_hours_recomputes_eligibility_both_ways
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
    created = s.register_employee()
    assert created["weekly_hours"] == 40
    assert created["eligibility_status"] == EligibilityStatus.ELIGIBLE
    assert created["version"] == 1

    reduced = validate_success(
        api.patch_employee(
            s.employee_id, employee_patch_payload(weekly_hours=15), s.benefit_admin
        )
    )
    assert reduced["weekly_hours"] == 15
    assert reduced["eligibility_status"] == EligibilityStatus.INELIGIBLE_HOURS
    assert reduced["version"] == 2
    assert reduced["updated_at"] > reduced["created_at"]
    assert reduced["hire_date"] == created["hire_date"]
    assert reduced["tenure_months"] == 30
    assert reduced["cap_available_cents"] == 1_000_000

    restored = validate_success(
        api.patch_employee(
            s.employee_id, employee_patch_payload(weekly_hours=40), s.benefit_admin
        )
    )
    assert restored["weekly_hours"] == 40
    assert restored["eligibility_status"] == EligibilityStatus.ELIGIBLE
    assert restored["version"] == 3
    assert restored["employment_status"] == EmploymentStatus.ACTIVE


def test_term_close_auto_completes_the_term_and_raises_a_coaching_hold(api):
    """A term with no reported outcome closes INCOMPLETE and locks new enrollments.

    PRD §3.9: "Step two closes unreported coursework: every enrollment carrying the
    given `term_code` whose `academic_status` is `IN_PROGRESS` and which has no
    outcome on file at all moves `IN_PROGRESS → INCOMPLETE`, and an outcome row is
    synthesized for it with `completion_status` `INCOMPLETE`, `grade_points` null,
    `credits_earned` 0 and `posted_by_role` `SYSTEM`; these enrollments are
    processed in `created_at` ascending order."

    PRD §3.8: "An employee's `coaching_hold` is true whenever at least one of that
    employee's enrollments has an `academic_status` of `REGISTERED`, `IN_PROGRESS`
    or `INCOMPLETE` together with a `persistence_tier` of `HIGH`, and it is false
    otherwise."

    Design: Corner/endpoints/term_close_auto_completes_and_raises_coaching_hold
    """
    s = build_vantage_reimbursement_in_progress(api)
    s.set_clock("2026-12-20T00:00:00Z")

    report = s.close_term("2026-FA")
    assert_term_close_counts(report, 0, 1, 0, 0, 1)

    enrollment = s.read_enrollment()
    assert_enrollment_axes(
        enrollment, AcademicStatus.INCOMPLETE, FundingStatus.RESERVED
    )
    assert enrollment["credits_earned"] == 0
    assert_persistence(enrollment, 60)
    assert enrollment["persistence_tier"] == PersistenceTier.HIGH
    assert_tier_bands_score(enrollment)

    outcomes, meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert meta["total_count"] == 1
    assert outcomes[0]["completion_status"] == CompletionStatus.INCOMPLETE
    assert outcomes[0]["credits_earned"] == 0
    assert outcomes[0]["grade_points"] is None
    assert outcomes[0]["posted_by_role"] == PostedByRole.SYSTEM

    employee = s.read_employee()
    assert employee["coaching_hold"] is True
    assert employee["cap_reserved_cents"] == 80_000

    validate_error(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=employee["version"],
                term_code="2027-SP",
                term_start_date="2027-01-10",
                term_end_date="2027-04-20",
                credits=4,
                funding_model=FundingModel.REIMBURSEMENT,
            ),
            s.employee,
        ),
        ERR_COACHING_HOLD_ACTIVE,
    )


def test_rejecting_a_claim_releases_the_reserve_without_disbursing(api):
    """A rejected claim zeroes the money axis and returns the whole cap pool.

    PRD §3.6: "On a `decision` of `REJECT`, the claim moves `SUBMITTED →
    REJECTED`, the supplied note is recorded in `decision_note`,
    `approved_amount_cents` stays 0 and `platform_admin_fee_cents` stays 0. The
    enrollment's money axis moves `RESERVED → RELEASED`, and the employee's
    `cap_reserved_cents` and `cap_available_cents` are recomputed so the headroom
    returns to the pool. No tax ledger entry is appended on this branch, and no
    employer roll-up changes."

    Design: Corner/endpoints/claim_rejection_releases_reserve_without_disbursing
    """
    s = build_vantage_reimbursement_passed(api)
    s.file_claim(160_000, "CVC-2026FA-RDELGADO-REJECTED")

    claim = validate_success(
        api.decide_reimbursement_claim(
            s.claim_id,
            claim_decision_payload(
                ClaimDecision.REJECT, "Receipt does not match the enrolled term."
            ),
            s.benefit_admin,
        )
    )
    assert claim["status"] == ClaimStatus.REJECTED
    assert claim["approved_amount_cents"] == 0
    assert claim["platform_admin_fee_cents"] == 0
    assert claim["decision_note"] == "Receipt does not match the enrolled term."

    enrollment = s.read_enrollment()
    assert_enrollment_axes(enrollment, AcademicStatus.PASSED, FundingStatus.RELEASED)
    assert enrollment["employer_settled_cents"] == 0
    assert enrollment["employer_disbursed_cents"] == 0
    assert enrollment["employee_share_cents"] == 160_000

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 0, 0, 1_000_000)
    assert_cap_pool_conserved(employee, 1_000_000)

    _, meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id}
        )
    )
    assert meta["total_count"] == 0

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 0
    assert employer["total_admin_fee_cents"] == 0


def test_the_enrollment_collection_filters_by_academic_status_and_pages(api):
    """One confirmed and one registered term separate by filter and by page.

    PRD §3.4: "Enrollments can be listed and filtered by `employee_id`,
    `catalog_listing_id`, `policy_id`, `term_code`, `academic_status` and
    `funding_status`, and a single read returns both status axes together with
    every money field."

    Design: Corner/endpoints/enrollment_listing_filters_by_academic_status_and_paginates
    """
    s = build_vantage_reimbursement_in_progress(api)
    first_id = s.enrollment_id
    second = s.enroll(
        primary=False,
        term_code="2026-WI",
        term_start_date="2026-12-20",
        term_end_date="2027-03-20",
        credits=2,
        funding_model=FundingModel.REIMBURSEMENT,
    )

    registered, meta = validate_paginated(
        api.list_enrollments(
            s.benefit_admin, {"academic_status": AcademicStatus.REGISTERED}
        )
    )
    assert meta["total_count"] == 1
    assert registered[0]["id"] == second["id"]

    in_progress, meta = validate_paginated(
        api.list_enrollments(
            s.benefit_admin, {"academic_status": AcademicStatus.IN_PROGRESS}
        )
    )
    assert meta["total_count"] == 1
    assert in_progress[0]["id"] == first_id

    page_one, meta = validate_paginated(
        api.list_enrollments(
            s.benefit_admin, {"employee_id": s.employee_id, "limit": 1, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert [row["id"] for row in page_one] == [first_id]

    page_two, meta = validate_paginated(
        api.list_enrollments(
            s.benefit_admin, {"employee_id": s.employee_id, "limit": 1, "offset": 1}
        )
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert [row["id"] for row in page_two] == [second["id"]]
