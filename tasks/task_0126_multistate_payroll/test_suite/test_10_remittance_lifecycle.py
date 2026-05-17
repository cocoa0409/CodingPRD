"""Remittance period: create, finalize preconditions, monthly
aggregation (employer match on SS/Medicare, no match on Additional
Medicare), state_breakdown, remit / reopen / amend cycle.

PRD §3.10.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_remittance_period,
    assert_remittance_state_breakdown_sums_to_total,
    create_remittance_period,
    create_remittance_payload,
    finalize_remittance,
    remit_remittance,
    setup_full_paid_cycle_for_month,
    setup_world,
    validate_error,
    validate_success,
)


class TestRemittanceCreate:
    """PRD §3.10 creation."""

    def test_create_remittance_initial_state(self, api, seeded_world):
        """PRD §3.10: "On creation, the remittance is in DRAFT with
        every total_*_cents field at zero and an empty
        state_breakdown."

        Claim: a freshly created RemittancePeriod has status=DRAFT,
        zero totals, empty state_breakdown.
        """
        resp = api_client.create_remittance_period(
            create_remittance_payload(tax_year=2024, tax_month=6),
            TEST_USERS["manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_remittance_period(data)
        assert data["status"] == "DRAFT"
        assert data["tax_year"] == 2024
        assert data["tax_month"] == 6
        assert data["total_federal_withholding_cents"] == 0
        assert data["total_state_withholding_cents"] == 0
        assert data["total_local_withholding_cents"] == 0
        assert data["total_social_security_cents"] == 0
        assert data["total_medicare_cents"] == 0
        assert data["total_medicare_additional_cents"] == 0
        assert data["state_breakdown"] == []

    def test_duplicate_year_month_rejected(self, api, seeded_world):
        """PRD §3.10: "The (tax_year, tax_month) pair is unique
        across remittances."

        Claim: second remittance with the same (year, month) ->
        ERR_DUPLICATE_REMITTANCE.
        """
        first = api_client.create_remittance_period(
            create_remittance_payload(tax_year=2024, tax_month=6),
            TEST_USERS["manager_headers"],
        )
        validate_success(first, expected_status=201)
        second = api_client.create_remittance_period(
            create_remittance_payload(tax_year=2024, tax_month=6),
            TEST_USERS["manager_headers"],
        )
        validate_error(second, ApiErrorId.ERR_DUPLICATE_REMITTANCE.value)


class TestFinalizePreconditions:
    """PRD §3.10 finalize preconditions."""

    def test_finalize_with_unapproved_paycheck_rejected(
            self, api, seeded_world):
        """PRD §3.10: "every Paycheck whose owning pay period's
        pay_date is in this (tax_year, tax_month) must be in
        APPROVED, PAID, or VOIDED; if any is still in DRAFT or
        CALCULATED, the request is rejected with
        ERR_UNAPPROVED_PAYCHECKS_IN_MONTH."

        Claim: a DRAFT paycheck in the month blocks /finalize even
        when every PayPeriod in the month is CLOSED.

        Reachability: PRD §3.2 forces a CLOSED period to have all
        paychecks PAID/VOIDED, so the only way to land a DRAFT/
        CALCULATED paycheck inside a CLOSED period is via §3.7
        issue-correction, which creates a new DRAFT paycheck on the
        target period (which is permitted to be a CLOSED period —
        PRD §3.7 explicitly states "a previously CLOSED source
        period remains CLOSED"). We use that path to construct the
        precondition for the second finalize check.
        """
        from test_helpers import issue_correction
        # Run the full lifecycle in June 2024 so the period auto-closes
        # to CLOSED after mark-paid.
        emp, pp, pc = setup_full_paid_cycle_for_month(
            work_state="TX", hourly_rate_cents=12_500,
            period_start=date(2024, 6, 3), regular_hours=16.0,
        )
        assert pp["status"] == "CLOSED"
        # Issue a correction targeting the same CLOSED period — PRD §3.7
        # leaves the period CLOSED while creating a new DRAFT correction
        # paycheck whose owning period is in the same (2024, 6) month.
        issue_correction(pc["id"], pp["id"])
        # Now every PayPeriod in (2024, 6) is CLOSED (first check
        # passes) but a DRAFT correction paycheck exists in it (second
        # check trips ERR_UNAPPROVED_PAYCHECKS_IN_MONTH).
        remit = create_remittance_period(tax_year=2024, tax_month=6)
        resp = api_client.finalize_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_UNAPPROVED_PAYCHECKS_IN_MONTH.value,
        )


class TestRemittanceAggregation:
    """PRD §3.10 monthly aggregation."""

    def test_finalize_one_paid_paycheck_employer_match(
            self, api, seeded_world):
        """PRD §3.10: "total_social_security_cents = sum of each
        paycheck's social_security_cents, then multiplied by two —
        because the employer matches Social Security one-for-one.
        total_medicare_cents = sum of each paycheck's
        medicare_base_cents, then multiplied by two — because the
        employer matches base Medicare one-for-one.
        total_medicare_additional_cents = sum of each paycheck's
        medicare_additional_cents — the employer does not match
        Additional Medicare".

        Claim: with one paycheck (gross 200000, SS 12400, Medicare
        2900, Additional 0):
            total_social_security_cents == 24800 (= 12400 * 2)
            total_medicare_cents == 5800 (= 2900 * 2)
            total_medicare_additional_cents == 0 (no match)
            total_federal_withholding_cents == 16738
        """
        emp, pp, pc = setup_full_paid_cycle_for_month(
            work_state="TX", hourly_rate_cents=12_500,
            period_start=date(2024, 6, 3), regular_hours=16.0,
        )
        # Sanity-check the paycheck shape that was paid.
        assert pc["status"] == "PAID"
        assert pc["federal_withholding_cents"] == 16_738
        assert pc["social_security_cents"] == 12_400
        assert pc["medicare_base_cents"] == 2_900
        assert pc["medicare_additional_cents"] == 0
        remit = create_remittance_period(tax_year=2024, tax_month=6)
        resp = api_client.finalize_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert_remittance_period(data)
        assert data["status"] == "FINALIZED"
        assert data["total_federal_withholding_cents"] == 16_738
        assert data["total_social_security_cents"] == 24_800
        assert data["total_medicare_cents"] == 5_800
        assert data["total_medicare_additional_cents"] == 0

    def test_state_breakdown_groups_by_work_state(self, api, seeded_world):
        """PRD §3.10: "state_breakdown is an array of records
        { state, amount_cents }, formed by grouping the source
        paychecks by the employee's work_state and summing each
        group's state_withholding_cents. The grand
        total_state_withholding_cents equals the sum of these
        breakdown amounts."

        Claim: state_breakdown sums to total_state_withholding_cents.
        """
        emp, pp, pc = setup_full_paid_cycle_for_month(
            work_state="TX", hourly_rate_cents=12_500,
            period_start=date(2024, 6, 3), regular_hours=16.0,
        )
        remit = create_remittance_period(tax_year=2024, tax_month=6)
        resp = api_client.finalize_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert_remittance_state_breakdown_sums_to_total(data)
        # TX produces zero state withholding so total is 0 and
        # breakdown either is [] or [{state: TX, amount_cents: 0}].
        assert data["total_state_withholding_cents"] == 0


class TestRemitCycle:
    """PRD §3.10 FINALIZED -> REMITTED -> AMENDED -> REMITTED."""

    def test_remit_finalized_succeeds(self, api, seeded_world):
        """PRD §3.10: "A Treasurer transmits a FINALIZED remittance,
        advancing it to REMITTED."

        Claim: /remit transitions FINALIZED -> REMITTED.
        """
        emp, pp, pc = setup_full_paid_cycle_for_month()
        pd = pp["pay_date"]
        year, month = int(pd[:4]), int(pd[5:7])
        remit = create_remittance_period(tax_year=year, tax_month=month)
        remit = finalize_remittance(remit["id"])
        resp = api_client.remit_remittance(
            remit["id"], TEST_USERS["treasurer_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "REMITTED"

    def test_remit_on_draft_rejected(self, api, seeded_world):
        """PRD §5: ERR_REMITTANCE_NOT_FINALIZED — "remit/reopen
        requires RemittancePeriod.status==FINALIZED".

        Claim: /remit on DRAFT -> ERR_REMITTANCE_NOT_FINALIZED.
        """
        remit = create_remittance_period(tax_year=2024, tax_month=6)
        resp = api_client.remit_remittance(
            remit["id"], TEST_USERS["treasurer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_REMITTANCE_NOT_FINALIZED.value,
        )

    def test_reopen_after_remit_blocked(self, api, seeded_world):
        """PRD §3.10: "A PayrollManager may reopen a FINALIZED
        remittance back to DRAFT, but only if the remittance has
        never been transmitted — i.e., its status was never
        REMITTED."

        Claim: /reopen on REMITTED is rejected (state pre-check at
        priority 6 against FINALIZED).
        """
        emp, pp, pc = setup_full_paid_cycle_for_month()
        pd = pp["pay_date"]
        year, month = int(pd[:4]), int(pd[5:7])
        remit = create_remittance_period(tax_year=year, tax_month=month)
        finalize_remittance(remit["id"])
        remit_remittance(remit["id"])
        resp = api_client.reopen_remittance(
            remit["id"], TEST_USERS["manager_headers"],
        )
        # PRD §5 names ERR_REMITTANCE_NOT_FINALIZED for the
        # reopen pre-state guard.
        validate_error(
            resp, ApiErrorId.ERR_REMITTANCE_NOT_FINALIZED.value,
        )


class TestAmendCycle:
    """PRD §3.10 amendment loop."""

    def test_amend_with_no_basis_rejected(self, api, seeded_world):
        """PRD §3.10: "The precondition is that at least one paycheck
        in this month is now VOIDED with a corresponding correction
        paycheck in APPROVED; otherwise the request is rejected with
        ERR_NO_AMENDMENT_BASIS."

        Claim: /amend on REMITTED without any voided+corrected
        paycheck -> ERR_NO_AMENDMENT_BASIS.
        """
        emp, pp, pc = setup_full_paid_cycle_for_month()
        pd = pp["pay_date"]
        year, month = int(pd[:4]), int(pd[5:7])
        remit = create_remittance_period(tax_year=year, tax_month=month)
        finalize_remittance(remit["id"])
        remit_remittance(remit["id"])
        resp = api_client.amend_remittance(
            remit["id"], TEST_USERS["manager_headers_alt"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_AMENDMENT_BASIS.value)
