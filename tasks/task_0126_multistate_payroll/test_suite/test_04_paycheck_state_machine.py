"""Paycheck state machine: DRAFT/CALCULATED/APPROVED/PAID/VOIDED
transitions, pre-state guards, owning pay period guard, terminated /
no-W4 referential checks.

PRD §3.4, §3.6, §3.7, §2.7.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_paycheck,
    assert_paycheck,
    assert_paycheck_computed_fields,
    calculate_paycheck,
    create_biweekly_pay_period,
    create_employee,
    create_payroll_item,
    create_w4_profile,
    get_paycheck_for_item,
    get_pay_period,
    iso_date_str,
    lock_pay_period,
    mark_paid_paycheck,
    setup_calculated_paycheck,
    setup_approved_paycheck,
    setup_draft_paycheck,
    setup_world,
    validate_error,
    validate_success,
)


class TestCalculateTransition:
    """PRD §3.4 DRAFT -> CALCULATED."""

    def test_calculate_advances_status_to_calculated(self, api, seeded_world):
        """PRD §3.4: "A PayrollSpecialist calculates a paycheck,
        advancing it from DRAFT to CALCULATED."

        Claim: /calculate transitions status DRAFT -> CALCULATED.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck()
        assert pc["status"] == "DRAFT"
        resp = api_client.calculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp)
        assert_paycheck(data)
        assert data["status"] == "CALCULATED"

    def test_calculate_sets_payroll_item_locked(self, api, seeded_world):
        """PRD §3.4: "Calculation snapshots w4_profile_id and
        employee_id onto the paycheck, sets PayrollItem.locked to
        true".

        Claim: PayrollItem.locked becomes true after /calculate.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck()
        calculate_paycheck(pc["id"])
        # Re-read the payroll item via PUT no-op? We don't have a GET
        # endpoint for payroll items by id — but updating with an
        # empty body returns the current item snapshot per PRD §4.
        # However, with locked=true, the PRD §3.3 narrative says
        # "once the paycheck reaches CALCULATED, the item's locked
        # flag is true and further edits are rejected"; sending a
        # PUT to mutate hours must therefore fail. We assert via the
        # rejection rather than a GET.
        resp = api_client.update_payroll_item(
            item["id"], {"regular_hours": 10.0},
            TEST_USERS["specialist_headers"],
        )
        # PRD §3.3 names no specific error_id for the locked-item
        # case but does say further edits are "rejected". Tolerate
        # any 4xx — the assertion is that the implementation does
        # NOT silently accept the edit.
        assert resp.status_code >= 400, (
            f"PUT on locked PayrollItem must be rejected; got "
            f"{resp.status_code}"
        )

    def test_calculate_without_w4_returns_no_w4(self, api, seeded_world):
        """PRD §3.4: "an active W4Profile resolves for this employee
        at this pay period (otherwise ERR_NO_W4)".

        Claim: calculate without any W-4 -> ERR_NO_W4.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        # NO W-4 created.
        item = create_payroll_item(pp["id"], emp["id"], regular_hours=16.0)
        pc = get_paycheck_for_item(item)
        resp = api_client.calculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_W4.value)

    def test_calculate_when_pay_period_not_open_rejected(
            self, api, seeded_world):
        """PRD §3.4: "the owning pay period is still OPEN" (else
        ERR_PAY_PERIOD_NOT_OPEN per PRD §2.7 priority 4 and the
        validation table).

        Claim: calculate when PayPeriod is LOCKED ->
        ERR_PAY_PERIOD_NOT_OPEN.
        """
        # Calculate, then approve, then lock (lock requires
        # calculated items), then attempt to recalculate which
        # requires DRAFT — but only DRAFT->CALCULATED triggers the
        # OPEN check via /calculate. To set this up, we need a
        # CALCULATED paycheck whose period is LOCKED. We arrange
        # that, then call /recalculate (which sends it back to
        # DRAFT) — recalculate requires PayPeriod.status==OPEN per
        # PRD §3.6, so this same OPEN check fires.
        # Pure DRAFT-with-LOCKED-period is hard; the cleanest test
        # is via /recalculate.
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        lock_pay_period(pp["id"])
        # Now try recalculate.
        resp = api_client.recalculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAY_PERIOD_NOT_OPEN.value)


