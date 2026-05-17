"""Garnishment orders: creation validation, CCPA cap (25% / 50%),
per-order cap, priority ordering, effective_pay_date filtering,
release, satisfaction transitions.

PRD §3.5.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_paycheck,
    assert_garnishment_order,
    calculate_paycheck,
    create_garnishment_order,
    create_garnishment_order_payload,
    create_payroll_item,
    get_garnishment_order,
    get_paycheck_for_item,
    setup_draft_paycheck,
    setup_employee_with_w4,
    setup_two_garnishments_for_employee,
    setup_world,
    validate_error,
    validate_success,
)


class TestGarnishmentValidation:
    """PRD §3.5 cap range validation."""

    @pytest.mark.parametrize("bad_cap", [0, -5, 101, 200])
    def test_cap_out_of_range_rejected(self, api, seeded_world, bad_cap):
        """PRD §3.5: "cap_pct_of_disposable (a per-pay-period cap
        expressed as an integer percent of disposable income in the
        range 1 through 100 inclusive — values outside the range are
        rejected with ERR_INVALID_GARNISHMENT_CAP)".

        Claim: cap outside [1, 100] -> error.
        """
        emp, _, _ = setup_employee_with_w4()
        resp = api_client.create_garnishment_order(
            create_garnishment_order_payload(
                employee_id=emp["id"],
                cap_pct_of_disposable=bad_cap,
            ),
            TEST_USERS["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_GARNISHMENT_CAP.value)

    @pytest.mark.parametrize("good_cap", [1, 50, 100])
    def test_cap_at_boundary_accepted(self, api, seeded_world, good_cap):
        """PRD §3.5: range "1 through 100 inclusive".

        Claim: cap == 1, 50, or 100 is accepted.
        """
        emp, _, _ = setup_employee_with_w4()
        resp = api_client.create_garnishment_order(
            create_garnishment_order_payload(
                employee_id=emp["id"],
                cap_pct_of_disposable=good_cap,
            ),
            TEST_USERS["manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_garnishment_order(data)


class TestGarnishmentPriorityDerived:
    """PRD §3.5 priority_rank derivation from order_type."""

    @pytest.mark.parametrize(
        "order_type,expected_rank",
        [
            ("CHILD_SUPPORT", 1),
            ("FEDERAL_TAX_LEVY", 2),
            ("STUDENT_LOAN", 3),
            ("CREDITOR", 4),
        ],
    )
    def test_priority_rank_from_type(
            self, api, seeded_world, order_type, expected_rank):
        """PRD §3.5: "priority_rank is derived from order_type:
        CHILD_SUPPORT is rank 1, FEDERAL_TAX_LEVY is rank 2,
        STUDENT_LOAN is rank 3, and CREDITOR is rank 4."

        Claim: priority_rank matches PRD-named mapping.
        """
        emp, _, _ = setup_employee_with_w4()
        g = create_garnishment_order(
            emp["id"], order_type=order_type,
        )
        assert g["priority_rank"] == expected_rank


class TestGarnishmentRelease:
    """PRD §3.5 release transition."""

    def test_release_active_succeeds(self, api, seeded_world):
        """PRD §3.5: "A PayrollManager may also release an ACTIVE
        order via the release capability, advancing it to RELEASED".

        Claim: ACTIVE -> RELEASED on /release.
        """
        emp, _, _ = setup_employee_with_w4()
        g = create_garnishment_order(emp["id"])
        resp = api_client.release_garnishment_order(
            g["id"], TEST_USERS["manager_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "RELEASED"

    def test_release_non_active_rejected(self, api, seeded_world):
        """PRD §3.5: "a release request against an order whose
        status is not ACTIVE is rejected with
        ERR_GARNISHMENT_NOT_ACTIVE."

        Claim: second /release after RELEASED ->
        ERR_GARNISHMENT_NOT_ACTIVE.
        """
        emp, _, _ = setup_employee_with_w4()
        g = create_garnishment_order(emp["id"])
        api_client.release_garnishment_order(
            g["id"], TEST_USERS["manager_headers"],
        )
        resp = api_client.release_garnishment_order(
            g["id"], TEST_USERS["manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GARNISHMENT_NOT_ACTIVE.value)


class TestWaterfallAllocation:
    """PRD §3.5 garnishment waterfall — disposable, CCPA cap, per-
    order cap, total."""

    def test_no_active_orders_yields_zero_total(self, api, seeded_world):
        """PRD §3.5: "garnishment_total_cents is the sum of all
        per-order allocations on this paycheck". With no orders the
        sum is zero.

        Claim: no garnishments -> garnishment_total_cents == 0.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["garnishment_total_cents"] == 0

    def test_two_orders_child_support_50pct_ccpa_cap(self, api, seeded_world):
        """PRD §3.5: "The default cap is 25% of disposable income;
        however, if the employee has any ACTIVE CHILD_SUPPORT
        order, the cap rises to 50% of disposable income. The cap is
        computed as disposable multiplied by the applicable percent
        (25 or 50) divided by 100, rounded half up to whole cents."
        PRD §3.5: "for each order computes a per-order cap as the
        disposable multiplied by cap_pct_of_disposable divided by
        100, rounded half up to whole cents. ... The allocation for
        the order is then the minimum of the per-order cap, the
        remaining owed amount, and the remaining pool."

        Claim: with G1=CHILD_SUPPORT cap=20%, G2=CREDITOR cap=15%,
        gross=200000, disposable=167962 ->
            CCPA pool = round(167962 * 0.50) = 83981
            G1 = min(round(167962 * 0.20)=33592, 500000, 83981) = 33592
            G2 = min(round(167962 * 0.15)=25194, 500000, 50389) = 25194
            total = 58786
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        setup_two_garnishments_for_employee(
            emp["id"],
            g1_type="CHILD_SUPPORT", g1_cap_pct=20, g1_owed=500_000,
            g2_type="CREDITOR", g2_cap_pct=15, g2_owed=500_000,
            g1_effective="2024-01-01", g2_effective="2024-01-01",
        )
        # Now create a payroll item and calculate.
        from test_helpers import (
            create_biweekly_pay_period,
            create_w4_profile,
        )
        # Need a fresh pay period whose pay_date >= effective_pay_date
        # of both orders.
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        assert pc["gross_wages_cents"] == 200_000
        # Federal SINGLE annualized = 16738 (computed in test_05).
        assert pc["federal_withholding_cents"] == 16_738
        assert pc["state_withholding_cents"] == 0  # TX
        assert pc["local_withholding_cents"] == 0  # NONE
        assert pc["social_security_cents"] == 12_400
        assert pc["medicare_base_cents"] == 2_900
        assert pc["medicare_additional_cents"] == 0
        # disposable = 200000 - 16738 - 12400 - 2900 = 167962
        # CCPA pool = round(167962 * 0.50) = 83981
        # G1 per-order cap = round(167962 * 0.20) = 33592
        # G2 per-order cap = round(167962 * 0.15) = 25194
        # G1 = min(33592, 500000, 83981) = 33592; pool -= 33592 = 50389
        # G2 = min(25194, 500000, 50389) = 25194
        # total = 58786
        assert pc["garnishment_total_cents"] == 58_786


class TestEffectivePayDateFilter:
    """PRD §3.5 effective_pay_date filter — half-open [effective, inf)."""

    def test_order_with_future_effective_date_excluded(
            self, api, seeded_world):
        """PRD §3.5: "the order applies only to paychecks whose
        owning pay period's pay_date is on or after this date".

        Claim: a creditor garnishment with effective_pay_date AFTER
        the pay period's pay_date does NOT apply.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        # The default pay_period from setup_employee_with_w4 starts
        # 2024-06-03 -> pay_date 2024-06-21. Make a garnishment
        # effective 2024-12-01 (clearly after).
        create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=50, total_owed_cents=500_000,
            effective_pay_date="2024-12-01",
        )
        from test_helpers import (
            create_biweekly_pay_period,
            create_w4_profile,
        )
        pp2 = create_biweekly_pay_period(date(2024, 6, 3))
        # W-4 already exists for the previous pp; create one for pp2.
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        assert pc["garnishment_total_cents"] == 0, (
            f"future-effective garnishment must not apply; got "
            f"{pc['garnishment_total_cents']}"
        )

    def test_order_effective_date_equal_pay_date_applies(
            self, api, seeded_world):
        """PRD §3.5: "the order applies only to paychecks whose
        owning pay period's pay_date is on or after this date" — the
        boundary "on" means equal-date IS included.

        Claim: effective_pay_date == pay_date applies. With a single
        creditor order capped at 15% and gross=200000:
          disposable = 167962
          CCPA pool = round(167962 * 0.25) = 41991 (no child support)
          per-order cap = round(167962 * 0.15) = 25194
          allocation = min(25194, 500000, 41991) = 25194
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        from test_helpers import (
            create_biweekly_pay_period,
            create_w4_profile,
        )
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        # Period starts 2024-08-12, ends 2024-08-25, pay_date
        # 2024-08-30 (pay_offset 5 days). Effective = pay_date.
        pay_date = pp2["pay_date"]
        create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=500_000,
            effective_pay_date=pay_date,
        )
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        assert pc["garnishment_total_cents"] == 25_194


class TestSatisfactionTransition:
    """PRD §2.9 / §3.5 garnishment becomes SATISFIED on approval when
    collected >= owed."""

    def test_order_satisfied_when_owed_reached(self, api, seeded_world):
        """PRD §3.5: "On paycheck approval, the system refreshes
        each affected garnishment order's amount_collected_cents by
        adding this paycheck's per-order allocation. If
        amount_collected_cents reaches or exceeds total_owed_cents
        and the order is currently ACTIVE, the order transitions
        automatically to SATISFIED."

        Claim: with total_owed equal to the one-shot allocation, the
        order becomes SATISFIED after /approve.
        """
        emp, _, _ = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=12_500,
        )
        # Allocation will be 25,194 (above); set total_owed at
        # exactly that figure so the order satisfies on first
        # paycheck approve.
        g = create_garnishment_order(
            emp["id"], order_type="CREDITOR",
            cap_pct_of_disposable=15, total_owed_cents=25_194,
            effective_pay_date="2024-01-01",
        )
        from test_helpers import (
            create_biweekly_pay_period,
            create_w4_profile,
        )
        pp2 = create_biweekly_pay_period(date(2024, 8, 12))
        create_w4_profile(emp["id"], pp2["id"], filing_status="SINGLE")
        item = create_payroll_item(
            pp2["id"], emp["id"], regular_hours=16.0,
        )
        pc = get_paycheck_for_item(item)
        pc = calculate_paycheck(pc["id"])
        # Allocate the maximum the cap permits: 25,194 -> equals
        # total_owed.
        assert pc["garnishment_total_cents"] == 25_194
        approve_paycheck(pc["id"])
        g_after = get_garnishment_order(g["id"])
        assert g_after["status"] == "SATISFIED", (
            f"order should auto-transition to SATISFIED when "
            f"collected >= owed; got {g_after['status']}"
        )
        assert g_after["amount_collected_cents"] == 25_194
