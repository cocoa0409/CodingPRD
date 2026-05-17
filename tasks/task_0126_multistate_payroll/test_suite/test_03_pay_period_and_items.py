"""Pay period creation/dates/lock, payroll item attach/edit, duplicate
paychecks, hours validation.

PRD §3.2, §3.3.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_pay_period,
    assert_payroll_item,
    biweekly_pay_period_payload,
    create_biweekly_pay_period,
    create_employee,
    create_pay_period,
    create_pay_period_payload,
    create_payroll_item,
    create_payroll_item_payload,
    create_w4_profile,
    iso_date_str,
    setup_world,
    update_payroll_item_payload,
    validate_error,
    validate_success,
)


class TestPayPeriodDates:
    """PRD §3.2 date ordering rules."""

    def test_create_pay_period_status_open_count_zero(self, api, seeded_world):
        """PRD §3.2: "A new pay period begins in OPEN status and
        carries a paycheck_count of zero."

        Claim: status=OPEN and paycheck_count=0 on creation.
        """
        resp = api_client.create_pay_period(
            create_pay_period_payload(),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_pay_period(data)
        assert data["status"] == "OPEN"
        assert data["paycheck_count"] == 0

    def test_period_end_before_period_start_rejected(self, api, seeded_world):
        """PRD §3.2: "The system requires that period_end is greater
        than or equal to period_start, and that pay_date is greater
        than or equal to period_end; either inversion is rejected
        with ERR_INVALID_PAY_PERIOD_DATES."

        Claim: period_end < period_start -> error.
        """
        resp = api_client.create_pay_period(
            {
                "period_start": "2024-06-10",
                "period_end": "2024-06-03",
                "pay_date": "2024-06-15",
            },
            TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAY_PERIOD_DATES.value)

    def test_pay_date_before_period_end_rejected(self, api, seeded_world):
        """PRD §3.2: "pay_date is greater than or equal to period_end;
        either inversion is rejected with
        ERR_INVALID_PAY_PERIOD_DATES."

        Claim: pay_date < period_end -> error.
        """
        resp = api_client.create_pay_period(
            {
                "period_start": "2024-06-03",
                "period_end": "2024-06-16",
                "pay_date": "2024-06-10",
            },
            TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAY_PERIOD_DATES.value)

    def test_pay_date_equal_period_end_accepted(self, api, seeded_world):
        """PRD §3.2: "pay_date is greater than or equal to
        period_end". Equality is on the inclusive side.

        Claim: pay_date == period_end is accepted.
        """
        resp = api_client.create_pay_period(
            {
                "period_start": "2024-06-03",
                "period_end": "2024-06-16",
                "pay_date": "2024-06-16",
            },
            TEST_USERS["specialist_headers"],
        )
        validate_success(resp, expected_status=201)


class TestPayPeriodLock:
    """PRD §3.2 lock preconditions."""

    def test_lock_with_no_payroll_items_rejected(self, api, seeded_world):
        """PRD §3.2: "at least one PayrollItem must exist in the
        period or the lock is rejected with ERR_NO_PAYROLL_ITEMS".

        Claim: empty period rejects /lock with ERR_NO_PAYROLL_ITEMS.
        """
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        resp = api_client.lock_pay_period(
            pp["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NO_PAYROLL_ITEMS.value)

    def test_lock_with_uncalculated_item_rejected(self, api, seeded_world):
        """PRD §3.2: "every PayrollItem must already have a
        corresponding paycheck in CALCULATED or later (APPROVED,
        PAID, or VOIDED) or the lock is rejected with
        ERR_UNCALCULATED_ITEMS".

        Claim: a DRAFT paycheck blocks /lock with
        ERR_UNCALCULATED_ITEMS.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        # Payroll item creation spawns DRAFT paycheck — never
        # calculated.
        create_payroll_item(pp["id"], emp["id"], regular_hours=16.0)
        resp = api_client.lock_pay_period(
            pp["id"], TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_UNCALCULATED_ITEMS.value)