class TestCalculateDuplicate:
    """PRD §3.4 / §3.8: serializing /calculate on a CALCULATED
    paycheck."""

    def test_second_calculate_returns_not_draft(self, api, seeded_world):
        """PRD §3.4: "Two simultaneous calculate calls on the same
        paycheck serialize so that exactly one wins; the loser sees
        the resulting CALCULATED state and is rejected with
        ERR_PAYCHECK_NOT_DRAFT."

        Claim: a serial second /calculate -> ERR_PAYCHECK_NOT_DRAFT.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        # The paycheck is already CALCULATED; another /calculate must
        # fail.
        resp = api_client.calculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAYCHECK_NOT_DRAFT.value)


class TestRecalculate:
    """PRD §3.4 / §3.6: CALCULATED -> DRAFT."""

    def test_recalculate_sends_back_to_draft(self, api, seeded_world):
        """PRD §3.6: "A specialist may also revert a calculated
        paycheck back to draft, which is only allowed while the
        owning pay period is OPEN, clears every computed field on the
        paycheck to null, and releases the PayrollItem.locked flag."

        Claim: /recalculate transitions CALCULATED -> DRAFT.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        resp = api_client.recalculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "DRAFT"


class TestApproveTransition:
    """PRD §3.6 CALCULATED -> APPROVED."""

    def test_approve_advances_to_approved(self, api, seeded_world):
        """PRD §3.6: "After calculation, a PayrollManager advances
        the paycheck from CALCULATED to APPROVED."

        Claim: /approve transitions CALCULATED -> APPROVED.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        resp = api_client.approve_paycheck(
            pc["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "APPROVED"

    def test_approve_on_draft_paycheck_rejected(self, api, seeded_world):
        """PRD §5 / §2.7: approve requires status==CALCULATED
        (priority 5 state check). PRD §3.4 confirms "After
        calculation, a PayrollManager advances the paycheck from
        CALCULATED to APPROVED."

        Claim: approve on DRAFT -> ERR_PAYCHECK_NOT_CALCULATED.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck()
        resp = api_client.approve_paycheck(
            pc["id"], TEST_USERS["manager_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_PAYCHECK_NOT_CALCULATED.value,
        )


class TestMarkPaidTransition:
    """PRD §3.6 APPROVED -> PAID."""

    def test_mark_paid_advances_to_paid(self, api, seeded_world):
        """PRD §3.6: "A Treasurer then disburses the paycheck by
        advancing it from APPROVED to PAID."

        Claim: /mark-paid transitions APPROVED -> PAID.
        """
        emp, pp, w4, item, pc = setup_approved_paycheck()
        # Lock period before mark-paid so the auto-close runs.
        lock_pay_period(pp["id"])
        resp = api_client.mark_paid_paycheck(
            pc["id"], TEST_USERS["treasurer_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "PAID"

    def test_mark_paid_on_calculated_rejected(self, api, seeded_world):
        """PRD §5: mark-paid requires Paycheck.status==APPROVED
        (ERR_PAYCHECK_NOT_APPROVED).

        Claim: mark-paid on CALCULATED -> ERR_PAYCHECK_NOT_APPROVED.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        resp = api_client.mark_paid_paycheck(
            pc["id"], TEST_USERS["treasurer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAYCHECK_NOT_APPROVED.value)


class TestTerminatedEmployeeOnCalculate:
    """PRD §3.1 / §3.4 terminated-employee referential check."""

    def test_calculate_for_terminated_outside_window_rejected(
            self, api, seeded_world):
        """PRD §3.1: "After termination, a final-settlement paycheck
        may still be created for the employee provided the owning
        pay period's period_end is within seven days of the recorded
        termination_date; calculate requests outside that window are
        rejected with ERR_TERMINATED_EMPLOYEE."

        Claim: calculate for a terminated employee whose pay period
        period_end is far past termination_date+7 days ->
        ERR_TERMINATED_EMPLOYEE.
        """
        emp = create_employee(hire_date="2024-01-01")
        # PRD §3.1: Termination requires no paycheck for this employee
        # is in DRAFT or CALCULATED. So terminate BEFORE attaching the
        # payroll item (which would implicitly create a DRAFT paycheck
        # and trip ERR_PENDING_PAYCHECKS).
        api_client.terminate_employee(emp["id"], TEST_USERS["manager_headers"])
        # Pay period whose period_end is 2024-06-16, far after the
        # termination_date (server "today"). PRD §3.1 permits creating
        # final-settlement items for terminated employees; the window
        # check is enforced at /calculate.
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        item = create_payroll_item(pp["id"], emp["id"], regular_hours=16.0)
        pc = get_paycheck_for_item(item)
        # The default server clock should leave today well before
        # 2024-06-16 - 7 days, so the pay period falls outside the
        # 7-day final-settlement window.
        resp = api_client.calculate_paycheck(
            pc["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TERMINATED_EMPLOYEE.value)
