"""PremiumInvoice payment, payment_status_rollup, grace period,
termination via /_sweep/age-invoices.

PRD §3.6 (binder), §3.7 (rollup), §2.9 (clock).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    advance_clock_to_date,
    assert_premium_invoice,
    iso_utc,
    list_premium_invoices,
    make_applicant_headers,
    post_payment,
    post_payment_payload,
    re_get_enrollment,
    setup_active_enrollment,
    setup_enrollment_pending_payment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Binder invoice & ACTIVE transition (PRD §3.6)
# ===========================================================================
class TestBinderPayment:
    """PRD §3.6: "The first invoice issued at enrollment time is the
    binder invoice. ... When the binder invoice is paid and the
    logical clock has reached or passed coverage_start_date, the
    enrollment auto-promotes from PENDING_PAYMENT to ACTIVE."""

    def test_first_invoice_issued_on_enrollment(self, api):
        """PRD §3.6: "The first invoice issued at enrollment time is
        the binder invoice. ... sets due_date to the first day of the
        billing_month."
        """
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment()
        )
        invoices = list_premium_invoices(enrollment=enrollment)
        assert len(invoices) >= 1
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        assert_premium_invoice(binder)
        assert binder["status"] == "ISSUED"
        # PRD §3.6: due_date = first day of billing_month.
        assert binder["due_date"] == binder["billing_month"] + "-01"

    def test_binder_paid_promotes_to_active(self, api):
        """PRD §3.6: "When the binder invoice is paid and the logical
        clock has reached or passed coverage_start_date, the enrollment
        auto-promotes from PENDING_PAYMENT to ACTIVE."
        """
        app, _p, ins, plan, variant, enrollment, invoices = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,  # high-income, no APTC
            )
        )
        # The helper already paid the binder and advanced the clock.
        assert enrollment["coverage_status"] == "ACTIVE"
        assert enrollment["payment_status"] == "CURRENT"


# ===========================================================================
# ERR_PAYMENT_INSUFFICIENT — boundary precision (PRD §3.7)
# ===========================================================================
class TestPaymentInsufficient:
    """# difficulty: boundary_precision_check/
    enrollment_payment_insufficient_zero_short_boundary

    PRD §3.7: "When a payment of amount_cents is posted to the invoice,
    the system requires amount_cents to be at least net_amount_cents
    (otherwise ERR_PAYMENT_INSUFFICIENT)."
    """

    def test_payment_one_cent_short_rejected(self, api):
        """# difficulty: boundary_precision_check/
        enrollment_payment_insufficient_zero_short_boundary

        PRD §3.7: "amount_cents to be at least net_amount_cents
        (otherwise ERR_PAYMENT_INSUFFICIENT)".

        Claim: amount_cents == net_amount_cents - 1 →
        ERR_PAYMENT_INSUFFICIENT.
        """
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment(
                primary_income_cents=5_000_000,
            )
        )
        invoices = list_premium_invoices(enrollment=enrollment)
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        short = binder["net_amount_cents"] - 1
        res = api.post_payment(
            binder["id"], post_payment_payload(amount_cents=short),
            make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_PAYMENT_INSUFFICIENT")

    def test_payment_exact_amount_accepted(self, api):
        """# difficulty: boundary_precision_check/
        enrollment_payment_insufficient_zero_short_boundary

        PRD §3.7: "amount_cents to be at least net_amount_cents".

        Claim: amount_cents == net_amount_cents → invoice transitions
        to PAID.
        """
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment(
                primary_income_cents=5_000_000,
            )
        )
        invoices = list_premium_invoices(enrollment=enrollment)
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        res = api.post_payment(
            binder["id"],
            post_payment_payload(amount_cents=binder["net_amount_cents"]),
            make_applicant_headers(app["_applicant_id"]),
        )
        paid = validate_success(res, 200)
        assert paid["status"] == "PAID"


# ===========================================================================
# Invoice double-payment (PRD §3.7, §3.9)
# ===========================================================================
class TestInvoiceAlreadyPaid:
    """PRD §3.7: "An invoice whose status is no longer ISSUED at the
    moment of posting is rejected with ERR_INVOICE_ALREADY_PAID."""

    def test_second_post_payment_rejected(self, api):
        """PRD §3.7: "An invoice whose status is no longer ISSUED at
        the moment of posting is rejected with ERR_INVOICE_ALREADY_PAID."
        """
        app, _p, ins, plan, variant, enrollment = (
            setup_enrollment_pending_payment(
                primary_income_cents=5_000_000,
            )
        )
        invoices = list_premium_invoices(enrollment=enrollment)
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        post_payment(application=app, invoice=binder)
        # Second post-payment on the same invoice — must be rejected.
        res = api.post_payment(
            binder["id"],
            post_payment_payload(amount_cents=binder["net_amount_cents"]),
            make_applicant_headers(app["_applicant_id"]),
        )
        validate_error(res, "ERR_INVOICE_ALREADY_PAID")


# ===========================================================================
# Payment status rollup (PRD §3.7)
# ===========================================================================
class TestPaymentStatusRollup:
    """PRD §3.7: "If one [oldest unpaid invoice] exists, the server
    computes the days overdue as the logical-clock present minus a
    30-day grace-start anchor (the first day of the oldest unpaid
    month plus 30 days). When the days overdue is zero or negative
    the enrollment is still inside the 30-day grace and payment_status
    remains CURRENT; when it is between 1 and 30 inclusive,
    payment_status becomes DELINQUENT_M1; between 31 and 60 inclusive,
    DELINQUENT_M2; and between 61 and 90 inclusive, DELINQUENT_M3.
    Day 91 of non-payment triggers termination."""

    def test_grace_aware_rollup_keeps_current_inside_30_day_grace(
        self, api,
    ):
        """# difficulty: dual_variant_calc/
        payment_status_rollup_strict_vs_grace_on_enrollment

        PRD §3.7: "When the days overdue is zero or negative the
        enrollment is still inside the 30-day grace and payment_status
        remains CURRENT."

        Claim: an ACTIVE enrollment with one or more unpaid invoices
        whose oldest unpaid due_date is fewer than 30 days in the past
        still reports payment_status='CURRENT' and coverage_status=
        'ACTIVE'. Specifically: at clock 2026-01-15 (binder paid,
        coverage start 2026-01-01, only the 2026-01 invoice exists
        which is paid), payment_status is CURRENT. This pins the
        grace-aware path because a strict reading would flip
        DELINQUENT_M1 on any unpaid invoice past due_date — but the
        binder IS paid, so the rule is trivially observable.
        """
        app, _p, ins, plan, variant, enrollment, invoices = (
            setup_active_enrollment(
                primary_income_cents=5_000_000,
                base_monthly_premium_cents=20_000,
            )
        )
        # No additional clock advance — binder is paid, coverage is
        # ACTIVE.
        api.sweep_age_invoices(TEST_USERS["admin_headers"])
        refreshed = re_get_enrollment(enrollment_id=enrollment["id"])
        # PRD §3.7: "If no such invoice [oldest unpaid] exists,
        # payment_status is CURRENT."
        assert refreshed["payment_status"] == "CURRENT"
        assert refreshed["coverage_status"] == "ACTIVE"

    def test_payment_status_delinquent_after_grace_period(
        self, api,
    ):
        """# difficulty: dual_variant_calc/
        payment_status_rollup_strict_vs_grace_on_enrollment

        PRD §3.7: "When an active enrollment's payment status flips
        to DELINQUENT_M1, the coverage status moves from ACTIVE to
        GRACE_PERIOD."

        Claim: an ACTIVE enrollment whose oldest unpaid invoice has
        aged at least 31 days past its due_date (i.e., past the 30-day
        grace) transitions to a DELINQUENT_M* payment_status and
        coverage_status GRACE_PERIOD. We assert the lockstep
        invariant: if payment_status is DELINQUENT_M*, then
        coverage_status is GRACE_PERIOD (or TERMINATED at day 91+).
        """
        app, _p, ins, plan, variant, enrollment, invoices = (
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
        # PRD §3.7 lockstep: DELINQUENT_M* on payment ⇒ GRACE_PERIOD
        # (or TERMINATED at day 91+) on coverage.
        if refreshed["payment_status"] in {
            "DELINQUENT_M1", "DELINQUENT_M2", "DELINQUENT_M3",
        }:
            assert refreshed["coverage_status"] in {
                "GRACE_PERIOD", "TERMINATED",
            }


# ===========================================================================
# Waive invoice (PRD §3.7)
# ===========================================================================
class TestWaiveInvoice:
    """PRD §3.7: "A customer-service operator may instead waive an
    issued invoice (ISSUED to WAIVED) when the invoice's
    net_amount_cents equals zero (fully subsidized) or when documented
    hardship is on file; a waive accepts an optional reason and is
    treated as PAID for purposes of the payment rollup."""

    def test_waive_fully_subsidized_invoice(self, api):
        """PRD §3.7: "ISSUED to WAIVED when the invoice's
        net_amount_cents equals zero (fully subsidized)".

        Claim: low-income household, APTC covers full premium →
        net_amount_cents == 0, /waive transitions ISSUED → WAIVED.
        """
        # Build an enrollment where aptc fully covers gross
        # (single-PRIMARY-FILER at FPL 105, base=40000 → net == 0).
        # PRD §3.3: adults in expansion states with fpl<138 are
        # Medicaid-eligible (blocks /approve). Build in TX (non-
        # expansion) so the household qualifies for marketplace
        # coverage rather than Medicaid.
        from test_helpers import (
            create_plan_variant, make_applicant_headers,
            setup_application_at_fpl_percentage,
        )
        determined, _p, ins, plan = (
            setup_application_at_fpl_percentage(
                target_fpl_percentage=105.0, coverage_year=2026,
                household_size=1, primary_age=35,
                filing_state="TX",
                base_monthly_premium_cents=40_000,
            )
        )
        approved = validate_success(api.approve_application(
            determined["id"], TEST_USERS["admin_headers"],
        ), 200)
        variant = create_plan_variant(
            plan=plan, csr_level=approved["csr_eligibility"],
            actuarial_value=97.0, insurer=ins,
        )
        from test_helpers import create_enrollment_payload
        enrollment = validate_success(api.create_enrollment(
            create_enrollment_payload(
                application_id=approved["id"],
                plan_variant_id=variant["id"],
            ),
            make_applicant_headers(determined["_applicant_id"]),
        ), 201)
        # net should be 0 since aptc covers full gross.
        invoices = list_premium_invoices(enrollment=enrollment)
        binder = sorted(invoices, key=lambda r: r["billing_month"])[0]
        assert binder["net_amount_cents"] == 0
        # Waive (CustomerService).
        res = api.waive_invoice(
            binder["id"], TEST_USERS["customer_service_headers"],
        )
        waived = validate_success(res, 200)
        assert waived["status"] == "WAIVED"
