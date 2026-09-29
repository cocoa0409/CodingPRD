"""The two award variants and the two tax-exclusion readings of the same money."""

from test_helpers import (
    AcademicStatus,
    ClaimDecision,
    CompletionStatus,
    FundingStatus,
    TaxEntryType,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_enrollment_axes,
    assert_ledger_row,
    assert_ledger_year_identity,
    assert_true_up_row_shape,
    assert_term_close_counts,
    build_beacon_first_term_failed,
    build_northwind_three_credit_enrolled,
    build_northwind_three_credit_in_progress,
    validate_paginated,
    validate_success,
)


def test_the_provisional_award_ignores_academic_input_entirely(api):
    """The reserve variant is pure rate arithmetic: 92,256 gross, 55,354 reserved.

    PRD §3.4: "The provisional employer entitlement is then computed: under
    `DIRECT_BILL` the uncapped amount is the whole `gross_tuition_cents`, because the
    employer fronts the full negotiated tuition, whereas under `REIMBURSEMENT` the
    uncapped amount is `gross_tuition_cents` multiplied by the policy's
    `reimbursement_pct`, rounded half up to a whole cent."

    PRD §3.4: "No academic input participates at this stage — there is no outcome
    yet."

    Design: Difficulty/dual_variant_calc/reserve_versus_settled_award_divergence_on_same_enrollment
    """
    s = build_northwind_three_credit_enrolled(api)

    enrollment = s.read_enrollment()
    assert enrollment["gross_tuition_cents"] == 92_256
    assert enrollment["employer_reserved_cents"] == 55_354
    assert enrollment["employee_share_cents"] == 36_902
    assert enrollment["employer_settled_cents"] == 0
    assert enrollment["employer_disbursed_cents"] == 0
    assert enrollment["credits_earned"] == 0
    assert enrollment["policy_id"] == s.policy_id
    assert_enrollment_axes(
        enrollment, AcademicStatus.REGISTERED, FundingStatus.RESERVED
    )

    _, outcomes_meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert outcomes_meta["total_count"] == 0

    employee = s.read_employee()
    assert employee["cap_available_cents"] == 544_646
    assert_cap_buckets(employee, 55_354, 0, 0, 544_646)
    assert_cap_pool_conserved(employee, 600_000)


def test_the_settled_award_diverges_upward_from_the_reservation(api):
    """A 3.70 grade lifts the share to 0.70, settling 64,579 against 55,354 reserved.

    PRD §3.6: "The effective share is the policy's `reimbursement_pct` plus a grade
    bonus of 0.10 when the latest outcome's `grade_points` are at least 3.50 and plus
    nothing otherwise, with the sum capped at 1.00 so the employer never covers more
    than the whole tuition."

    PRD §3.6: "The enrollment's `employer_settled_cents` is then the smaller of that
    uncapped final entitlement and the sum of `employer_reserved_cents` and the
    employee's `cap_available_cents`; because the headroom is added back to the
    original reservation, this final figure can legitimately come out *above* the
    provisional reserve as well as below it."

    Design: Difficulty/dual_variant_calc/reserve_versus_settled_award_divergence_on_same_enrollment
    """
    s = build_northwind_three_credit_in_progress(api)
    s.set_clock("2026-12-20T00:00:00Z")
    s.post_outcome("2026-FA", CompletionStatus.PASSED, 3, 3.70)

    before = s.read_employee()
    assert before["cap_reserved_cents"] == 55_354
    assert before["cap_available_cents"] == 544_646

    s.file_claim(92_256, "CSU-2026FA-DOKAFOR-01")
    decided = s.decide_claim(ClaimDecision.APPROVE)
    assert decided["approved_amount_cents"] == 64_579
    assert decided["platform_admin_fee_cents"] == 3_229
    assert decided["approved_amount_cents"] - 55_354 == 9_225

    enrollment = s.read_enrollment()
    assert enrollment["employer_reserved_cents"] == 55_354
    assert enrollment["employer_settled_cents"] == 64_579
    assert enrollment["employer_disbursed_cents"] == 64_579
    assert enrollment["employee_share_cents"] == 27_677
    assert_enrollment_axes(enrollment, AcademicStatus.PASSED, FundingStatus.SETTLED)

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 64_579, 0, 535_421)
    assert_cap_pool_conserved(employee, 600_000)

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 64_579
    assert employer["total_admin_fee_cents"] == 3_229


