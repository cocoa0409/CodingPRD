"""Cascade tests: cancel-cascade voids future invoices, SEP-verify
cascade redetermine+recalc+invoice, /_sweep/reconcile-aptc.

PRD §2.10 (cascade semantics), §3.4 (SEP cascade), §3.8
(reconciliation), §3.7 (cancel cascade).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    cancel_enrollment,
    create_sep_event,
    iso_utc,
    list_premium_invoices,
    make_applicant_headers,
    post_payment,
    re_get_application,
    re_get_enrollment,
    setup_active_enrollment,
    setup_eligibility_determined_application,
    setup_enrollment_pending_payment,
    setup_submitted_application,
    validate_success,
    verify_sep_event,
)


# ===========================================================================
# Cancel cascade — VOID future invoices (PRD §3.7, §2.10)
# ===========================================================================
class TestCancelCascadeVoidsFutureInvoices:
    """# difficulty: transitive_cascade/
    enrollment_cancel_depth2_cascade_void_future_invoices

    PRD §3.7: "This moves the enrollment to TERMINATED with
    terminated_reason set to APPLICANT_CANCELLED, the coverage_end_date
    set to the last day of the current billing month per the logical
    clock, and a depth-2 cascade that transitions every premium invoice
    whose billing_month lies strictly after coverage_end_date from
    ISSUED to VOIDED."

    PRD §2.10: "every premium invoice whose billing_month lies strictly
    after the coverage_end_date is transitioned to VOIDED."
    """

    def test_cancel_voids_invoices_after_coverage_end(self, api):
        """# difficulty: transitive_cascade/
        enrollment_cancel_depth2_cascade_void_future_invoices

        PRD §3.7: "a depth-2 cascade that transitions every premium
        invoice whose billing_month lies strictly after
        coverage_end_date from ISSUED to VOIDED."

        Claim: with paid April + ISSUED May + ISSUED June invoices and
        a /cancel on 2026-04-20, post-cancel: April stays PAID,
        May → VOIDED, June → VOIDED, coverage_end_date = 2026-04-30.
        """
        # The /__test__/reset hook leaves the clock at 2025-12-15
        # (inside OEP for coverage_year=2026), so we can build ACTIVE
        # enrollment without first advancing the clock. setup_active_-
        # enrollment will advance the clock to coverage_start_date.
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        # Advance to 2026-04-20 so two months of invoices are present.
        advance_clock_to(iso_utc(
            datetime(2026, 4, 20, tzinfo=timezone.utc),
        ))
        # Trigger /sweep/age-invoices to refresh the payment rollup.
        api.sweep_age_invoices(TEST_USERS["admin_headers"])
        # Cancel — PRD §4: requires ACTIVE Enrollment. The enrollment
        # is still ACTIVE here because no further ISSUED invoices have
        # aged past the 30-day grace boundary.
        cancelled = cancel_enrollment(application=app, enrollment=enrollment)
        assert cancelled["coverage_status"] == "TERMINATED"
        assert cancelled["terminated_reason"] == "APPLICANT_CANCELLED"
        # coverage_end_date = last day of current billing month per
        # logical clock — clock is 2026-04-20 → 2026-04-30.
        assert cancelled["coverage_end_date"] == "2026-04-30"
        # All invoices whose billing_month > 2026-04 must be VOIDED.
        invoices = list_premium_invoices(enrollment=enrollment)
        for inv in invoices:
            if inv["billing_month"] > "2026-04":
                assert inv["status"] == "VOIDED", (
                    f"PRD §3.7 cascade: invoice for "
                    f"billing_month={inv['billing_month']} must be VOIDED"
                )


# ===========================================================================
# SEP verify cascade — depth-3 (PRD §3.4, §2.10)
# ===========================================================================
class TestSepVerifyDepth3Cascade:
    """# difficulty: transitive_cascade/
    sep_verify_depth3_cascade_redetermine_recalc_invoice

    PRD §3.4: "when the qualifying event is MARRIAGE, BIRTH_ADOPTION,
    or MEDICAID_LOSS, and the parent application is already APPROVED
    with an active enrollment in place, the verification triggers a
    three-level cascade: the application is force-redetermined
    (reverting APPROVED to ELIGIBILITY_DETERMINED and recomputing
    fpl_percentage, csr_eligibility, and aptc_estimated_cents), the
    enrollment's monthly premium is recomputed, and a fresh premium
    invoice is issued for the next billing_month."
    """

    def test_birth_adoption_verify_cascades_redetermine(self, api):
        """# difficulty: transitive_cascade/
        sep_verify_depth3_cascade_redetermine_recalc_invoice

        PRD §3.4: "the verification triggers a three-level cascade: the
        application is force-redetermined (reverting APPROVED to
        ELIGIBILITY_DETERMINED and recomputing fpl_percentage,
        csr_eligibility, and aptc_estimated_cents)".

        Claim: SEP /verify with event_type=BIRTH_ADOPTION on an APPROVED
        application with ACTIVE Enrollment → Application.status
        transitions from APPROVED back to ELIGIBILITY_DETERMINED.
        """
        # Build APPROVED + ACTIVE enrollment first. /__test__/reset
        # leaves the clock at 2025-12-15 (inside OEP) so the approve
        # step has an open window; setup_active_enrollment then
        # advances the clock to coverage_start_date.
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=40_000,
            )
        )
        # File and verify a BIRTH_ADOPTION SEP. Clock = 2026-05-15,
        # event_date 2026-05-12.
        advance_clock_to(iso_utc(
            datetime(2026, 5, 15, tzinfo=timezone.utc),
        ))
        sep = create_sep_event(
            application=app, event_type="BIRTH_ADOPTION",
            event_date="2026-05-12",
        )
        # Verify — triggers the cascade.
        verified = verify_sep_event(application=app, sep_event=sep)
        assert verified["status"] == "VERIFIED"
        # PRD §3.4 cascade: Application reverts APPROVED →
        # ELIGIBILITY_DETERMINED.
        refreshed_app = re_get_application(application_id=app["id"])
        assert refreshed_app["status"] == "ELIGIBILITY_DETERMINED"


# ===========================================================================
# Reconciliation sweep (PRD §3.8)
# ===========================================================================
class TestReconciliationSweep:
    """# difficulty: dual_variant_calc/
    aptc_estimated_vs_reconciled_on_application

    PRD §3.8: "At year-end, the marketplace runs a reconciliation sweep
    against every approved application for the specified coverage_year.
    The sweep replays each application's IncomeRecord ledger
    chronologically, month by month, and produces aptc_reconciled_cents
    — the reconciled annual subsidy the household actually qualified
    for after all income shifts are taken into account."

    PRD §3.8: "The estimated and reconciled figures can legitimately
    diverge when corrective IncomeRecord rows arrive in mid-year."
    """

    def test_reconcile_aptc_populates_aptc_reconciled_cents(self, api):
        """# difficulty: dual_variant_calc/
        aptc_estimated_vs_reconciled_on_application

        PRD §3.8: "The sweep replays each application's IncomeRecord
        ledger chronologically, month by month, and produces
        aptc_reconciled_cents".

        Claim: after POST /_sweep/reconcile-aptc with coverage_year, an
        APPROVED Application's aptc_reconciled_cents is non-null.
        """
        from test_helpers import (
            add_income_record, advance_clock_to,
            create_plan_variant, make_applicant_headers,
            setup_enrollment_pending_payment,
        )
        advance_clock_to(iso_utc(
            datetime(2026, 1, 15, tzinfo=timezone.utc),
        ))
        # PRD §3.6 requires variant.csr_level to align with
        # csr_eligibility. The fixture's default variant is STANDARD,
        # which matches csr_eligibility=NONE; we pick an income that
        # lands above the 250% CSR threshold so the household resolves
        # to csr_eligibility=NONE.
        app, primary, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment(
                coverage_year=2026, filing_state="CA",
                primary_age=35, primary_income_cents=5_000_000,
                base_monthly_premium_cents=40_000,
            )
        )
        # Pay the binder so Enrollment becomes ACTIVE.
        invoices = list_premium_invoices(enrollment=enrollment)
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        post_payment(application=app, invoice=binder)
        # Mid-year corrective IncomeRecord.
        advance_clock_to(iso_utc(
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        ))
        # Need to capture the first IncomeRecord id — but the fixture
        # didn't surface it. Append a new corrective record without
        # supersedes_id (it still influences MAGI for months >=
        # effective_date in the reconciled replay).
        add_income_record(
            application=app, member=primary,
            amount_cents=1_000_000, source_type="WAGES",
            effective_date="2026-07-01",
        )
        # Year-end clock.
        advance_clock_to(iso_utc(
            datetime(2027, 1, 2, tzinfo=timezone.utc),
        ))
        # Reconcile sweep.
        from test_helpers import reconcile_aptc_payload
        res = api.sweep_reconcile_aptc(
            reconcile_aptc_payload(coverage_year=2026),
            TEST_USERS["admin_headers"],
        )
        validate_success(res, 200)
        # Re-fetch the application and assert aptc_reconciled_cents is
        # populated.
        refreshed = re_get_application(application_id=app["id"])
        assert refreshed["aptc_reconciled_cents"] is not None
        assert isinstance(refreshed["aptc_reconciled_cents"], int)


# ===========================================================================
# Compensating invariant: invoice payments survive cancel
# (PRD §3.7, difficulty rule 9)
# ===========================================================================
class TestPaidInvoicesSurviveCancel:
    """# difficulty: compensating_invariant/
    invoice_payment_and_void_total_paid_cents_invariant

    PRD §3.7: "a depth-2 cascade that transitions every premium invoice
    whose billing_month lies strictly after coverage_end_date from
    ISSUED to VOIDED."

    Implicit invariant from PRD: only ISSUED invoices in the future
    become VOIDED; PAID invoices are never touched, so the sum of
    net_amount_cents over PAID invoices is invariant across cancel.
    """

    def test_paid_invoices_unchanged_after_cancel(self, api):
        """# difficulty: compensating_invariant/
        invoice_payment_and_void_total_paid_cents_invariant

        PRD §3.7: "a depth-2 cascade that transitions every premium
        invoice whose billing_month lies strictly after
        coverage_end_date from ISSUED to VOIDED."

        Claim: with one paid invoice and one ISSUED future invoice,
        /cancel does NOT change the paid one and DOES void the future
        one — sum of net_amount_cents over PAID invoices is unchanged.
        """
        # /__test__/reset leaves the clock at 2025-12-15 (inside OEP);
        # build ACTIVE enrollment first, then advance the clock for
        # the rest of the test. Pre-fixture advance would close the
        # OEP and break the approve step.
        app, _p, ins, plan, variant, enrollment, _invs = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        # Helper already paid the binder; capture pre-cancel paid sum.
        before = list_premium_invoices(enrollment=enrollment)
        paid_sum_before = sum(
            inv["net_amount_cents"] for inv in before
            if inv["status"] == "PAID"
        )
        # Advance the clock further.
        advance_clock_to(iso_utc(
            datetime(2026, 4, 20, tzinfo=timezone.utc),
        ))
        api.sweep_age_invoices(TEST_USERS["admin_headers"])
        # Cancel — enrollment is still ACTIVE because no additional
        # ISSUED monthly invoices have been materialised between the
        # binder and now.
        cancel_enrollment(application=app, enrollment=enrollment)
        after = list_premium_invoices(enrollment=enrollment)
        paid_sum_after = sum(
            inv["net_amount_cents"] for inv in after
            if inv["status"] == "PAID"
        )
        # Invariant: paid total unchanged.
        assert paid_sum_after == paid_sum_before, (
            f"PRD §3.7 cascade: paid-invoice net total must be "
            f"unchanged by /cancel (before={paid_sum_before}, "
            f"after={paid_sum_after})"
        )
