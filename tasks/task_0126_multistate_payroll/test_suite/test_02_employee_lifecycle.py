"""Employee creation / termination, W-4 profile creation, W-4 pre-fill.

PRD §3.1.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_employee,
    assert_w4_profile,
    create_biweekly_pay_period,
    create_employee,
    create_employee_payload,
    create_pay_period,
    create_payroll_item,
    create_w4_profile,
    create_w4_profile_payload,
    finalize_remittance,
    get_employee,
    iso_date_str,
    prefill_w4_payload,
    setup_world,
    terminate_employee,
    validate_error,
    validate_success,
)


class TestCreateEmployee:
    """PRD §3.1 employee creation."""

    def test_create_employee_returns_active_with_zero_ytd(self, api, seeded_world):
        """PRD §3.1: "On creation, the employee's status is ACTIVE,
        and the three year-to-date wage counters —
        ytd_gross_wages_cents, ytd_social_security_wages_cents, and
        ytd_medicare_wages_cents — are initialized to zero."

        Claim: status=ACTIVE and all YTD counters are 0 at birth.
        """
        resp = api_client.create_employee(
            create_employee_payload(work_state="TX"),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_employee(data)
        assert data["status"] == "ACTIVE"
        assert data["ytd_gross_wages_cents"] == 0
        assert data["ytd_social_security_wages_cents"] == 0
        assert data["ytd_medicare_wages_cents"] == 0

    def test_create_employee_default_locality_is_none(self, api, seeded_world):
        """PRD §3.1: "an optional work_locality chosen from NYC, PHL,
        or NONE that selects the city-level income tax jurisdiction
        (defaulting to NONE when omitted, in which case no local tax
        is withheld)".

        Claim: omitted work_locality -> stored value is 'NONE'.
        """
        payload = create_employee_payload(work_state="TX")
        assert "work_locality" not in payload  # factory honors PRD-default
        resp = api_client.create_employee(
            payload, TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["work_locality"] == "NONE"

    @pytest.mark.parametrize("ws", ["CA", "NY", "TX", "IL", "PA"])
    def test_create_employee_each_work_state_accepted(
            self, api, seeded_world, ws):
        """PRD §3.1: "a work_state chosen from CA, NY, TX, IL, or PA
        that controls the state income tax regime applied to the
        employee's paychecks".

        Claim: each of the five PRD-named states is accepted on
        create.
        """
        resp = api_client.create_employee(
            create_employee_payload(work_state=ws),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["work_state"] == ws


class TestEmployeeNotFound:
    """PRD §5 / §2.7: existence checks return 404 with the
    resource-specific not-found error."""

    def test_get_unknown_employee_returns_not_found(self, api, seeded_world):
        """PRD §5: ERR_EMPLOYEE_NOT_FOUND on a missing employee id.
        PRD §2.7 priority 3 ("left-to-right existence of every path
        resource") makes this the first applicable failure.

        Claim: GET /employees/{unknown} -> ERR_EMPLOYEE_NOT_FOUND.
        """
        resp = api_client.get_employee(
            NON_EXISTENT_UUID, TEST_USERS["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value)


class TestTerminateEmployee:
    """PRD §3.1 termination workflow."""

    def test_terminate_sets_status_and_records_termination_date(
            self, api, seeded_world):
        """PRD §3.1: "An employee leaves the workforce via the
        terminate capability, which a PayrollManager performs and
        which advances status from ACTIVE to TERMINATED. ... On
        success, the server stamps termination_date to today (its
        logical clock)."

        Claim: terminate succeeds and produces TERMINATED status.
        """
        emp = create_employee()
        resp = api_client.terminate_employee(
            emp["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert_employee(data)
        assert data["status"] == "TERMINATED"

    def test_terminate_blocked_when_pending_paychecks(self, api, seeded_world):
        """PRD §3.1: "Termination requires that no paycheck for this
        employee is currently in DRAFT or CALCULATED; if one is, the
        request is rejected with ERR_PENDING_PAYCHECKS."

        Claim: an employee with a DRAFT paycheck cannot be
        terminated.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        # Creating a payroll item spawns the implicit DRAFT paycheck.
        create_payroll_item(pp["id"], emp["id"], regular_hours=16.0)
        resp = api_client.terminate_employee(
            emp["id"], TEST_USERS["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PENDING_PAYCHECKS.value)


class TestW4ProfileCreation:
    """PRD §3.1 W-4 profile creation."""

    def test_create_w4_returns_profile_with_prefilled_false(
            self, api, seeded_world):
        """PRD §3.1: "Newly created profiles record
        prefilled_from_prior_year as false."

        Claim: explicit POST /w4-profiles creates a profile with
        prefilled_from_prior_year=false.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        resp = api_client.create_w4_profile(
            emp["id"],
            create_w4_profile_payload(
                effective_pay_period_id=pp["id"],
                filing_status="SINGLE",
            ),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_w4_profile(data)
        assert data["prefilled_from_prior_year"] is False
        assert data["filing_status"] == "SINGLE"

    def test_create_w4_default_dependents_is_zero(self, api, seeded_world):
        """PRD §3.1: "an optional dependents_amount_cents representing
        the annual dependent credit from W-4 Step 3 (defaulting to
        0)".

        Claim: omitted dependents_amount_cents stored as 0.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        resp = api_client.create_w4_profile(
            emp["id"],
            create_w4_profile_payload(
                effective_pay_period_id=pp["id"],
                filing_status="SINGLE",
            ),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["dependents_amount_cents"] == 0
        assert data["other_income_cents"] == 0
        assert data["additional_withholding_cents"] == 0
        assert data["state_allowances"] == 0


class TestW4Prefill:
    """PRD §3.1 W-4 pre-fill capability."""

    def test_prefill_when_no_prior_year_returns_error(self, api, seeded_world):
        """PRD §3.1: "If no prior-year W-4 exists for the employee,
        the pre-fill is rejected with ERR_NO_PRIOR_YEAR_W4."

        Claim: pre-fill with no prior-year W-4 -> error.
        """
        emp = create_employee()
        pp_2025 = create_biweekly_pay_period(date(2025, 1, 6))
        resp = api_client.prefill_w4_profile(
            emp["id"],
            prefill_w4_payload(effective_pay_period_id=pp_2025["id"]),
            TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_PRIOR_YEAR_W4.value)

    def test_prefill_copies_prior_year_fields(self, api, seeded_world):
        """PRD §3.1: "the specialist supplies only the new
        effective_pay_period_id, and the system locates the
        employee's W-4 whose effective_pay_period.pay_date is the
        latest within the prior tax year, copies its filing_status,
        state_allowances, dependents_amount_cents, and
        other_income_cents onto the new profile, sets
        additional_withholding_cents to 0, and marks
        prefilled_from_prior_year true."

        Claim: pre-fill copies named fields and sets the two pinned
        flags correctly.
        """
        emp = create_employee()
        pp_2024 = create_biweekly_pay_period(date(2024, 6, 3))
        api_client.create_w4_profile(
            emp["id"],
            create_w4_profile_payload(
                effective_pay_period_id=pp_2024["id"],
                filing_status="MARRIED_JOINT",
                dependents_amount_cents=200_000,
                other_income_cents=150_000,
                additional_withholding_cents=5_000,
                state_allowances=3,
            ),
            TEST_USERS["specialist_headers"],
        )
        pp_2025 = create_biweekly_pay_period(date(2025, 1, 6))
        resp = api_client.prefill_w4_profile(
            emp["id"],
            prefill_w4_payload(effective_pay_period_id=pp_2025["id"]),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_w4_profile(data)
        assert data["filing_status"] == "MARRIED_JOINT"
        assert data["dependents_amount_cents"] == 200_000
        assert data["other_income_cents"] == 150_000
        assert data["state_allowances"] == 3
        assert data["additional_withholding_cents"] == 0
        assert data["prefilled_from_prior_year"] is True

    def test_prefill_twice_for_same_target_year_rejected(
            self, api, seeded_world):
        """PRD §3.1: "Pre-fill is one-shot per employee per target
        tax year: a second pre-fill attempt for the same employee
        that would land in the same target tax year is rejected with
        ERR_W4_PREFILL_ALREADY_DONE."

        Claim: a duplicate pre-fill in the same target tax year is
        rejected.
        """
        emp = create_employee()
        pp_2024 = create_biweekly_pay_period(date(2024, 6, 3))
        api_client.create_w4_profile(
            emp["id"],
            create_w4_profile_payload(
                effective_pay_period_id=pp_2024["id"],
                filing_status="SINGLE",
            ),
            TEST_USERS["specialist_headers"],
        )
        pp_2025_a = create_biweekly_pay_period(date(2025, 1, 6))
        first = api_client.prefill_w4_profile(
            emp["id"],
            prefill_w4_payload(effective_pay_period_id=pp_2025_a["id"]),
            TEST_USERS["specialist_headers"],
        )
        validate_success(first, expected_status=201)
        pp_2025_b = create_biweekly_pay_period(date(2025, 7, 7))
        second = api_client.prefill_w4_profile(
            emp["id"],
            prefill_w4_payload(effective_pay_period_id=pp_2025_b["id"]),
            TEST_USERS["specialist_headers"],
        )
        validate_error(
            second, ApiErrorId.ERR_W4_PREFILL_ALREADY_DONE.value,
        )