def test_chronological_attribution_strands_imputed_income_after_a_reversal(api):
    """Three rows: 525,000 excluded, 52,500 imputed, then the first row reversed.

    PRD §2.10: "Attribution order is pinned: entries are considered in `posted_at`
    ascending order with `created_at` ascending as the only tie-break — never by
    `id`."

    PRD §3.7: "The system locates the `BENEFIT` entry for the same `enrollment_id`
    and `tax_year`, takes the reversed exclusion as the smaller of the obligation's
    `principal_cents` and that origin entry's `excluded_cents`, and appends a
    `REVERSAL` entry whose `benefit_cents` is the negative of `principal_cents`,
    whose `excluded_cents` is the negative of that reversed exclusion, and whose
    `imputed_income_cents` is the negative of the principal minus the reversed
    exclusion."

    Design: Difficulty/dual_variant_calc/chronological_versus_annual_true_up_tax_exclusion_divergence
    """
    s = build_beacon_first_term_failed(api)

    entries, meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert meta["total_count"] == 3

    first_benefit = [
        e
        for e in entries
        if e["entry_type"] == TaxEntryType.BENEFIT
        and e["enrollment_id"] == s.first_enrollment_id
    ]
    assert len(first_benefit) == 1
    assert_ledger_row(first_benefit[0], TaxEntryType.BENEFIT, 525_000, 525_000, 0, 2026)

    second_benefit = [
        e
        for e in entries
        if e["entry_type"] == TaxEntryType.BENEFIT
        and e["enrollment_id"] == s.second_enrollment_id
    ]
    assert len(second_benefit) == 1
    assert_ledger_row(second_benefit[0], TaxEntryType.BENEFIT, 52_500, 0, 52_500, 2026)

    reversals = [e for e in entries if e["entry_type"] == TaxEntryType.REVERSAL]
    assert len(reversals) == 1
    assert reversals[0]["enrollment_id"] == s.first_enrollment_id
    assert_ledger_row(
        reversals[0], TaxEntryType.REVERSAL, -525_000, -525_000, 0, 2026
    )

    employee = s.read_employee()
    assert employee["taxable_excluded_cents_ytd"] == 0
    assert employee["imputed_income_cents_ytd"] == 52_500
    assert_ledger_year_identity(entries, employee)


def test_the_annual_true_up_books_only_the_aggregate_difference(api):
    """The aggregate reading nets to 52,500 excludable and moves it with one row.

    PRD §3.9: "When either delta is non-zero, a single `TRUE_UP` entry is appended
    with a null `enrollment_id`, `benefit_cents` of 0, `excluded_cents` equal to the
    excluded delta and `imputed_income_cents` equal to the imputed delta; when both
    deltas are zero, nothing is appended for that employee."

    PRD §3.9: "The two readings agree until a reversal occurs; afterwards they
    diverge, because chronological attribution leaves imputed income stranded on a
    later disbursement whose earlier neighbour has since been reversed, and the
    aggregate reading therefore yields a strictly smaller `imputed_income_cents_ytd`."

    Design: Difficulty/dual_variant_calc/chronological_versus_annual_true_up_tax_exclusion_divergence
    """
    s = build_beacon_first_term_failed(api)
    before = s.read_employee()
    assert before["taxable_excluded_cents_ytd"] == 0
    assert before["imputed_income_cents_ytd"] == 52_500

    report = s.close_term("2026-FA", run_annual_true_up=True, tax_year=2026)
    assert_term_close_counts(report, 0, 0, 0, 1, 0)

    entries, meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert meta["total_count"] == 4

    true_ups = [e for e in entries if e["entry_type"] == TaxEntryType.TRUE_UP]
    assert len(true_ups) == 1
    assert_true_up_row_shape(true_ups[0])
    assert_ledger_row(true_ups[0], TaxEntryType.TRUE_UP, 0, 52_500, -52_500, 2026)

    after = s.read_employee()
    assert after["taxable_excluded_cents_ytd"] == 52_500
    assert after["imputed_income_cents_ytd"] == 0
    assert_ledger_year_identity(entries, after)

    employer = validate_success(api.get_employer(s.employer_id, s.benefit_admin))
    assert employer["total_imputed_income_cents"] == 0
