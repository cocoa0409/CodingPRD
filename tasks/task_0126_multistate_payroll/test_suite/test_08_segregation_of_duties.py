"""Segregation of duties: calculator != approver, approver !=
treasurer != calculator, finalizer != remitter (and amender on
post-amend remit).

PRD §2.6.
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
    create_remittance_period,
    finalize_remittance,
    lock_pay_period,
    make_manager_headers,
    make_specialist_headers,
    make_treasurer_headers,
    mark_paid_paycheck,
    setup_calculated_paycheck,
    setup_approved_paycheck,
    setup_full_paid_cycle_for_month,
    setup_paid_paycheck,
    setup_world,
    validate_error,
    validate_success,
)


class TestSODApproveVsCalculate:
    """PRD §2.6: approver's X-User-ID must differ from the
    calculator's."""

    def test_same_user_calculate_and_approve_rejected(
            self, api, seeded_world):
        """PRD §2.6: "On a paycheck moving from CALCULATED to
        APPROVED, the approver's X-User-ID must differ from the
        X-User-ID recorded as the most recent calculator of that
        paycheck. A match is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: same X-User-ID on calculate and approve ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        from test_helpers import setup_draft_paycheck
        emp, pp, w4, item, pc = setup_draft_paycheck()
        # Calculate as user_X (any role permitted to calculate).
        same_id = "shared-user-1"
        spec_x = make_specialist_headers(same_id)
        api_client.calculate_paycheck(pc["id"], spec_x)
        # Approve as the SAME X-User-ID but acting as PayrollManager.
        mgr_x = make_manager_headers(same_id)
        resp = api_client.approve_paycheck(pc["id"], mgr_x)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_distinct_users_calculate_and_approve_succeeds(
            self, api, seeded_world):
        """PRD §2.6: "the approver's X-User-ID must differ from the
        X-User-ID recorded as the most recent calculator". Distinct
        ids satisfy the check.

        Claim: distinct X-User-IDs on calculate and approve succeed.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        resp = api_client.approve_paycheck(
            pc["id"], TEST_USERS["manager_headers"],
        )
        validate_success(resp)


class TestSODMarkPaidVsApproverAndCalculator:
    """PRD §2.6: Treasurer's X-User-ID must differ from BOTH the
    approver and the most recent calculator."""

    def test_treasurer_equal_to_approver_rejected(self, api, seeded_world):
        """PRD §2.6: "On a paycheck moving from APPROVED to PAID,
        the Treasurer's X-User-ID must differ from both the approver
        and the most recent calculator of that paycheck. A match
        against either is rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: treasurer X-User-ID equals approver's ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        from test_helpers import setup_draft_paycheck
        emp, pp, w4, item, pc = setup_draft_paycheck()
        # Calculate as specialist-A, approve as manager-B, mark-paid
        # as treasurer with X-User-ID==B (collision with approver).
        spec_a = make_specialist_headers("user-A-calc")
        mgr_b = make_manager_headers("user-B-approve")
        tre_b = make_treasurer_headers("user-B-approve")
        api_client.calculate_paycheck(pc["id"], spec_a)
        api_client.approve_paycheck(pc["id"], mgr_b)
        # Lock period before mark-paid.
        api_client.lock_pay_period(pp["id"], TEST_USERS["specialist_headers"])
        resp = api_client.mark_paid_paycheck(pc["id"], tre_b)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_treasurer_equal_to_calculator_rejected(self, api, seeded_world):
        """PRD §2.6: "the Treasurer's X-User-ID must differ from both
        the approver and the most recent calculator of that paycheck.
        A match against either is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: treasurer X-User-ID equals calculator's ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        from test_helpers import setup_draft_paycheck
        emp, pp, w4, item, pc = setup_draft_paycheck()
        spec_a = make_specialist_headers("user-A-calc")
        mgr_b = make_manager_headers("user-B-approve")
        tre_a = make_treasurer_headers("user-A-calc")  # equals calc
        api_client.calculate_paycheck(pc["id"], spec_a)
        api_client.approve_paycheck(pc["id"], mgr_b)
        api_client.lock_pay_period(pp["id"], TEST_USERS["specialist_headers"])
        resp = api_client.mark_paid_paycheck(pc["id"], tre_a)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestSODRemitVsFinalizer:
    """PRD §2.6: Treasurer remitting must differ from finalizer."""

    def test_remit_by_finalizer_rejected(self, api, seeded_world):
        """PRD §2.6: "On a remittance moving from FINALIZED (or
        AMENDED) to REMITTED, the Treasurer's X-User-ID must differ
        from the finalizer's".

        Claim: remit X-User-ID equals finalizer's ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        # Walk through a one-paycheck pay-period cycle so the
        # monthly remittance has something (or nothing) to
        # aggregate. We use a paid cycle so finalize will not
        # reject with ERR_UNAPPROVED_PAYCHECKS_IN_MONTH.
        emp, pp, pc = setup_full_paid_cycle_for_month()
        # Determine month from pp.pay_date.
        pd = pp["pay_date"]
        year = int(pd[:4])
        month = int(pd[5:7])
        # Use the SAME X-User-ID for finalize and remit. Both must
        # be PayrollManager and Treasurer respectively per PRD §4,
        # but the X-User-ID may be reused (collision is the test).
        shared = "shared-id-fin-remit"
        mgr_h = make_manager_headers(shared)
        tre_h = make_treasurer_headers(shared)
        remit = create_remittance_period(
            tax_year=year, tax_month=month, headers=mgr_h,
        )
        finalize_remittance(remit["id"], headers=mgr_h)
        resp = api_client.remit_remittance(remit["id"], tre_h)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