class TestPayrollItemHours:
    """PRD §3.3 hours validation."""

    @pytest.mark.parametrize(
        "regular,overtime,double",
        [
            (-1.0, 0, 0),
            (0, -2.0, 0),
            (0, 0, -5.0),
        ],
    )
    def test_negative_hours_rejected(
            self, api, seeded_world, regular, overtime, double):
        """PRD §3.3: "the three hour fields must each be
        non-negative, and the sum of regular_hours, overtime_hours,
        and double_hours must not exceed 240 hours per period;
        violation is rejected with ERR_INVALID_HOURS."

        Claim: any negative hour field -> ERR_INVALID_HOURS.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        resp = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"],
                regular_hours=regular,
                overtime_hours=overtime,
                double_hours=double,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HOURS.value)

    def test_hours_sum_above_240_rejected(self, api, seeded_world):
        """PRD §3.3: "the sum of regular_hours, overtime_hours, and
        double_hours must not exceed 240 hours per period; violation
        is rejected with ERR_INVALID_HOURS."

        Claim: sum > 240 -> error.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        resp = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"],
                regular_hours=100.0,
                overtime_hours=100.0,
                double_hours=41.0,  # 241 total
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HOURS.value)

    def test_hours_sum_exactly_240_accepted(self, api, seeded_world):
        """PRD §3.3: "the sum ... must not exceed 240 hours per
        period". Boundary case: sum == 240 must be accepted.

        Claim: 240 sum is accepted.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        resp = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"],
                regular_hours=100.0,
                overtime_hours=100.0,
                double_hours=40.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_success(resp, expected_status=201)

    def test_payroll_item_omitted_hours_default_zero(self, api, seeded_world):
        """PRD §3.3: "All four default to zero when omitted".

        Claim: an item created with no hour/retro fields stores all
        four at 0.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        resp = api_client.create_payroll_item(
            pp["id"],
            {"employee_id": emp["id"]},
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_payroll_item(data)
        assert data["regular_hours"] == 0
        assert data["overtime_hours"] == 0
        assert data["double_hours"] == 0
        assert data["retro_adjustment_cents"] == 0


class TestPayrollItemDuplicates:
    """PRD §3.3 per-employee-per-period uniqueness."""

    def test_duplicate_payroll_item_rejected(self, api, seeded_world):
        """PRD §3.3: "At most one non-correction PayrollItem may
        exist per (pay_period_id, employee_id) pair; an attempt to
        attach a second is rejected with
        ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE".

        Claim: a second payroll item for the same (period, employee)
        is rejected.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        first = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=16.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_success(first, expected_status=201)
        second = api_client.create_payroll_item(
            pp["id"],
            create_payroll_item_payload(
                employee_id=emp["id"], regular_hours=16.0,
            ),
            TEST_USERS["specialist_headers"],
        )
        validate_error(
            second, ApiErrorId.ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE.value,
        )


class TestPayrollItemUpdate:
    """PRD §3.3 payroll item edit semantics while paycheck is DRAFT."""

    def test_update_payroll_item_while_draft_succeeds(self, api, seeded_world):
        """PRD §3.3: "While the linked paycheck is in DRAFT, the
        specialist may edit the hours and the retro adjustment by
        submitting an update against the payroll item".

        Claim: PUT updates an item whose linked paycheck is DRAFT.
        """
        emp = create_employee()
        pp = create_biweekly_pay_period(date(2024, 6, 3))
        create_w4_profile(emp["id"], pp["id"])
        item = create_payroll_item(
            pp["id"], emp["id"], regular_hours=16.0,
        )
        resp = api_client.update_payroll_item(
            item["id"],
            update_payroll_item_payload(regular_hours=20.0),
            TEST_USERS["specialist_headers"],
        )
        data = validate_success(resp)
        assert_payroll_item(data)
        assert data["regular_hours"] == 20.0
        assert data["locked"] is False
