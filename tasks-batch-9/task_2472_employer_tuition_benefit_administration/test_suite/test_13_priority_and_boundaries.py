"""Which rule answers when two fire at once, and what happens exactly at a limit."""

from test_helpers import (
    BenefitPolicyStatus,
    CredentialType,
    EligibilityStatus,
    ERR_ANNUAL_CAP_EXCEEDED,
    ERR_EMPLOYEE_TENURE_NOT_MET,
    ERR_LISTING_NOT_CURATED,
    FundingModel,
    JobFamily,
    ListingStatus,
    Scenario,
    SkillTrack,
    TaxEntryType,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_ledger_row,
    build_beacon_second_term_billed,
    build_cobalt_successor_policy,
    build_harborview_cap_exhausted,
    enrollment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_exhausted_annual_cap_refuses_an_enrollment_on_its_own(api):
    """The control: four credits eat the whole 120,000 pool, so listing B is refused.

    PRD §3.4: "Finally, `cap_available_cents` must be strictly greater than 0, or
    `ERR_ANNUAL_CAP_EXCEEDED` is returned; positive-but-insufficient headroom is
    explicitly allowed and simply yields partial coverage."

    PRD §2.9: "The employee's `cap_available_cents` is greater than 0; otherwise
    `ERR_ANNUAL_CAP_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_listing_state_error_outranks_exhausted_annual_cap
    """
    s = build_harborview_cap_exhausted(api)

    first = s.read_enrollment(s.first_enrollment_id)
    assert first["gross_tuition_cents"] == 120_000
    assert first["employer_reserved_cents"] == 120_000

    employee = s.read_employee()
    assert_cap_buckets(employee, 120_000, 0, 0, 0)
    assert_cap_pool_conserved(employee, 120_000)

    validate_error(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.second_listing_id,
                expected_employee_version=employee["version"],
                term_code="2026-WI",
                term_start_date="2026-12-20",
                term_end_date="2027-03-20",
                credits=1,
            ),
            s.employee,
        ),
        ERR_ANNUAL_CAP_EXCEEDED,
        422,
    )
    assert s.read_listing(s.second_listing_id)["status"] == ListingStatus.CURATED


def test_the_suspended_listing_answers_before_the_exhausted_cap(api):
    """Priority 21 outranks priority 44 on a request that violates both.

    PRD §2.9: "When a single request violates several rules at once, the response
    reports exactly one error: the one belonging to the lowest-numbered rule in the
    ordering below."

    PRD §2.9: "The target or referenced listing's `status` is `CURATED`; otherwise
    `ERR_LISTING_NOT_CURATED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/suspended_listing_state_error_outranks_exhausted_annual_cap
    """
    s = build_harborview_cap_exhausted(api)
    suspended = validate_success(
        api.suspend_catalog_listing(s.listing_id, s.benefit_admin)
    )
    assert suspended["status"] == ListingStatus.SUSPENDED

    employee = s.read_employee()
    assert employee["cap_available_cents"] == 0

    validate_error(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=employee["version"],
                term_code="2026-WI",
                term_start_date="2026-12-20",
                term_end_date="2027-03-20",
                credits=1,
            ),
            s.employee,
        ),
        ERR_LISTING_NOT_CURATED,
        409,
    )

    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 1


def test_adjacent_policy_windows_hand_over_without_repointing_the_enrollment(api):
    """P2 activates alongside P1 and raises the tenure floor from 6 months to 36.

    PRD §3.1: "A `BenefitAdministrator` may activate only a policy that is still
    `DRAFT` — activating one that is already `ACTIVE` or `SUPERSEDED` is rejected with
    `ERR_POLICY_NOT_DRAFT` — only for its own employer, and only when the policy's
    half-open window does not intersect the window of any other `ACTIVE` policy of the
    same employer; overlap is rejected with `ERR_POLICY_PERIOD_OVERLAP`, while two
    windows that merely touch at a boundary are explicitly not an overlap."

    PRD §3.1: "Enrollments that already exist are deliberately left alone: each keeps
    the `policy_id` it pinned at creation and every money field it has already
    computed."

    Design: Difficulty/priority_pair_validation_conflict/tenure_shortfall_outranks_concurrent_credit_overlap
    """
    s = build_cobalt_successor_policy(api)

    first = s.read_enrollment(s.first_enrollment_id)
    assert first["gross_tuition_cents"] == 184_512
    assert first["employer_reserved_cents"] == 110_707
    assert first["policy_id"] == s.policy_id

    _, active_meta = validate_paginated(
        api.list_benefit_policies(
            s.employer_id, s.benefit_admin, {"status": BenefitPolicyStatus.ACTIVE}
        )
    )
    assert active_meta["total_count"] == 2

    employee = s.read_employee()
    assert employee["eligibility_status"] == EligibilityStatus.INELIGIBLE_TENURE
    assert employee["tenure_months"] == 19


