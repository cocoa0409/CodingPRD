"""Benefit invoice creation, prorated amount calculation, payment,
ageing transitions (ISSUED → GRACE → FORFEITED).

Covers PRD §3.9 (benefit invoice, prorated amount), §2.10 (clock-driven
state transitions), §3.10 (forfeiture cascade to job_restoration_status).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    advance_clock_to,
    assert_benefit_invoice,
    get_leave_case,
    list_benefit_invoices,
    make_employee_headers,
    pay_invoice,
    setup_approved_case,
    setup_invoice_forfeit_cascade,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# First invoice on APPROVE — PRD §3.9
# ===========================================================================
class TestInitialInvoice:

    def test_first_invoice_issued_on_approve(self, api):
        """PRD §3.9: "The first invoice is issued automatically when
        the case transitions to `APPROVED`, sized for the calendar
        month containing `requested_start_date`"."""
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
            benefit_premium_share_cents=30_000,
        )
        invoice = ctx["invoice"]
        assert_benefit_invoice(invoice)
        assert invoice["leave_case_id"] == ctx["case"]["id"]
        assert invoice["period_month"] == "2026-01", (
            f"first invoice's period_month = month containing "
            f"requested_start_date 2026-01-15 = '2026-01'; "
            f"got {invoice['period_month']!r}"
        )
        assert invoice["invoice_status"] == "ISSUED"


# ===========================================================================
# Invoice amount — PRD §3.9 (prorated by days_on_leave / days_in_month)
# ===========================================================================
class TestInvoiceAmount:

    def test_intermittent_invoice_prorates_by_instance_count(self, api):
        """PRD §3.9: "for intermittent and reduced-schedule cases it is
        the count of `LeaveInstance` rows on this case whose
        `instance_status` is in `APPROVED` or `PROPOSED` and whose
        `instance_date` falls anywhere between the first and last
        calendar day of `period_month` inclusive ... the
        `amount_due_cents` is the employer's `benefit_premium_share_cents`
        multiplied by the days-on-leave-in-month divided by the
        days-in-month, rounded half-up to whole cents".

        For Feb 2026 (28 days), 14 instances, premium 30_000:
            amount = round_half_up(30_000 * 14 / 28) = 15_000
        """
        # Build INTERMITTENT case in Feb 2026 with 14 8-hour instances.
        instance_dates = [f"2026-02-{day:02d}" for day in range(1, 15)]
        # Use setup_approved_case with state_pfl_program=NONE and
        # premium 30_000 — but the helper's premium is fixed via
        # employer creation. Build by hand:
        from test_helpers import (
            create_employer, create_worksite, create_employee,
            submit_leave_case, submit_certification, review_certification,
            log_instance, review_leave_case,
        )
        advance_clock_to("2026-01-15T00:00:00.000Z")
        employer = create_employer(
            leave_year_basis="CALENDAR",
            state_pfl_program="NONE",
            benefit_premium_share_cents=30_000,
        )
        worksite = create_worksite(
            employer_id=employer["id"],
            employee_count_within_75_miles=80,
        )
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        case = submit_leave_case(
            employee_id=employee["id"],
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-02-01",
            expected_end_date="2026-02-28",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="ACCEPT",
        )
        for d in instance_dates:
            log_instance(
                leave_case_id=case["id"], employee_id=employee["id"],
                instance_date=d, hours_used=8,
            )
        review_leave_case(leave_case_id=case["id"], decision="APPROVE")
        invoices = list_benefit_invoices(case["id"])
        feb_invoice = next(
            (i for i in invoices if i["period_month"] == "2026-02"), None,
        )
        assert feb_invoice is not None, (
            f"Expected invoice for 2026-02; got {invoices!r}"
        )
        assert feb_invoice["amount_due_cents"] == 15_000, (
            f"PRD §3.9: round_half_up(30_000 * 14 / 28) = 15_000; "
            f"got {feb_invoice['amount_due_cents']!r}"
        )


# ===========================================================================
# Payment — PRD §3.9
# ===========================================================================
class TestInvoicePayment:

    def test_pay_issued_invoice_succeeds(self, api):
        """PRD §3.9: "An invoice may be paid by the employee or by an
        HR specialist on the employee's behalf, transitioning
        `invoice_status` from `ISSUED` to `PAID`"."""
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        result = pay_invoice(
            invoice_id=invoice["id"], employee_id=ctx["employee"]["id"],
        )
        assert result["invoice_status"] == "PAID"


# ===========================================================================
# Ageing — PRD §3.9 (30 days → GRACE, 45 days → FORFEITED)
# ===========================================================================
class TestInvoiceAgeing:

    def test_invoice_transitions_to_grace_at_30_days(self, api):
        """PRD §3.9: "when the server clock crosses thirty days from
        the invoice's `created_at` the `invoice_status` transitions
        from `ISSUED` to `GRACE`"."""
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        # Advance clock to invoice.created_at + 31 days.
        advance_clock_to(add_days(invoice["created_at"], 31))
        invoices = list_benefit_invoices(ctx["case"]["id"])
        refreshed = next(i for i in invoices if i["id"] == invoice["id"])
        assert refreshed["invoice_status"] == "GRACE", (
            f"invoice should transition to GRACE at 30+ days; got "
            f"{refreshed['invoice_status']!r}"
        )

    def test_invoice_transitions_to_forfeited_at_45_days(self, api):
        """PRD §3.9: "when the server clock crosses forty-five days
        from the invoice's `created_at` the `invoice_status`
        transitions from `GRACE` to `FORFEITED`"."""
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        # Advance past 30 days → GRACE.
        advance_clock_to(add_days(invoice["created_at"], 31))
        # Then past 45 days → FORFEITED.
        advance_clock_to(add_days(invoice["created_at"], 46))
        invoices = list_benefit_invoices(ctx["case"]["id"])
        refreshed = next(i for i in invoices if i["id"] == invoice["id"])
        assert refreshed["invoice_status"] == "FORFEITED", (
            f"invoice should transition to FORFEITED at 45+ days; got "
            f"{refreshed['invoice_status']!r}"
        )

    def test_forfeit_cascades_to_job_restoration_status_forfeited(self, api):
        """PRD §3.9: "Forfeiture cascades into the parent
        `LeaveCase.job_restoration_status`, setting it to `FORFEITED`".

        PRD §2.8 confirms: "when a `BenefitInvoice` ages past 45 days
        from its `created_at`, it forfeits, and as part of that
        transition the parent `LeaveCase.job_restoration_status`
        cascades to `FORFEITED`".
        """
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        advance_clock_to(add_days(invoice["created_at"], 31))
        advance_clock_to(add_days(invoice["created_at"], 46))
        refreshed_case = get_leave_case(ctx["case"]["id"])
        assert refreshed_case["job_restoration_status"] == "FORFEITED", (
            f"PRD §3.9: forfeiture cascades to job_restoration_status; "
            f"got {refreshed_case['job_restoration_status']!r}"
        )

    def test_pay_after_forfeit_returns_err_invoice_not_payable(self, api):
        """PRD §3.9: "payment is allowed when `invoice_status` is in
        `ISSUED` or `GRACE`, and any other status yields
        `ERR_INVOICE_NOT_PAYABLE`"."""
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        advance_clock_to(add_days(invoice["created_at"], 31))
        advance_clock_to(add_days(invoice["created_at"], 46))
        # Now invoice is FORFEITED.
        h = make_employee_headers(ctx["employee"]["id"])
        resp = api.pay_benefit_invoice(invoice["id"], None, h)
        validate_error(resp, "ERR_INVOICE_NOT_PAYABLE")
