"""Concurrency races and OCC version mismatch.

PRD §2.5, §3.1 (W-4 prefill race), §3.3, §3.4, §3.8, §3.10.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    calculate_paycheck,
    create_employee,
    create_biweekly_pay_period,
    create_payroll_item_payload,
    create_remittance_payload,
    create_w4_profile,
    create_w4_profile_payload,
    prefill_w4_payload,
    run_race,
    setup_calculated_paycheck,
    setup_draft_paycheck,
    setup_employee_with_w4,
    setup_world,
    validate_error,
    validate_success,
)


class TestOCCVersionConflict:
    """PRD §2.5 optimistic concurrency control."""

    def test_terminate_with_stale_version_rejected(self, api, seeded_world):
        """PRD §2.5: "When version is supplied, the server compares
        it to the resource's current version and, on mismatch,
        rejects the request with ERR_STALE_DATA."

        Claim: termination with a bogus low version ->
        ERR_STALE_DATA.
        """
        emp = create_employee()
        # Send a version far below the current (which is 1 after
        # creation) — 0 is guaranteed stale.
        resp = api_client.terminate_employee(
            emp["id"], TEST_USERS["manager_headers"],
            {"version": 0},
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DATA.value)

    def test_terminate_without_version_skips_occ_check(
            self, api, seeded_world):
        """PRD §2.5: "When version is omitted from the body, no OCC
        check is performed and the mutation proceeds."

        Claim: terminate without a version field succeeds.
        """
        emp = create_employee()
        resp = api_client.terminate_employee(
            emp["id"], TEST_USERS["manager_headers"], {},
        )
        validate_success(resp)


class TestCalculateRace:
    """PRD §3.4: two simultaneous calculate calls."""

    def test_two_calculate_calls_serialize(self, api, seeded_world):
        """PRD §3.4: "Two simultaneous calculate calls on the same
        paycheck serialize so that exactly one wins; the loser is
        rejected with ERR_PAYCHECK_NOT_DRAFT."

        Claim: under concurrent /calculate, exactly one 2xx and one
        4xx outcome; the failure carries the named error_id.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck()
        results = run_race(
            lambda: api_client.calculate_paycheck(
                pc["id"], TEST_USERS["specialist_headers"],
            ),
            lambda: api_client.calculate_paycheck(
                pc["id"], TEST_USERS["specialist_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_PAYCHECK_NOT_DRAFT.value)


class TestApproveAndRecalculateRace:
    """PRD §3.4 / §3.8: approve vs recalculate race."""

    def test_approve_vs_recalculate_serialize(self, api, seeded_world):
        """PRD §3.8: "Two simultaneous approve calls (or an approve
        and a recalculate) on the same CALCULATED paycheck serialize
        so that exactly one wins; the loser is rejected with
        ERR_PAYCHECK_NOT_CALCULATED."

        Claim: exactly one of {approve, recalculate} wins; the loser
        carries ERR_PAYCHECK_NOT_CALCULATED.
        """
        emp, pp, w4, item, pc = setup_calculated_paycheck()
        results = run_race(
            lambda: api_client.approve_paycheck(
                pc["id"], TEST_USERS["manager_headers"],
            ),
            lambda: api_client.recalculate_paycheck(
                pc["id"], TEST_USERS["specialist_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_PAYCHECK_NOT_CALCULATED.value,
        )


class TestDuplicatePayrollItemRace:
    """PRD §3.3 / §3.8: two payroll-item attaches for same employee."""

    def test_two_payroll_items_for_same_employee_serialize(
            self, api, seeded_world):
        """PRD §3.8: "Two simultaneous attempts to create a payroll
        item for the same (pay_period_id, employee_id) serialize so
        that at most one non-correction paycheck per pair exists;
        the loser is rejected with
        ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE."

        Claim: under concurrent attaches for the same (pp, emp), one
        succeeds and one fails with the named error.
        """
        emp, pp, w4 = setup_employee_with_w4()
        results = run_race(
            lambda: api_client.create_payroll_item(
                pp["id"], create_payroll_item_payload(
                    employee_id=emp["id"], regular_hours=16.0,
                ),
                TEST_USERS["specialist_headers"],
            ),
            lambda: api_client.create_payroll_item(
                pp["id"], create_payroll_item_payload(
                    employee_id=emp["id"], regular_hours=8.0,
                ),
                TEST_USERS["specialist_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(
            loser,
            ApiErrorId.ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE.value,
        )


class TestDuplicateRemittanceRace:
    """PRD §3.8: two remittance creations for the same (year, month)."""

    def test_two_remittances_same_year_month_serialize(
            self, api, seeded_world):
        """PRD §3.8: "Two simultaneous attempts to create a
        remittance for the same (tax_year, tax_month) serialize so
        that at most one exists; the loser is rejected with
        ERR_DUPLICATE_REMITTANCE."

        Claim: concurrent (2024, 6) creations -> exactly one
        succeeds and the loser carries
        ERR_DUPLICATE_REMITTANCE.
        """
        results = run_race(
            lambda: api_client.create_remittance_period(
                create_remittance_payload(tax_year=2024, tax_month=6),
                TEST_USERS["manager_headers"],
            ),
            lambda: api_client.create_remittance_period(
                create_remittance_payload(tax_year=2024, tax_month=6),
                TEST_USERS["manager_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_DUPLICATE_REMITTANCE.value,
        )


class TestPrefillRace:
    """PRD §3.1 / §3.8: two W-4 pre-fills for same employee+tax-year."""

    def test_two_prefills_same_target_year_serialize(
            self, api, seeded_world):
        """PRD §3.8: "Two simultaneous pre-fill attempts for the
        same employee targeting the same effective tax year
        serialize so that at most one prefilled profile is created;
        the loser is rejected with ERR_W4_PREFILL_ALREADY_DONE."

        Claim: concurrent prefill for same employee with two 2025
        target periods -> exactly one 2xx + one 4xx with the named
        error.
        """
        emp = create_employee()
        pp_2024 = create_biweekly_pay_period(date(2024, 6, 3))
        # Seed a prior-year W-4 the prefill can copy.
        api_client.create_w4_profile(
            emp["id"],
            create_w4_profile_payload(
                effective_pay_period_id=pp_2024["id"],
                filing_status="SINGLE",
            ),
            TEST_USERS["specialist_headers"],
        )
        pp_a = create_biweekly_pay_period(date(2025, 1, 6))
        pp_b = create_biweekly_pay_period(date(2025, 7, 7))
        results = run_race(
            lambda: api_client.prefill_w4_profile(
                emp["id"],
                prefill_w4_payload(effective_pay_period_id=pp_a["id"]),
                TEST_USERS["specialist_headers"],
            ),
            lambda: api_client.prefill_w4_profile(
                emp["id"],
                prefill_w4_payload(effective_pay_period_id=pp_b["id"]),
                TEST_USERS["specialist_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_W4_PREFILL_ALREADY_DONE.value,
        )