def test_the_tenure_shortfall_answers_before_the_concurrent_credit_ceiling(api):
    """Priority 33 outranks priority 37 even though both are 422 on the same request.

    PRD §2.9: "The employee's `tenure_months` is at least the policy's
    `min_tenure_months`; otherwise `ERR_EMPLOYEE_TENURE_NOT_MET` (422). Applies to
    `POST /enrollments` and `POST /program-approval-requests`."

    PRD §2.9: "Concurrent credits — the sum of `credits` over the employee's
    enrollments whose `academic_status` is `REGISTERED` or `IN_PROGRESS` and whose
    closed term interval shares at least one day with the new enrollment's closed term
    interval, plus the new enrollment's own `credits`, is at most the policy's
    `max_concurrent_credits`; otherwise `ERR_CONCURRENT_CREDIT_LIMIT` (422)."

    Design: Difficulty/priority_pair_validation_conflict/tenure_shortfall_outranks_concurrent_credit_overlap
    """
    s = build_cobalt_successor_policy(api)
    employee = s.read_employee()

    validate_error(
        api.create_enrollment(
            enrollment_payload(
                employee_id=s.employee_id,
                catalog_listing_id=s.listing_id,
                expected_employee_version=employee["version"],
                term_code="2026-WI",
                term_start_date="2026-12-15",
                term_end_date="2027-03-30",
                credits=4,
            ),
            s.employee,
        ),
        ERR_EMPLOYEE_TENURE_NOT_MET,
        422,
    )

    _, meta = validate_paginated(
        api.list_enrollments(s.benefit_admin, {"employee_id": s.employee_id})
    )
    assert meta["total_count"] == 1
    assert s.read_employee()["cap_reserved_cents"] == 110_707


def test_a_disbursement_landing_exactly_on_the_limit_is_wholly_excluded(api):
    """525,000 is not above the 525,000 ceiling, so nothing is imputed.

    PRD §2.10: "Under the statutory educational-assistance exclusion, at most 525,000
    cents — five thousand two hundred fifty dollars — of employer-provided education
    benefit may be excluded from an employee's income in a calendar year; anything
    beyond that is imputed income added to taxable wages."

    Design: Difficulty/boundary_precision_check/section_127_exclusion_limit_at_limit_versus_first_cent_beyond
    """
    s = build_beacon_second_term_billed(api)

    entries, meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert meta["total_count"] == 1
    assert entries[0]["enrollment_id"] == s.first_enrollment_id
    assert_ledger_row(entries[0], TaxEntryType.BENEFIT, 525_000, 525_000, 0, 2026)

    employee = s.read_employee()
    assert employee["taxable_excluded_cents_ytd"] == 525_000
    assert employee["imputed_income_cents_ytd"] == 0
    assert_cap_buckets(employee, 52_500, 525_000, 0, 422_500)
    assert_cap_pool_conserved(employee, 1_000_000)


def test_the_next_disbursement_finds_zero_headroom_and_is_wholly_imputed(api):
    """One cent past the ceiling there is no room at all, not a partial split.

    PRD §3.5: "The system first sums `excluded_cents` across all of that employee's
    ledger entries whose `tax_year` matches the year in question, then takes the
    headroom as the exclusion limit of 525,000 cents minus that prior total, floored at
    0 so an already-exhausted year yields no headroom rather than a negative one."

    PRD §3.5: "The `excluded_cents` on the new entry is the smaller of the amount just
    disbursed and that headroom, and `imputed_income_cents` is the amount disbursed
    minus `excluded_cents`."

    Design: Difficulty/boundary_precision_check/section_127_exclusion_limit_at_limit_versus_first_cent_beyond
    """
    s = build_beacon_second_term_billed(api)
    s.pay_invoice(s.second_invoice_id)

    second_rows, second_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"enrollment_id": s.second_enrollment_id}
        )
    )
    assert second_meta["total_count"] == 1
    assert_ledger_row(second_rows[0], TaxEntryType.BENEFIT, 52_500, 0, 52_500, 2026)

    employee = s.read_employee()
    assert employee["taxable_excluded_cents_ytd"] == 525_000
    assert employee["imputed_income_cents_ytd"] == 52_500
    assert_cap_buckets(employee, 0, 577_500, 0, 422_500)
    assert_cap_pool_conserved(employee, 1_000_000)

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 577_500
    assert employer["total_imputed_income_cents"] == 52_500

    _, year_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert year_meta["total_count"] == 2


