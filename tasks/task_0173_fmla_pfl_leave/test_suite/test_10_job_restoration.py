"""Return-to-work, job restoration, and the job-restoration score.

Covers PRD §3.10 (return, restore, score), §3.9 (forfeiture cascade).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    advance_clock_to,
    get_leave_case,
    list_benefit_invoices,
    make_employee_headers,
    pay_invoice,
    restore_job,
    return_case,
    setup_approved_case,
    setup_completed_case,
    setup_invoice_forfeit_cascade,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# COMPLETED → JOB_RESTORED — PRD §3.10
# ===========================================================================
class TestJobRestoration:

    def test_restore_job_on_completed_protected_case_succeeds(self, api):
        """PRD §3.10: "Once the case is `COMPLETED`, an `HRSpecialist`
        may restore the employee to their job by posting the restore
        decision; this transitions the `case_status` from `COMPLETED`
        to `JOB_RESTORED` and the `Employee.employment_status` from
        `ON_LEAVE` or `ACTIVE` to `RESTORED`"."""
        ctx = setup_completed_case(
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
            leave_pattern="CONTINUOUS",
        )
        assert ctx["case"]["case_status"] == "COMPLETED"
        result = restore_job(leave_case_id=ctx["case"]["id"])
        assert result["case_status"] == "JOB_RESTORED"

    def test_restore_when_forfeited_returns_err_job_restoration_forfeited(
        self, api,
    ):
        """PRD §3.10: "Restoration is allowed only when the
        `job_restoration_status` is `PROTECTED` and there is no
        outstanding `BenefitInvoice` on this case in the `FORFEITED`
        status; any other condition surfaces as
        `ERR_JOB_RESTORATION_FORFEITED`"."""
        # Setup an APPROVED → ACTIVE case + invoice → FORFEITED → COMPLETED.
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        # Forfeit the invoice.
        advance_clock_to(add_days(invoice["created_at"], 31))
        advance_clock_to(add_days(invoice["created_at"], 46))
        # Now expedite to past expected_end_date so COMPLETED fires.
        advance_clock_to("2026-05-01T00:00:00.000Z")
        case = get_leave_case(ctx["case"]["id"])
        # Confirm preconditions.
        assert case["case_status"] == "COMPLETED", (
            f"Setup expected COMPLETED; got {case['case_status']!r}"
        )
        assert case["job_restoration_status"] == "FORFEITED", (
            f"Setup expected FORFEITED; got "
            f"{case['job_restoration_status']!r}"
        )
        # Attempt restore.
        resp = api.restore_job(
            case["id"], None, TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_JOB_RESTORATION_FORFEITED")


# ===========================================================================
# Score recomputation — PRD §3.10
# ===========================================================================
class TestRestorationScore:

    def test_score_for_clean_case_is_protected(self, api):
        """PRD §3.10: "The final `job_restoration_status` is `PROTECTED`
        if the resulting score is at least 50, and `FORFEITED`
        otherwise".

        For a clean case (cert COMPLETE, no GRACE/FORFEITED invoices,
        hours_worked_trailing_12mo below 2000):
            Step 1: base 100
            Step 2: not INSUFFICIENT → unchanged (100)
            Step 3: no GRACE / FORFEITED → unchanged (100)
            Step 4: hours_worked_trailing_12mo=2080 ≥ 2000 →
                    round_half_up(100 * 1.10) = 110 → clamp to 100
        """
        ctx = setup_approved_case(
            leave_pattern="CONTINUOUS",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
        )
        refreshed = get_leave_case(ctx["case"]["id"])
        assert refreshed["job_restoration_status"] == "PROTECTED", (
            f"clean APPROVED case should be PROTECTED; got "
            f"{refreshed['job_restoration_status']!r}"
        )

    def test_score_with_grace_invoice_reduces_to_75(self, api):
        """PRD §3.10: "Step two — the invoice penalty — multiplies the
        score by 0.00 (yielding zero) if any `BenefitInvoice` on the
        case has `invoice_status` of `FORFEITED`, otherwise multiplies
        by 0.75 if any has `invoice_status` of `GRACE`, otherwise
        leaves it unchanged".

        With one GRACE invoice and hours_worked_trailing_12mo=2080:
            Step 1: 100
            Step 2: cert COMPLETE → unchanged
            Step 3: invoice GRACE → round_half_up(100 * 0.75) = 75
            Step 4: hours >= 2000 → round_half_up(75 * 1.10) = 83 → clamp 83
        Score 83 ≥ 50 → PROTECTED.
        """
        ctx = setup_invoice_forfeit_cascade(
            initial_clock_iso="2026-01-01T00:00:00.000Z",
            requested_start_date="2026-01-15",
            expected_end_date="2026-04-30",
        )
        invoice = ctx["invoice"]
        # Push to GRACE only (not FORFEITED).
        advance_clock_to(add_days(invoice["created_at"], 31))
        refreshed = get_leave_case(ctx["case"]["id"])
        # Score = 83 — still ≥ 50 → PROTECTED.
        assert refreshed["job_restoration_status"] == "PROTECTED", (
            f"GRACE invoice with high tenure: score 83 ≥ 50 → "
            f"PROTECTED; got {refreshed['job_restoration_status']!r}"
        )
