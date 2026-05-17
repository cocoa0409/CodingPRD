"""Correction loop: issue-correction void/reversal cascade, YTD
ledger conservation, garnishment recompute, pay-period CLOSED
cascade.

PRD §2.9, §2.11, §3.4 (ytd reconciliation), §3.7.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_paycheck,
    calculate_paycheck,
    create_biweekly_pay_period,
    create_garnishment_order,
    create_w4_profile,
    find_correction_paycheck,
    get_employee,
    get_garnishment_order,
    get_pay_period,
    get_paycheck,
    issue_correction,
    lock_pay_period,
    mark_paid_paycheck,
    setup_approved_paycheck,
    setup_calculated_paycheck,
    setup_employee_with_w4,
    setup_paid_paycheck,
    setup_world,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import create_payroll_item, get_paycheck_for_item


class TestApprovalYTDAccrual:
    """PRD §2.11, §3.6 — APPROVE writes ACCRUAL ledger entry, updates
    YTD."""

    def test_approve_updates_employee_ytd(self, api, seeded_world):
        """PRD §2.11: "The denormalized fields ytd_gross_wages_cents,
        ytd_social_security_wages_cents, and ytd_medicare_wages_cents
        on Employee are derived: they always equal the sum of ledger
        entries for the employee in the current tax_year, and the
        server re-derives them whenever a paycheck is approved or
        voided."

        Claim: after /approve, Employee.ytd_gross_wages_cents equals
        paycheck.gross.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        assert pc["gross_wages_cents"] == 200_000
        approve_paycheck(pc["id"])
        emp_after = get_employee(emp["id"])
        assert emp_after["ytd_gross_wages_cents"] == 200_000, (
            f"expected ytd_gross == 200000 after approve, got "
            f"{emp_after['ytd_gross_wages_cents']}"
        )


class TestIssueCorrectionGuards:
    """PRD §3.7 issue-correction state guards."""

    def test_issue_correction_on_draft_rejected(self, api, seeded_world):
        """PRD §3.7: "The source paycheck must be in APPROVED or
        PAID; if it is in any other state, the request is rejected
        with ERR_PAYCHECK_NOT_CORRECTABLE."

        Claim: issue-correction on DRAFT paycheck ->
        ERR_PAYCHECK_NOT_CORRECTABLE.
        """
        from test_helpers import setup_draft_paycheck
        emp, pp, w4, item, pc = setup_draft_paycheck()
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        resp = api_client.issue_correction_paycheck(
            pc["id"],
            {"target_pay_period_id": target_pp["id"]},
            TEST_USERS["specialist_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_PAYCHECK_NOT_CORRECTABLE.value,
        )

    def test_issue_correction_on_calculated_rejected(self, api, seeded_world):
        """PRD §3.7: "The source paycheck must be in APPROVED or
        PAID; if it is in any other state, the request is rejected
        with ERR_PAYCHECK_NOT_CORRECTABLE."

        Claim: issue-correction on CALCULATED ->
        ERR_PAYCHECK_NOT_CORRECTABLE.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        resp = api_client.issue_correction_paycheck(
            pc["id"],
            {"target_pay_period_id": target_pp["id"]},
            TEST_USERS["specialist_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_PAYCHECK_NOT_CORRECTABLE.value,
        )


class TestIssueCorrectionSideEffects:
    """PRD §3.7 issue-correction cascading effects."""

    def test_correction_voids_source_and_reverses_ytd(self, api, seeded_world):
        """PRD §3.7: "The side effects of the correction are: the
        source paycheck's status advances to VOIDED, a YTDLedgerEntry
        of kind REVERSAL is appended whose deltas are the negation of
        the source paycheck's, the employee's three year-to-date
        counters are recomputed from the ledger".

        Claim: source paycheck transitions to VOIDED and
        Employee.ytd_gross drops by source.gross.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        assert pc["status"] == "APPROVED"
        emp_pre = get_employee(emp["id"])
        assert emp_pre["ytd_gross_wages_cents"] == 200_000
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        issue_correction(pc["id"], target_pp["id"])
        # Re-read source.
        source_after = get_paycheck(pc["id"])
        assert source_after["status"] == "VOIDED"
        emp_after = get_employee(emp["id"])
        assert emp_after["ytd_gross_wages_cents"] == 0, (
            f"YTD must drop by the voided paycheck's gross; got "
            f"{emp_after['ytd_gross_wages_cents']}"
        )

    def test_correction_creates_new_draft_in_target_period(
            self, api, seeded_world):
        """PRD §3.7: "a new Paycheck is created in DRAFT cloned from
        the source's payroll_item_id with is_retro_correction set to
        true and correction_of_paycheck_id pointing at the source.
        The new draft attaches to the supplied target_pay_period_id".

        Claim: a new DRAFT paycheck appears in the target pay period
        carrying is_retro_correction=true.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        target_pp = create_biweekly_pay_period(date(2024, 7, 1))
        issue_correction(pc["id"], target_pp["id"])
        correction = find_correction_paycheck(
            source_paycheck_id=pc["id"],
            target_pay_period_id=target_pp["id"],
        )
        assert correction["status"] == "DRAFT"
        assert correction["is_retro_correction"] is True

    def test_correction_refunds_garnishment_collected(self, api, seeded_world):
        """PRD §3.7: "each affected garnishment order has the
        source's per-order allocations subtracted from its
        amount_collected_cents (with any order whose collected total
        drops below total_owed_cents transitioning back from
        SATISFIED to ACTIVE)".

        Claim: after issue-correction, the garnishment that had been
        SATISFIED reverts to ACTIVE and amount_collected_cents
        drops back to 0.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        # Set total_owed to exactly the allocation so the order
        # satisfies on first approve, then unsatisfies on correction.
        g = create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=25_194,
            effective_pay_date="2024-01-01",
        )
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        approve_paycheck(pc["id"])
        g_mid = get_garnishment_order(g["id"])
        assert g_mid["status"] == "SATISFIED"
        assert g_mid["amount_collected_cents"] == 25_194
        # Issue correction.
        target_pp = create_biweekly_pay_period(date(2024, 9, 9))
        issue_correction(pc["id"], target_pp["id"])
        g_after = get_garnishment_order(g["id"])
        assert g_after["amount_collected_cents"] == 0, (
            f"order amount_collected must revert; got "
            f"{g_after['amount_collected_cents']}"
        )
        assert g_after["status"] == "ACTIVE", (
            f"order should revert to ACTIVE; got {g_after['status']}"
        )


class TestPayPeriodAutoClose:
    """PRD §2.9 / §3.6 — paid-paycheck triggers LOCKED -> CLOSED."""

    def test_paid_paycheck_in_locked_period_auto_closes_period(
            self, api, seeded_world):
        """PRD §3.6: "The disbursement also triggers the period-
        close check: if every paycheck in the owning pay period is
        now in PAID or VOIDED and the period is in LOCKED, the
        system transitions the period to CLOSED."

        Claim: single-paycheck period auto-closes when the paycheck
        is paid (period was LOCKED).
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        lock_pay_period(pp["id"])
        pp_mid = get_pay_period(pp["id"])
        assert pp_mid["status"] == "LOCKED"
        mark_paid_paycheck(pc["id"])
        pp_after = get_pay_period(pp["id"])
        assert pp_after["status"] == "CLOSED", (
            f"period must auto-CLOSE after the last paycheck PAID; "
            f"got {pp_after['status']}"
        )
