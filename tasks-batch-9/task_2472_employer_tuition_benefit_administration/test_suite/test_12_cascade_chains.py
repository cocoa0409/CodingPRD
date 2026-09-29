"""Four-hop chains where every hop exists only because the previous one happened."""

from test_helpers import (
    AcademicStatus,
    CompletionStatus,
    EligibilityStatus,
    EmploymentStatus,
    FundingStatus,
    ObligationReason,
    ObligationStatus,
    PostedByRole,
    TaxEntryType,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_enrollment_axes,
    assert_ledger_row,
    assert_ledger_year_identity,
    assert_obligation_identity,
    build_beacon_first_term_failed,
    build_beacon_second_term_paid,
    build_lakeshore_early_departure,
    build_lakeshore_settled,
    employee_patch_payload,
    validate_paginated,
    validate_success,
)


def test_a_failed_outcome_assesses_the_full_disbursement_and_claws_it_back(api):
    """Hops one and two: FAILED on the academic axis, CLAWED_BACK on the money axis.

    PRD §3.7: "Because the academic axis turned `FAILED` (or `INCOMPLETE`) while the
    money axis stood at `SETTLED`, an obligation is created with `trigger_reason`
    `ACADEMIC_FAILURE` and `principal_cents` equal to the full
    `employer_disbursed_cents`, and the money axis moves `SETTLED → CLAWED_BACK`."

    PRD §2.8: "An implementation that performs only the first hop of a chain is
    incorrect even though the first hop looks complete."

    Design: Difficulty/transitive_cascade/failed_outcome_drives_obligation_then_clawback_then_reversal_then_aggregates
    """
    s = build_beacon_second_term_paid(api)
    before = s.read_enrollment(s.first_enrollment_id)
    assert_enrollment_axes(
        before, AcademicStatus.IN_PROGRESS, FundingStatus.SETTLED
    )
    assert before["employer_disbursed_cents"] == 525_000

    outcome = s.post_outcome(
        "2026-FA",
        CompletionStatus.FAILED,
        0,
        1.50,
        enrollment_id=s.first_enrollment_id,
    )
    assert outcome["completion_status"] == CompletionStatus.FAILED
    assert outcome["credits_earned"] == 0
    assert outcome["posted_by_role"] == PostedByRole.SCHOOL_PARTNER

    failed = s.read_enrollment(s.first_enrollment_id)
    assert_enrollment_axes(failed, AcademicStatus.FAILED, FundingStatus.CLAWED_BACK)
    assert failed["credits_earned"] == 0
    assert failed["employer_disbursed_cents"] == 525_000

    obligations, meta = validate_paginated(
        api.list_repayment_obligations(s.first_enrollment_id, s.benefit_admin)
    )
    assert meta["total_count"] == 1
    obligation = obligations[0]
    assert obligation["trigger_reason"] == ObligationReason.ACADEMIC_FAILURE
    assert obligation["principal_cents"] == 525_000
    assert obligation["paid_cents"] == 0
    assert obligation["waived_cents"] == 0
    assert obligation["balance_cents"] == 525_000
    assert obligation["status"] == ObligationStatus.ASSESSED
    assert_obligation_identity(obligation)


def test_the_clawback_reverses_the_exclusion_and_refreshes_every_aggregate(api):
    """Hops three and four: a mirroring REVERSAL, then five recomputed aggregates.

    PRD §3.7: "Because that reversal landed, the employee's
    `taxable_excluded_cents_ytd`, `imputed_income_cents_ytd`, `cap_disbursed_cents`,
    `cap_clawback_hold_cents`, `cap_available_cents` and
    `open_repayment_balance_cents` are recomputed, and so are the employer's
    `total_disbursed_cents` and `total_imputed_income_cents`."

    PRD §3.7: "The `employer_disbursed_cents` figure itself is never zeroed by a
    reversal — the money genuinely left, and the record of it is retained while the
    enrollment sits in `CLAWED_BACK`."

    Design: Difficulty/transitive_cascade/failed_outcome_drives_obligation_then_clawback_then_reversal_then_aggregates
    """
    s = build_beacon_first_term_failed(api)

    reversals, reversal_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin,
            {
                "enrollment_id": s.first_enrollment_id,
                "entry_type": TaxEntryType.REVERSAL,
            },
        )
    )
    assert reversal_meta["total_count"] == 1
    assert_ledger_row(reversals[0], TaxEntryType.REVERSAL, -525_000, -525_000, 0, 2026)

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 52_500, 525_000, 422_500)
    assert_cap_pool_conserved(employee, 1_000_000)
    assert employee["taxable_excluded_cents_ytd"] == 0
    assert employee["imputed_income_cents_ytd"] == 52_500
    assert employee["open_repayment_balance_cents"] == 525_000

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 52_500
    assert employer["total_imputed_income_cents"] == 52_500

    untouched = s.read_enrollment(s.second_enrollment_id)
    assert_enrollment_axes(
        untouched, AcademicStatus.IN_PROGRESS, FundingStatus.SETTLED
    )
    assert untouched["employer_disbursed_cents"] == 52_500

    entries, _ = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert_ledger_year_identity(entries, employee)