def _utilization_employer(api) -> Scenario:
    """An employer with an ACTIVE direct-bill policy and nobody on the roster yet."""
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Beacon Analytics Holdings",
        benefit_admin_contact_email="benefits@beacon-analytics.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=3,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.CORPORATE],
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.DIRECT_BILL,
        reimbursement_pct=1.00,
        max_concurrent_credits=12,
        drop_window_days=7,
        service_commitment_months=12,
    )
    s.activate_policy()
    return s


def _utilization_catalog(s: Scenario) -> None:
    """A school, a 52,500-per-credit listing and nothing enrolled on it yet."""
    s.register_school(
        legal_name="Riverbend Technical Institute",
        state_code="OR",
        contact_email="registrar@riverbendtech.example",
    )
    s.publish_program(
        name="Certificate in Data Analytics",
        credential_type=CredentialType.CERTIFICATE,
        skill_track=SkillTrack.DATA_ANALYTICS,
        list_tuition_per_credit_cents=70_000,
        total_credits=30,
        term_length_weeks=12,
    )
    s.draft_agreement(
        negotiated_discount_pct=0.25,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )
    s.activate_agreement()
    s.curate_listing()


def test_every_utilization_quotient_short_circuits_on_an_empty_denominator(api):
    """No employees means ten zeros, and one idle employee means participation 0.0.

    PRD §3.9: "`participation_rate` is the participating count divided by the eligible
    count, rounded half up to four decimal places, and is reported as 0.0 when the
    eligible count is zero."

    PRD §3.9: "Empty collections always short-circuit to 0.0 or 0 rather than producing
    a division error."

    Design: Difficulty/boundary_precision_check/utilization_report_zero_denominator_boundaries
    """
    s = _utilization_employer(api)

    empty = validate_success(
        api.get_utilization_report(s.employer_id, s.benefit_admin)
    )
    assert empty["plan_year"] == 2026
    assert empty["eligible_employee_count"] == 0
    assert empty["participating_employee_count"] == 0
    assert empty["participation_rate"] == 0.0
    assert empty["completion_rate"] == 0.0
    assert empty["retention_rate"] == 0.0
    assert empty["skill_attainment_count"] == 0
    assert empty["total_employer_disbursed_cents"] == 0
    assert empty["total_imputed_income_cents"] == 0
    assert empty["cost_per_completion_cents"] == 0

    s.register_employee(
        full_name="Priya Raman",
        work_email="priya.raman@beacon-analytics.example",
        hire_date="2024-06-01",
        weekly_hours=40,
        job_family=JobFamily.CORPORATE,
    )
    assert s.read_employee()["eligibility_status"] == EligibilityStatus.ELIGIBLE

    idle = validate_success(api.get_utilization_report(s.employer_id, s.benefit_admin))
    assert idle["eligible_employee_count"] == 1
    assert idle["participating_employee_count"] == 0
    assert idle["participation_rate"] == 0.0
    assert idle["completion_rate"] == 0.0
    assert idle["retention_rate"] == 0.0


def test_a_full_participation_rate_coexists_with_a_zero_completion_rate(api):
    """One registered enrollment: participation 1.0, retention 1.0, completion 0.0.

    PRD §3.9: "`retention_rate` is the number of distinct participating employees whose
    `employment_status` is `ACTIVE` divided by `participating_employee_count`, rounded
    half up to four decimal places, and is 0.0 when nobody participated."

    PRD §3.9: "Closed enrollments are those in scope whose `academic_status` is
    `PASSED`, `FAILED`, `WITHDRAWN` or `INCOMPLETE`, and completions are the subset of
    those that are `PASSED`; `completion_rate` is the number of completions divided by
    the number of closed enrollments, rounded half up to four decimal places, and is
    0.0 when nothing has closed."

    Design: Difficulty/boundary_precision_check/utilization_report_zero_denominator_boundaries
    """
    s = _utilization_employer(api)
    s.register_employee(
        full_name="Priya Raman",
        work_email="priya.raman@beacon-analytics.example",
        hire_date="2024-06-01",
        weekly_hours=40,
        job_family=JobFamily.CORPORATE,
    )
    _utilization_catalog(s)
    enrolled = s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-11-30",
        credits=10,
    )
    assert enrolled["plan_year"] == 2026
    assert enrolled["employer_disbursed_cents"] == 0

    report = validate_success(
        api.get_utilization_report(s.employer_id, s.benefit_admin)
    )
    assert report["plan_year"] == 2026
    assert report["eligible_employee_count"] == 1
    assert report["participating_employee_count"] == 1
    assert report["participation_rate"] == 1.0
    assert report["retention_rate"] == 1.0
    assert report["completion_rate"] == 0.0
    assert report["skill_attainment_count"] == 0
    assert report["total_employer_disbursed_cents"] == 0
    assert report["total_imputed_income_cents"] == 0
    assert report["cost_per_completion_cents"] == 0
