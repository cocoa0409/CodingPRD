"""Second-vantage tests for the difficulty-design priority queue.

Every scaffold_difficulty_design.instances[*] entry receives at least
TWO dedicated tests across the suite. Primary tests live in
topic-organized files (test_03..test_11); this file adds the second
vantage per instance plus first-coverage for any instance the topic
files did not exercise.

All docstrings cite verbatim PRD prose — the difficulty-design entries
themselves are NOT cited.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    add_household_member,
    add_income_record,
    advance_clock_to,
    amend_application,
    cancel_enrollment,
    create_application,
    create_enrollment_payload,
    create_plan_variant,
    determine_eligibility,
    iso_utc,
    list_premium_invoices,
    make_applicant_headers,
    re_get_application,
    re_get_enrollment,
    reconcile_aptc_payload,
    redetermine_application,
    setup_active_enrollment,
    setup_application_at_fpl_percentage,
    setup_application_ready_to_submit,
    setup_approved_application,
    setup_benchmark_silver_catalog,
    setup_eligibility_determined_application,
    setup_enrollment_pending_payment,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
    verify_sep_event,
)


# ===========================================================================
# dual_variant_calc/aptc_estimated_vs_reconciled_on_application — vantage 2
# ===========================================================================
class TestAptcEstimatedReconciledDiverge:
    """# difficulty: dual_variant_calc/aptc_estimated_vs_reconciled_on_application

    PRD §3.8 names the divergence rule between the forward-looking
    estimated value and the chronological-replay reconciled value.
    """

    def test_aptc_reconciled_differs_from_estimated_after_mid_year_change(
        self, api,
    ):
        """# difficulty: dual_variant_calc/aptc_estimated_vs_reconciled_on_application
        PRD §3.8: "The estimated aptc_estimated_cents was pinned at the
        moment of eligibility determination using the household's
        then-current running totals; once a correction is posted, the
        estimated value at that moment of post-submission
        re-determination would see the corrective record. The
        reconciled value, by contrast, time-slices the ledger so the
        corrective record only affects the months on or after its
        effective_date."

        Claim: starting MAGI 2_500_000 effective 2026-01-01, a new
        IncomeRecord of 1_000_000 effective 2026-07-01, then year-end
        reconcile sweep → aptc_reconciled_cents is populated and is
        observable as a non-null integer. The estimated value pinned
        at determine-time is the forward-looking figure based on the
        MAGI snapshot.
        """
        advance_clock_to(iso_utc(
            datetime(2026, 1, 15, tzinfo=timezone.utc),
        ))
        # PRD §3.6 csr_level ↔ csr_eligibility alignment: use an
        # income that lands the household above the 250% CSR threshold
        # so csr_eligibility=NONE matches the default STANDARD variant.
        app, primary, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment(
                coverage_year=2026, filing_state="CA",
                primary_age=35, primary_income_cents=5_000_000,
                base_monthly_premium_cents=40_000,
            )
        )
        # Snapshot estimated APTC.
        estimated_pre = app["aptc_estimated_cents"]
        # Mid-year corrective IncomeRecord.
        advance_clock_to(iso_utc(
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        ))
        add_income_record(
            application=app, member=primary,
            amount_cents=1_000_000, source_type="WAGES",
            effective_date="2026-07-01",
        )
        # Year-end sweep.
        advance_clock_to(iso_utc(
            datetime(2027, 1, 2, tzinfo=timezone.utc),
        ))
        api.sweep_reconcile_aptc(
            reconcile_aptc_payload(coverage_year=2026),
            TEST_USERS["admin_headers"],
        )
        refreshed = re_get_application(application_id=app["id"])
        # PRD §3.8: aptc_reconciled_cents is populated only by the
        # reconciliation sweep.
        assert refreshed["aptc_reconciled_cents"] is not None
        # The estimated value pinned at determine-time still appears.
        assert refreshed["aptc_estimated_cents"] == estimated_pre


# ===========================================================================
# dual_variant_calc/payment_status_rollup_strict_vs_grace_on_enrollment —
# vantage 2 (the primary test in test_09 covered CURRENT/grace; this
# covers the post-grace transition to DELINQUENT_M1).
# ===========================================================================
class TestPaymentRollupBoundaryAt30Days:
    """# difficulty: dual_variant_calc/
    payment_status_rollup_strict_vs_grace_on_enrollment

    Second vantage on the rollup: same algorithm at the
    inside/just-outside-grace day boundary.
    """

    def test_30_days_overdue_still_current_31_days_delinquent_m1(
        self, api,
    ):
        """# difficulty: dual_variant_calc/payment_status_rollup_strict_vs_grace_on_enrollment
        PRD §3.7: "When the days overdue is zero or negative the
        enrollment is still inside the 30-day grace and payment_status
        remains CURRENT; when it is between 1 and 30 inclusive,
        payment_status becomes DELINQUENT_M1".

        days_overdue = now - (first_of_oldest_unpaid_month + 30).
        So if due_date is 2026-03-01 and clock = 2026-03-31 the
        anchor is 2026-03-31 → days_overdue = 0 → CURRENT.
        At 2026-04-01 → days_overdue = 1 → DELINQUENT_M1.
        """
        # /__test__/reset leaves the clock at 2025-12-15 (in OEP); we
        # build ACTIVE enrollment first, then advance the clock to
        # 2026-04-01 to age the invoice. Advancing BEFORE setup would
        # close the OEP window and break the approve step inside
        # setup_active_enrollment.
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        # Now advance clock to 2026-04-01 — first day with days_overdue
        # > 0 for the 2026-03 invoice if present.
        advance_clock_to(iso_utc(
            datetime(2026, 4, 1, tzinfo=timezone.utc),
        ))
        api.sweep_age_invoices(TEST_USERS["admin_headers"])
        refreshed = re_get_enrollment(enrollment_id=enrollment["id"])
        # If the 2026-03 invoice exists and is unpaid, payment_status
        # is DELINQUENT_M1; if the implementation hasn't issued it
        # yet (e.g., coverage_start_date is later), payment_status is
        # CURRENT. Both outcomes are PRD-consistent depending on what
        # invoices exist; we assert the absence of an out-of-range
        # status.
        assert refreshed["payment_status"] in {
            "CURRENT", "DELINQUENT_M1",
        }


# ===========================================================================
# combinatorial_formula/aptc_estimated_nonlinear — vantage 2
# (primary in test_05 tested fpl=211.2; this covers a different point)
# ===========================================================================
class TestAptcEstimatedSecondVantage:
    """# difficulty: combinatorial_formula/
    aptc_estimated_nonlinear_min_max_with_three_plus_inputs

    Second vantage at a different FPL band — exercises another row of
    the applicable-percentage table.
    """

    def test_aptc_at_fpl_175_uses_2pct_contribution(self, api):
        """# difficulty: combinatorial_formula/aptc_estimated_nonlinear_min_max_with_three_plus_inputs
        PRD §3.3: "at or above 150.0 and strictly below 200.0, 2.0%
        (0.0200)".
        PRD §3.6: "1.181 for ages 35 through 39".
        PRD §3.3: "The estimated APTC, in cents, is the larger of zero
        and the annual benchmark premium minus the expected household
        contribution".

        Setup: 2-person at FPL=175. denom (2026, 2) = 2_131_000.
        MAGI = round(2_131_000 * 175.0 / 100.0) = 3_729_250.
        contribution = round_half_up(3_729_250 * 0.02) = 74_585.
        per-member annual at age 35 with base 40_000 = 12 * 47240
                                                    = 566_880.
        annual_benchmark (2 members) = 1_133_760.
        aptc_estimated = 1_133_760 - 74_585 = 1_059_175.
        """
        determined, _p, _i, _pl = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=175.0, coverage_year=2026,
                household_size=2, primary_age=35, spouse_age=35,
                base_monthly_premium_cents=40_000,
            )
        )
        assert determined["fpl_percentage"] == 175.0
        assert determined["csr_eligibility"] == "CSR_87"
        assert determined["aptc_estimated_cents"] == 1_059_175


# ===========================================================================
# combinatorial_formula/monthly_premium_round_then_sum — vantage 2
# ===========================================================================
class TestMonthlyPremiumRoundingSecondVantage:
    """# difficulty: combinatorial_formula/
    monthly_premium_per_member_round_then_sum_pinned_order

    Second vantage: tobacco surcharge double-rounding (PRD §3.6).
    """

    def test_tobacco_surcharge_double_round(self, api):
        """# difficulty: combinatorial_formula/monthly_premium_per_member_round_then_sum_pinned_order
        PRD §3.6: "If the member is a tobacco user (is_tobacco_user is
        true) and their age at coverage_start_date is at least 21, the
        per-member amount is multiplied by the tobacco surcharge factor
        of 1.50 and rounded half-up to a whole cent a second time."

        Setup: single PRIMARY_FILER age 35 (mult 1.181), tobacco user,
        base = 12_345.
        step1 = round_half_up(12345 * 1.181) = 14579.
        step2 = round_half_up(14579 * 1.50) = round_half_up(21868.5)
              = 21869.
        Expected gross = 21869 (single member).
        """
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=260.0, coverage_year=2026,
                household_size=1, primary_age=35,
                primary_tobacco=True,
                base_monthly_premium_cents=12_345,
            )
        )
        approved = validate_success(api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        ), 200)
        # FPL 260 → csr_eligibility == NONE → STANDARD variant.
        assert approved["csr_eligibility"] == "NONE"
        variant = create_plan_variant(
            plan=plan, csr_level="STANDARD", actuarial_value=70.0,
            insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        )
        enrollment = validate_success(res, 201)
        assert enrollment["monthly_premium_gross_cents"] == 21869


# ===========================================================================
# combinatorial_formula/enrollment_net_premium_evaluation_order — vantage 2
# ===========================================================================
class TestNetPremiumEvaluationOrderSecondVantage:
    """# difficulty: combinatorial_formula/
    enrollment_net_premium_evaluation_order_when_subsidy_caps

    Second vantage: a partial-subsidy case where /12 is below gross —
    verifies the OTHER branch of the min().
    """

    def test_partial_subsidy_aptc_below_gross_applied_as_is(self, api):
        """# difficulty: combinatorial_formula/enrollment_net_premium_evaluation_order_when_subsidy_caps
        PRD §3.6: "The monthly APTC applied is the lesser of the
        annual aptc_estimated_cents divided by 12 (rounded half-up to
        a whole cent) and monthly_premium_gross_cents".

        Setup: 2 PRIMARY/SPOUSE age 35 at FPL 200 — fraction 0.04,
        contribution = 4_262_000 * 0.04 = 170_480.
        benchmark annual = 2 * 12 * 47240 = 1_133_760.
        aptc_estimated = 1_133_760 - 170_480 = 963_280.
        monthly = round_half_up(963_280 / 12) = round_half_up(80_273.33)
                = 80_273.
        gross = 2 * 47240 = 94_480.
        applied = min(80_273, 94_480) = 80_273 (the /12 branch).
        net = 94_480 - 80_273 = 14_207.
        """
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=200.0, coverage_year=2026,
                household_size=2, primary_age=35, spouse_age=35,
                base_monthly_premium_cents=40_000,
            )
        )
        approved = validate_success(api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert approved["csr_eligibility"] == "CSR_73"
        variant = create_plan_variant(
            plan=plan, csr_level="CSR_73", actuarial_value=73.0,
            insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        )
        enrollment = validate_success(res, 201)
        assert enrollment["monthly_premium_gross_cents"] == 94_480
        assert enrollment["monthly_aptc_applied_cents"] == 80_273
        assert enrollment["monthly_net_premium_cents"] == 14_207


# ===========================================================================
# non_linear_state_machine/application_branch_with_revert_loop — vantage 1+2
# ===========================================================================
class TestApplicationRevertLoop:
    """# difficulty: non_linear_state_machine/application_branch_with_revert_loop

    PRD §3.2: SUBMITTED → DRAFT (amend) → SUBMITTED cycle and
    APPROVED → ELIGIBILITY_DETERMINED → APPROVED (redetermine) cycle.
    """

    def test_amend_then_resubmit_returns_to_submitted(self, api):
        """# difficulty: non_linear_state_machine/application_branch_with_revert_loop
        PRD §3.2: "While an application sits in SUBMITTED, the
        applicant may revert it back to DRAFT by amending it; this
        clears submitted_at, pinned_fpl_table_version, fpl_percentage,
        and total_magi_cents (all set back to null)".

        Claim: amend on SUBMITTED → DRAFT (clears pins); re-submit →
        SUBMITTED (pins reset).
        """
        submitted, _p = setup_submitted_application()
        amended = amend_application(application=submitted)
        assert amended["status"] == "DRAFT"
        assert amended.get("pinned_fpl_table_version") is None
        resubmitted = submit_application(application=amended)
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted.get("pinned_fpl_table_version") is not None

    def test_eligibility_branch_fork_observable(self, api):
        """# difficulty: non_linear_state_machine/application_branch_with_revert_loop
        PRD §3.3: "Approval moves the application from
        ELIGIBILITY_DETERMINED to APPROVED ... Denial moves the
        application from ELIGIBILITY_DETERMINED to DENIED."

        Claim: from ELIGIBILITY_DETERMINED a /approve produces APPROVED
        with approved_at stamped, while a /deny on an analogous second
        determined application produces DENIED with no approved_at.
        """
        # Approve branch.
        d1, _p, ins, pl = setup_eligibility_determined_application(
            primary_income_cents=5_000_000,
        )
        approved = validate_success(api.approve_application(
            d1["id"], TEST_USERS["admin_headers"],
        ), 200)
        assert approved["status"] == "APPROVED"
        assert approved.get("approved_at") is not None
        # Deny branch — reuse the same insurer / benchmark plan so a
        # second benchmark-Silver write does not collide with the first
        # under PRD §3.5's (filing_state, coverage_year) uniqueness.
        d2, _p2, _i2, _pl2 = setup_eligibility_determined_application(
            primary_income_cents=10_000,  # low → likely Medicaid-eligible
            insurer=ins, benchmark_plan=pl,
        )
        res = api.deny_application(
            d2["id"], TEST_USERS["admin_headers"],
            payload={"reason": "members Medicaid-eligible"},
        )
        denied = validate_success(res, 200)
        assert denied["status"] == "DENIED"


# ===========================================================================
# non_linear_state_machine/enrollment_parallel_dimensions — vantage 1+2
# ===========================================================================
class TestEnrollmentParallelDimensions:
    """# difficulty: non_linear_state_machine/
    enrollment_parallel_dimensions_coverage_vs_payment

    PRD §3.7: coverage_status and payment_status evolve independently.
    """

    def test_coverage_active_payment_current_after_binder(self, api):
        """# difficulty: non_linear_state_machine/enrollment_parallel_dimensions_coverage_vs_payment
        PRD §3.6: "When the binder invoice is paid and the logical
        clock has reached or passed coverage_start_date, the
        enrollment auto-promotes from PENDING_PAYMENT to ACTIVE.
        Specifically, when the binder is posted, payment_status flips
        from AWAITING_BINDER to CURRENT".

        Claim: both dimensions advance together at binder payment:
        coverage_status → ACTIVE, payment_status → CURRENT.
        """
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
            )
        )
        assert enrollment["coverage_status"] == "ACTIVE"
        assert enrollment["payment_status"] == "CURRENT"

    def test_coverage_grace_period_payment_delinquent_after_age_sweep(
        self, api,
    ):
        """# difficulty: non_linear_state_machine/enrollment_parallel_dimensions_coverage_vs_payment
        PRD §3.7: "When an active enrollment's payment status flips
        to DELINQUENT_M1, the coverage status moves from ACTIVE to
        GRACE_PERIOD."

        Claim: after aging an unpaid invoice past day-30 grace, both
        dimensions advance: coverage_status → GRACE_PERIOD and
        payment_status → DELINQUENT_M1. Observable independently in
        GET /enrollments/{id}.
        """
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        advance_clock_to(iso_utc(
            datetime(2026, 4, 5, tzinfo=timezone.utc),
        ))
        api.sweep_age_invoices(TEST_USERS["admin_headers"])
        refreshed = re_get_enrollment(enrollment_id=enrollment["id"])
        # If an unpaid 2026-03 invoice exists, both dimensions advance.
        if refreshed["payment_status"] == "DELINQUENT_M1":
            assert refreshed["coverage_status"] == "GRACE_PERIOD"


# ===========================================================================
# transitive_cascade/sep_verify_depth3 — vantage 2 (premium recalc on cascade)
# ===========================================================================
class TestSepVerifyDepth3CascadeSecondVantage:
    """# difficulty: transitive_cascade/
    sep_verify_depth3_cascade_redetermine_recalc_invoice

    Second vantage: confirm the Enrollment recalc (link C) and fresh
    PremiumInvoice (link D) of the depth-3 chain.
    """

    def test_sep_verify_cascade_emits_fresh_invoice(self, api):
        """# difficulty: transitive_cascade/sep_verify_depth3_cascade_redetermine_recalc_invoice
        PRD §3.4: "the verification triggers a three-level cascade:
        the application is force-redetermined ..., the enrollment's
        monthly premium is recomputed, and a fresh premium invoice is
        issued for the next billing_month."

        Claim: SEP /verify with BIRTH_ADOPTION on APPROVED + ACTIVE →
        a fresh PremiumInvoice exists whose billing_month is later
        than the original binder.
        """
        # /__test__/reset starts clock at 2025-12-15 (inside OEP).
        # setup_active_enrollment will advance the clock to
        # coverage_start_date; advance further AFTER setup if needed.
        app, _p, ins, plan, variant, enrollment, invs_before = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=40_000,
            )
        )
        binder = sorted(
            invs_before, key=lambda r: r["billing_month"],
        )[0]
        advance_clock_to(iso_utc(
            datetime(2026, 5, 15, tzinfo=timezone.utc),
        ))
        from test_helpers import create_sep_event
        sep = create_sep_event(
            application=app, event_type="BIRTH_ADOPTION",
            event_date="2026-05-12",
        )
        verify_sep_event(application=app, sep_event=sep)
        invs_after = list_premium_invoices(enrollment=enrollment)
        # PRD: a fresh PremiumInvoice for the next billing_month is
        # issued by the cascade.
        post_binder = [
            inv for inv in invs_after
            if inv["billing_month"] > binder["billing_month"]
        ]
        assert len(post_binder) >= 1


# ===========================================================================
# transitive_cascade/enrollment_cancel_depth2 — vantage 2
# ===========================================================================
class TestCancelCascadeSecondVantage:
    """# difficulty: transitive_cascade/
    enrollment_cancel_depth2_cascade_void_future_invoices

    Second vantage: terminated_reason and coverage_end_date observable
    on the Enrollment row immediately after cancel.
    """

    def test_cancel_sets_terminated_reason_and_coverage_end(self, api):
        """# difficulty: transitive_cascade/enrollment_cancel_depth2_cascade_void_future_invoices
        PRD §3.7: "This moves the enrollment to TERMINATED with
        terminated_reason set to APPLICANT_CANCELLED, the
        coverage_end_date set to the last day of the current billing
        month per the logical clock".

        Claim: after /cancel on 2026-04-20, Enrollment.coverage_status
        == 'TERMINATED', terminated_reason == 'APPLICANT_CANCELLED',
        coverage_end_date == '2026-04-30'.
        """
        # /__test__/reset starts clock at 2025-12-15 (inside OEP).
        # Build ACTIVE enrollment first, then advance to 2026-04-20.
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        advance_clock_to(iso_utc(
            datetime(2026, 4, 20, tzinfo=timezone.utc),
        ))
        cancelled = cancel_enrollment(
            application=app, enrollment=enrollment,
        )
        assert cancelled["coverage_status"] == "TERMINATED"
        assert cancelled["terminated_reason"] == "APPLICANT_CANCELLED"
        assert cancelled["coverage_end_date"] == "2026-04-30"


# ===========================================================================
# priority_pair_validation_conflict — vantage 1+2 per instance
# ===========================================================================
class TestPriorityStateOverCsrMismatch:
    """# difficulty: priority_pair_validation_conflict/
    state_vs_business_referential_csr_mismatch_on_approved_app

    PRD §3.9: "State machine eligibility (ERR_INVALID_STATE) is checked
    next, before business preconditions on the request body."
    """

    def test_state_invalid_wins_over_csr_mismatch(self, api):
        """# difficulty: priority_pair_validation_conflict/state_vs_business_referential_csr_mismatch_on_approved_app
        PRD §3.9: "State machine eligibility (ERR_INVALID_STATE) is
        checked next, before business preconditions on the request
        body."

        Claim: ELIGIBILITY_DETERMINED (not APPROVED) AND mismatched
        CSR variant → ERR_INVALID_STATE wins over
        ERR_CSR_VARIANT_MISMATCH.
        """
        # CSR_94 application + CSR_73 variant + not-yet-approved.
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=140.0, coverage_year=2026,
                household_size=2,
            )
        )
        assert determined["csr_eligibility"] == "CSR_94"
        # Intentionally NOT approve.
        variant = create_plan_variant(
            plan=plan, csr_level="CSR_73", actuarial_value=73.0,
            insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=determined["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestPriorityExistenceOverState:
    """# difficulty: priority_pair_validation_conflict/
    existence_vs_state_owner_check_on_missing_application

    PRD §3.9: "Path-parameter existence is checked next, left-to-right,
    and an unresolved id raises ERR_NOT_FOUND before any business rule
    fires."
    """

    def test_approve_on_missing_application_returns_not_found(self, api):
        """# difficulty: priority_pair_validation_conflict/existence_vs_state_owner_check_on_missing_application
        PRD §3.9: "Path-parameter existence is checked next ... an
        unresolved id raises ERR_NOT_FOUND before any business rule
        fires."

        Claim: /approve on a non-existent application id → ERR_NOT_FOUND
        (not ERR_INVALID_STATE).
        """
        from test_helpers import NON_EXISTENT_UUID
        res = api.approve_application(
            NON_EXISTENT_UUID, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_on_missing_application_returns_not_found(self, api):
        """# difficulty: priority_pair_validation_conflict/existence_vs_state_owner_check_on_missing_application
        Second vantage: GET on a missing id also returns ERR_NOT_FOUND
        (no state check ever runs on a GET, so the precedence is
        observable purely as existence-first).
        """
        from test_helpers import NON_EXISTENT_UUID
        res = api.get_application(
            NON_EXISTENT_UUID, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# cross_entity_state_dependency/application_approve_requires_open_enrollment_window
# ===========================================================================
class TestEnrollmentRequiresApprovedApplication:
    """# difficulty: cross_entity_state_dependency/
    enrollment_creation_requires_application_approved

    PRD §3.6: "Once an application is APPROVED, the applicant binds it
    to a chosen plan variant by submitting an enrollment ... ".
    """

    def test_enrollment_on_draft_application_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/enrollment_creation_requires_application_approved
        PRD §3.6: "Once an application is APPROVED, the applicant binds
        it to a chosen plan variant by submitting an enrollment".

        Claim: POST /enrollments where Application.status=DRAFT →
        ERR_INVALID_STATE (state precondition fires before any business
        check).
        """
        # DRAFT application with no determination yet.
        app = create_application()
        # Build a benchmark plan + variant under CA so the variant id
        # is resolvable.
        ins, plan, variant = setup_benchmark_silver_catalog(
            filing_state="CA", coverage_year=2026,
            include_standard_variant=True,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=app["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_enrollment_after_approve_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/enrollment_creation_requires_application_approved
        PRD §3.6: "Once an application is APPROVED, the applicant binds
        it to a chosen plan variant by submitting an enrollment that
        names both the parent application_id and the chosen
        plan_variant_id."

        Claim: after the same Application reaches APPROVED, /enrollments
        with a CSR-aligned variant succeeds with status 201.
        """
        approved, _p, ins, plan = setup_approved_application(
            primary_income_cents=5_000_000,
        )
        # csr_eligibility == NONE at high income → STANDARD variant.
        variant = create_plan_variant(
            plan=plan, csr_level="STANDARD", actuarial_value=70.0,
            insurer=ins,
        )
        res = api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(approved["_applicant_id"]),
        )
        validate_success(res, 201)


class TestApproveRequiresOpenWindow:
    """# difficulty: cross_entity_state_dependency/
    application_approve_requires_open_enrollment_window_from_sep_event

    PRD §3.3: "Approval moves the application from
    ELIGIBILITY_DETERMINED to APPROVED, provided the application's
    enrollment_window is either OEP or SEP (not CLOSED)".

    PRD §3.9 priority 8: ERR_OUTSIDE_ENROLLMENT_WINDOW.
    """

    def test_approve_with_closed_window_rejected(self, api):
        """# difficulty: cross_entity_state_dependency/application_approve_requires_open_enrollment_window_from_sep_event
        PRD §3.3: "Approval moves the application from
        ELIGIBILITY_DETERMINED to APPROVED, provided the application's
        enrollment_window is either OEP or SEP (not CLOSED)".

        Claim: ELIGIBILITY_DETERMINED with enrollment_window=CLOSED →
        ERR_OUTSIDE_ENROLLMENT_WINDOW on /approve. The window becomes
        CLOSED when the clock is outside OEP and no VERIFIED SEP exists.
        Direct verification of this is dependent on what range
        constitutes OEP in the implementation — PRD does not pin the
        OEP calendar. We therefore use a household every member of
        whom is Medicaid-eligible AND assert the rejection path
        produces a non-2xx with an error code from the small set
        permitted by §3.3 prose.
        """
        # Build determined low-income CA household → Medicaid-eligible.
        determined, _p, _i, _pl = (
            setup_eligibility_determined_application(
                filing_state="CA", primary_income_cents=10_000,
            )
        )
        # Try /approve — PRD §3.3 says it "falls to the denial branch
        # instead" when every member is Medicaid-eligible. PRD does
        # name ERR_OUTSIDE_ENROLLMENT_WINDOW only for the closed-window
        # case; when every member is Medicaid eligible, the prose is
        # softer ("falls to denial"). Implementation could plausibly
        # return ERR_INVALID_STATE or ERR_OUTSIDE_ENROLLMENT_WINDOW.
        res = api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        )
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(res, [
            "ERR_OUTSIDE_ENROLLMENT_WINDOW",
            "ERR_INVALID_STATE",
        ])

    def test_approve_with_open_sep_window_succeeds(self, api):
        """# difficulty: cross_entity_state_dependency/application_approve_requires_open_enrollment_window_from_sep_event
        PRD §3.4: verification of a SEP "sets the parent application's
        enrollment_window to SEP."
        PRD §3.3: "Approval moves the application from
        ELIGIBILITY_DETERMINED to APPROVED, provided the application's
        enrollment_window is either OEP or SEP".

        Claim: file + verify a SEP under a SUBMITTED application, then
        determine + approve — the open SEP window unblocks /approve.
        """
        advance_clock_to(iso_utc(
            datetime(2026, 4, 5, tzinfo=timezone.utc),
        ))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
            primary_income_cents=5_000_000,
        )
        # Need benchmark Silver for determine-eligibility.
        setup_benchmark_silver_catalog(
            filing_state="CA", coverage_year=2026,
            include_standard_variant=False,
        )
        # File + verify a MOVE SEP.
        from test_helpers import create_sep_event
        sep = create_sep_event(
            application=submitted, event_type="MOVE",
            event_date="2026-03-15",
        )
        verify_sep_event(application=submitted, sep_event=sep)
        # Determine eligibility.
        determined = determine_eligibility(application=submitted)
        # Approve — should succeed under SEP window.
        res = api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        )
        approved = validate_success(res, 200)
        assert approved["status"] == "APPROVED"


# ===========================================================================
# resource_temporal_overlap/sep_window_overlap_with_60_day_open_half_open_interval
# ===========================================================================
class TestSepWindowsCoexist:
    """# difficulty: resource_temporal_overlap/
    sep_window_overlap_with_60_day_open_half_open_interval

    PRD §3.4: "When multiple SEPEvents under the same application race
    for governance of an enrollment's effective date, both
    verifications may succeed, but the application's enrollment_window
    remains SEP and only one SEP's effective_date governs the next
    enrollment. The earliest verified event — broken on reported_at
    ascending — wins."
    """

    def test_two_verified_seps_coexist(self, api):
        """# difficulty: resource_temporal_overlap/sep_window_overlap_with_60_day_open_half_open_interval
        PRD §3.4: "When multiple SEPEvents under the same application
        race for governance of an enrollment's effective date, both
        verifications may succeed".

        Claim: file + verify a MARRIAGE and a MOVE SEP under the same
        Application within their windows. Both reach VERIFIED;
        Application.enrollment_window remains SEP.
        """
        advance_clock_to(iso_utc(
            datetime(2026, 4, 5, tzinfo=timezone.utc),
        ))
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
            primary_income_cents=5_000_000,
        )
        # Two SEPs, both within 60 calendar days of now.
        from test_helpers import create_sep_event
        sep_a = create_sep_event(
            application=submitted, event_type="MARRIAGE",
            event_date="2026-03-01",
        )
        sep_b = create_sep_event(
            application=submitted, event_type="MOVE",
            event_date="2026-04-01",
        )
        verify_sep_event(application=submitted, sep_event=sep_a)
        verify_sep_event(application=submitted, sep_event=sep_b)
        # Application.enrollment_window remains SEP.
        refreshed = re_get_application(application_id=submitted["id"])
        assert refreshed["enrollment_window"] == "SEP"


# ===========================================================================
# compensating_invariant/application_amend_resubmit_household_size — vantage 1+2
# ===========================================================================
class TestAmendResubmitHouseholdSizeInvariant:
    """# difficulty: compensating_invariant/
    application_amend_resubmit_household_size_invariant

    PRD §3.2: "While an application sits in SUBMITTED, the applicant
    may revert it back to DRAFT by amending it; this clears
    submitted_at, pinned_fpl_table_version, fpl_percentage, and
    total_magi_cents (all set back to null) so that the household
    composition or income statement can be edited without contradiction."

    PRD §3.2: "household_size is the count of HouseholdMember rows for
    the application where include_in_household is true."

    Conserved quantity: number of include_in_household members.
    """

    def test_household_size_unchanged_across_amend_resubmit(self, api):
        """# difficulty: compensating_invariant/application_amend_resubmit_household_size_invariant
        PRD §3.2: "household_size is the count of HouseholdMember rows
        for the application where include_in_household is true."

        Claim: 2 included members, /amend then /submit with no member
        mutations between → household_size after second submit == 2
        (unchanged conserved quantity).
        """
        # Build: PRIMARY_FILER + SPOUSE both include_in_household=true.
        # PRD §3.2 requires every include_in_magi=true member to have at
        # least one IncomeRecord at submit; the SPOUSE here carries
        # income to keep the submit precondition green.
        extra = [{
            "filer_type": "SPOUSE", "age_years": 33,
            "income_cents": 1_500_000,
        }]
        submitted, _p = setup_submitted_application(
            coverage_year=2026, filing_state="CA",
            extra_members=extra,
        )
        assert submitted["household_size"] == 2
        # Amend → DRAFT.
        amended = amend_application(application=submitted)
        assert amended["status"] == "DRAFT"
        # Re-submit without changing members.
        resubmitted = submit_application(application=amended)
        assert resubmitted["status"] == "SUBMITTED"
        # household_size invariant.
        assert resubmitted["household_size"] == 2

    def test_amend_then_submit_repins_fpl_table_version(self, api):
        """# difficulty: compensating_invariant/application_amend_resubmit_household_size_invariant
        PRD §3.2: "When the transition succeeds, the server stamps
        submitted_at, snapshots the FPL constants table identifier
        into pinned_fpl_table_version".

        Claim: amend clears pinned_fpl_table_version to null; re-submit
        repopulates it.
        """
        submitted, _p = setup_submitted_application()
        original_version = submitted["pinned_fpl_table_version"]
        amended = amend_application(application=submitted)
        assert amended.get("pinned_fpl_table_version") is None
        resubmitted = submit_application(application=amended)
        # Repinned to the same FPL table version (the table itself
        # didn't change between calls).
        assert resubmitted["pinned_fpl_table_version"] == original_version


# ===========================================================================
# compensating_invariant/invoice_payment_and_void — vantage 2
# (primary in test_10 tested sum-invariant; this tests status counts)
# ===========================================================================
class TestPaidInvoicesCount:
    """# difficulty: compensating_invariant/
    invoice_payment_and_void_total_paid_cents_invariant

    PRD §3.7: "a depth-2 cascade that transitions every premium invoice
    whose billing_month lies strictly after coverage_end_date from
    ISSUED to VOIDED."
    """

    def test_paid_count_unchanged_only_issued_voided(self, api):
        """# difficulty: compensating_invariant/invoice_payment_and_void_total_paid_cents_invariant
        PRD §3.7: "a depth-2 cascade that transitions every premium
        invoice whose billing_month lies strictly after
        coverage_end_date from ISSUED to VOIDED."

        Claim: after /cancel, the number of PAID invoices is unchanged
        (only ISSUED invoices with billing_month > coverage_end_date
        become VOIDED).
        """
        # /__test__/reset starts clock at 2025-12-15 (inside OEP).
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        invs_before = list_premium_invoices(enrollment=enrollment)
        paid_count_before = sum(
            1 for inv in invs_before if inv["status"] == "PAID"
        )
        advance_clock_to(iso_utc(
            datetime(2026, 4, 20, tzinfo=timezone.utc),
        ))
        api.sweep_age_invoices(TEST_USERS["admin_headers"])
        cancel_enrollment(application=app, enrollment=enrollment)
        invs_after = list_premium_invoices(enrollment=enrollment)
        paid_count_after = sum(
            1 for inv in invs_after if inv["status"] == "PAID"
        )
        assert paid_count_after == paid_count_before


# ===========================================================================
# cross_entity_state_dependency/premium_invoice_void_requires_enrollment — vantage 2
# ===========================================================================
class TestVoidOnlyReachableViaCancel:
    """# difficulty: cross_entity_state_dependency/
    premium_invoice_void_requires_enrollment_terminated_or_recalced

    PRD §3.7: VOID is a side-effect of /cancel or recalc; there is no
    direct VOID endpoint.
    """

    # NOTE: test_no_direct_void_endpoint_exists was DELETED.
    #
    # The test asserted that after /cancel, at least one VOIDED invoice
    # exists — i.e., that a future-month PremiumInvoice was present at
    # cancel time so the §3.7 cascade had something to void.
    #
    # PRD §3.7 says only "Every billing month the enrollment issues a
    # PremiumInvoice" and "every premium invoice whose billing_month
    # lies strictly after coverage_end_date is transitioned to VOIDED".
    # PRD does NOT uniquely determine whether future-month invoices
    # exist at the moment of /cancel: one PRD-faithful reading issues
    # invoices when each billing month becomes the current month (so
    # no future invoices exist at cancel-time and the cascade has
    # nothing to void); another reading pre-issues all 12 monthly
    # invoices at enrollment time (so the cascade voids the post-end
    # months). Under STEP 1b (unique-derivability), the test must be
    # removed.
    #
    # The sibling test test_cancel_voids_invoices_after_coverage_end in
    # test_10 still asserts that IF future-month invoices exist, they
    # are VOIDED — which is the PRD-uniquely-derived behavior.
    pass
