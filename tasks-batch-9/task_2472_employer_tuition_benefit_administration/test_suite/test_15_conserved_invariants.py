"""Two conserved quantities, each measured across its own compensating action."""

from test_helpers import (
    AcademicStatus,
    CompletionStatus,
    FundingStatus,
    ObligationStatus,
    PostedByRole,
    assert_cap_buckets,
    assert_cap_pool_conserved,
    assert_obligation_identity,
    build_lakeshore_early_departure,
    build_northwind_base,
    build_northwind_three_credit_enrolled,
    validate_paginated,
)


def test_an_in_window_withdrawal_restores_the_pool_to_the_exact_cent(api):
    """600,000 whole, then 55,354 reserved, then 600,000 whole again with no residue.

    PRD §2.6: "`cap_available_cents` is the governing policy's `annual_cap_cents` minus
    the reserved bucket minus the disbursed bucket minus the clawback-hold bucket."

    PRD §2.6: "Enrollments whose `funding_status` is `RELEASED`, and clawed-back
    enrollments whose obligation has reached `SETTLED`, contribute zero to every bucket."

    Design: Difficulty/compensating_invariant/annual_cap_pool_identity_restored_exactly_by_in_window_withdrawal
    """
    s = build_northwind_base(api)
    untouched = s.read_employee()
    assert_cap_buckets(untouched, 0, 0, 0, 600_000)
    assert_cap_pool_conserved(untouched, 600_000)

    s.enroll(
        term_code="2026-FA",
        term_start_date="2026-09-01",
        term_end_date="2026-12-15",
        credits=3,
    )
    reserved = s.read_employee()
    assert_cap_buckets(reserved, 55_354, 0, 0, 544_646)
    assert_cap_pool_conserved(reserved, 600_000)

    s.set_clock("2026-09-10T00:00:00Z")
    s.withdraw()

    restored = s.read_employee()
    assert_cap_buckets(restored, 0, 0, 0, 600_000)
    assert_cap_pool_conserved(restored, 600_000)
    assert restored["cap_available_cents"] == 600_000
    assert restored["cap_available_cents"] != 599_999
    assert restored["cap_available_cents"] != 600_001


def test_the_released_enrollment_keeps_its_audit_trail_and_owes_nothing(api):
    """The reserve stays on the record, a SYSTEM outcome is logged, nothing is owed.

    PRD §3.7: "Withdrawal is the learner's own exit, permitted while the enrollment's
    `academic_status` is either `REGISTERED` or `IN_PROGRESS`; from both states the
    academic axis moves to `WITHDRAWN`, and in both cases an `AcademicOutcome` is appended
    with `completion_status` `WITHDRAWN`, `grade_points` null, `credits_earned` 0 and
    `posted_by_role` `SYSTEM`."

    PRD §3.7: "When the logical clock date is on or before that deadline, the money axis
    moves from `RESERVED` or `BILLED` to `RELEASED`, every `TuitionInvoice` of the
    enrollment whose `status` is `ISSUED` or `APPROVED_FOR_PAYMENT` moves to `VOIDED`, and
    no repayment obligation is created at all."

    PRD §3.4: "When `funding_status` is `RELEASED` the employer contributes nothing and
    the field is the full `gross_tuition_cents`; the `employer_reserved_cents` figure is
    retained on the record for audit but excluded from every cap bucket."

    Design: Difficulty/compensating_invariant/annual_cap_pool_identity_restored_exactly_by_in_window_withdrawal
    """
    s = build_northwind_three_credit_enrolled(api)
    assert s.read_enrollment()["drop_deadline_date"] == "2026-09-15"

    s.set_clock("2026-09-10T00:00:00Z")
    s.withdraw()

    released = s.read_enrollment()
    assert released["academic_status"] == AcademicStatus.WITHDRAWN
    assert released["funding_status"] == FundingStatus.RELEASED
    assert released["employer_reserved_cents"] == 55_354
    assert released["employer_disbursed_cents"] == 0
    assert released["employee_share_cents"] == 92_256

    outcomes, outcomes_meta = validate_paginated(
        api.list_academic_outcomes(s.enrollment_id, s.school_partner)
    )
    assert outcomes_meta["total_count"] == 1
    assert outcomes[0]["completion_status"] == CompletionStatus.WITHDRAWN
    assert outcomes[0]["grade_points"] is None
    assert outcomes[0]["credits_earned"] == 0
    assert outcomes[0]["posted_by_role"] == PostedByRole.SYSTEM

    _, obligations_meta = validate_paginated(
        api.list_repayment_obligations(s.enrollment_id, s.benefit_admin)
    )
    assert obligations_meta["total_count"] == 0

    _, ledger_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"enrollment_id": s.enrollment_id}
        )
    )
    assert ledger_meta["total_count"] == 0