def test_an_employment_termination_prorates_the_obligation_by_unserved_months(api):
    """Hops one and two: INELIGIBLE_EMPLOYMENT, then eight unserved months of 104,000.

    PRD §3.1: "Any such patch recomputes `eligibility_status`; a patch to `TERMINATED`
    yields `INELIGIBLE_EMPLOYMENT` and additionally runs the early-departure cascade
    described in §3.7."

    PRD §3.7: "For `EARLY_DEPARTURE`, the recovery is prorated by the part of the
    service commitment the employee did not serve: the system counts the whole months
    elapsed from the enrollment's `term_end_date` to the employee's
    `termination_date`, where a month completes once the day-of-month is reached or
    passed and a negative span clamps to zero months; the unserved remainder is the
    policy's `service_commitment_months` minus that elapsed count, floored at zero; and
    `principal_cents` is `employer_disbursed_cents` multiplied by the unserved
    remainder divided by `service_commitment_months`, rounded half up to a whole cent."

    Design: Difficulty/transitive_cascade/employee_termination_drives_prorated_obligation_then_clawback_then_reversal_then_aggregates
    """
    s = build_lakeshore_settled(api)
    assert s.read_listing()["negotiated_tuition_per_credit_cents"] == 32_000

    settled = s.read_enrollment()
    assert settled["gross_tuition_cents"] == 160_000
    assert settled["employer_reserved_cents"] == 88_000
    assert settled["employer_disbursed_cents"] == 104_000

    baseline = s.read_employee()
    assert_cap_buckets(baseline, 0, 104_000, 0, 696_000)
    assert_cap_pool_conserved(baseline, 800_000)
    benefit_rows, benefit_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin,
            {"enrollment_id": s.enrollment_id, "entry_type": TaxEntryType.BENEFIT},
        )
    )
    assert benefit_meta["total_count"] == 1
    assert_ledger_row(benefit_rows[0], TaxEntryType.BENEFIT, 104_000, 104_000, 0, 2026)

    s.set_clock("2026-09-01T00:00:00Z")
    patched = validate_success(
        api.patch_employee(
            s.employee_id,
            employee_patch_payload(
                employment_status=EmploymentStatus.TERMINATED,
                termination_date="2026-09-01",
            ),
            s.benefit_admin,
        )
    )
    assert patched["employment_status"] == EmploymentStatus.TERMINATED
    assert patched["termination_date"] == "2026-09-01"
    assert patched["eligibility_status"] == EligibilityStatus.INELIGIBLE_EMPLOYMENT

    obligations, meta = validate_paginated(
        api.list_repayment_obligations(s.enrollment_id, s.benefit_admin)
    )
    assert meta["total_count"] == 1
    obligation = obligations[0]
    assert obligation["trigger_reason"] == ObligationReason.EARLY_DEPARTURE
    assert obligation["principal_cents"] == 69_333
    assert obligation["balance_cents"] == 69_333
    assert obligation["status"] == ObligationStatus.ASSESSED
    assert obligation["assessed_on"] == "2026-09-01"
    assert_obligation_identity(obligation)


def test_the_prorated_reversal_leaves_a_residual_exclusion_behind(api):
    """Hops three and four: −69,333 reversed out of 104,000, leaving 34,667 excluded.

    PRD §3.7: "Separately, every enrollment whose `funding_status` is `SETTLED` and
    whose `term_end_date` falls within the policy's `service_commitment_months` before
    the `termination_date` moves `SETTLED → CLAWED_BACK` with a prorated obligation
    whose `trigger_reason` is `EARLY_DEPARTURE`, plus the mirroring `REVERSAL` entry."

    PRD §2.8: "`total_disbursed_cents` on an `Employer` is the sum of
    `employer_disbursed_cents` over enrollments belonging to that employer's employees
    whose `funding_status` is `SETTLED`; clawed-back and released enrollments
    contribute zero."

    Design: Difficulty/transitive_cascade/employee_termination_drives_prorated_obligation_then_clawback_then_reversal_then_aggregates
    """
    s = build_lakeshore_early_departure(api)

    clawed_back = s.read_enrollment()
    assert_enrollment_axes(
        clawed_back, AcademicStatus.PASSED, FundingStatus.CLAWED_BACK
    )
    assert clawed_back["employer_disbursed_cents"] == 104_000

    reversals, reversal_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin,
            {"enrollment_id": s.enrollment_id, "entry_type": TaxEntryType.REVERSAL},
        )
    )
    assert reversal_meta["total_count"] == 1
    assert_ledger_row(reversals[0], TaxEntryType.REVERSAL, -69_333, -69_333, 0, 2026)

    employee = s.read_employee()
    assert_cap_buckets(employee, 0, 0, 104_000, 696_000)
    assert_cap_pool_conserved(employee, 800_000)
    assert employee["taxable_excluded_cents_ytd"] == 34_667
    assert employee["imputed_income_cents_ytd"] == 0
    assert employee["open_repayment_balance_cents"] == 69_333

    employer = s.read_employer()
    assert employer["total_disbursed_cents"] == 0
    assert employer["total_admin_fee_cents"] == 5_200

    entries, entries_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert entries_meta["total_count"] == 2
    assert_ledger_year_identity(entries, employee)