def test_a_partial_payment_preserves_the_identity_and_releases_no_capacity(api):
    """69,333 splits into 20,000 paid and 49,333 outstanding, hold untouched at 104,000.

    PRD §3.7: "The identity that `principal_cents` equals `paid_cents` plus `waived_cents`
    plus `balance_cents` holds after every operation on the row."

    PRD §3.7: "A payment strictly smaller than the current `balance_cents` increases
    `paid_cents` by that amount, recomputes `balance_cents`, and moves the obligation
    `ASSESSED → PARTIALLY_PAID`; a further such payment from `PARTIALLY_PAID` keeps it in
    `PARTIALLY_PAID`, so repeated instalments loop in that state until the balance reaches
    zero."

    PRD §3.7: "While a balance remains, the clawback hold on the cap is emphatically
    **not** released; only on reaching `SETTLED` does the enrollment's amount leave
    `cap_clawback_hold_cents`, raising `cap_available_cents` by that amount, because the
    employer has been made whole."

    Design: Difficulty/compensating_invariant/repayment_obligation_principal_conserved_across_partial_payment_and_waiver
    """
    s = build_lakeshore_early_departure(api)
    assessed = s.first_obligation()
    assert assessed["principal_cents"] == 69_333
    assert assessed["paid_cents"] == 0
    assert assessed["waived_cents"] == 0
    assert assessed["balance_cents"] == 69_333
    assert assessed["status"] == ObligationStatus.ASSESSED
    assert_obligation_identity(assessed)

    part_paid = s.pay_obligation(20_000)
    assert part_paid["principal_cents"] == 69_333
    assert part_paid["paid_cents"] == 20_000
    assert part_paid["waived_cents"] == 0
    assert part_paid["balance_cents"] == 49_333
    assert part_paid["status"] == ObligationStatus.PARTIALLY_PAID
    assert_obligation_identity(part_paid)

    employee = s.read_employee()
    assert employee["open_repayment_balance_cents"] == 49_333
    assert_cap_buckets(employee, 0, 0, 104_000, 696_000)
    assert_cap_pool_conserved(employee, 800_000)


def test_the_waiver_closes_the_balance_without_refilling_that_year_s_pool(api):
    """The remaining 49,333 becomes waived, and the 104,000 hold deliberately stays put.

    PRD §3.7: "A `BenefitAdministrator` may waive an obligation whose `status` is
    `ASSESSED` or `PARTIALLY_PAID`; `waived_cents` is set to the `balance_cents` as it
    stands at waive time, `balance_cents` becomes 0, and the obligation moves to `WAIVED`."

    PRD §3.7: "Because the employer absorbed the cost rather than recovering it, the
    amount **stays** in `cap_clawback_hold_cents` and `cap_available_cents` does not rise —
    a waiver forgives the learner without refilling that plan year's pool."

    Design: Difficulty/compensating_invariant/repayment_obligation_principal_conserved_across_partial_payment_and_waiver
    """
    s = build_lakeshore_early_departure(api)
    s.first_obligation()
    s.pay_obligation(20_000)

    waived = s.waive_obligation()
    assert waived["principal_cents"] == 69_333
    assert waived["paid_cents"] == 20_000
    assert waived["waived_cents"] == 49_333
    assert waived["balance_cents"] == 0
    assert waived["status"] == ObligationStatus.WAIVED
    assert_obligation_identity(waived)

    employee = s.read_employee()
    assert employee["open_repayment_balance_cents"] == 0
    assert_cap_buckets(employee, 0, 0, 104_000, 696_000)
    assert_cap_pool_conserved(employee, 800_000)

    _, ledger_meta = validate_paginated(
        api.list_tax_ledger_entries(
            s.benefit_admin, {"employee_id": s.employee_id, "tax_year": 2026}
        )
    )
    assert ledger_meta["total_count"] == 2
    assert employee["taxable_excluded_cents_ytd"] == 34_667
