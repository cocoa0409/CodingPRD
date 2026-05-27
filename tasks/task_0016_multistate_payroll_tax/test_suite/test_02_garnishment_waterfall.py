"""Garnishment waterfall — priority_rank → served_on → created_at tie-break;
per-order rounding; CCPA intake checks; aggregate capacity check.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    seed_federal_and_california_2025,
    setup_employee_with_filed_w4,
    create_employee,
    create_and_file_w4,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    approve_run,
    pay_run,
    create_garnishment_order,
    setup_paid_regular_run,
    TEST_USERS,
    create_garnishment_order_payload,
)


# =========================================================================
# Queue (A) Difficulty — rule 2 combinatorial_formula (mode c)
# =========================================================================

class TestGarnishmentWaterfallEvaluationOrder:
    """Fixed evaluation order + served_on tie-break per PRD §3.5."""

    def test_two_child_support_orders_split_by_served_on_then_caps(self, api):
        """PRD §3.5: "the candidate orders are all `ACTIVE` garnishments for
        this employee sorted by `priority_rank` ascending, then `served_on`
        ascending, then `created_at` ascending. The tie-break tail is fixed:
        `served_on` earlier wins within the same `priority_rank`"
        PRD §3.5: "for each order, the per-order amount is the smallest of
        `weekly_cap_cents`, the order's current `balance_remaining_cents`, and
        the `remaining` cap."

        Two CHILD_SUPPORT orders for same employee on a $2000 REGULAR paycheck:
        - A served 2025-06-01, cap 30000, bal 100000
        - B served 2025-07-01, cap 50000, bal 100000
        CCPA cap = 50% × disposable_earnings = 83,171c (after fed/state/FICA/medicare).
        A deducted first (earlier served_on) for min(30000, 100000, 83171) = 30000.
        Remaining = 53,171. B deducted min(50000, 100000, 53171) = 50,000.
        garnishment_total = 80,000. net_pay = 200000 - 33657 - 80000 = 86,343.

        Design: Difficulty/combinatorial_formula/garnishment_waterfall_eval_order_mode_c
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=100000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=50000, original_balance_cents=100000,
            served_on="2025-07-01T00:00:00.000Z",
        )
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["gross_wages_cents"] == 200000
        assert pay["fed_withheld_cents"] == 16357
        assert pay["state_withheld_cents"] == 2000
        assert pay["ss_withheld_cents"] == 12400
        assert pay["medicare_withheld_cents"] == 2900
        assert pay["garnishment_total_cents"] == 80000, (
            f"earlier served_on wins tie-break → A:30000 + B:50000 = 80000, "
            f"got {pay['garnishment_total_cents']}"
        )
        assert pay["net_pay_cents"] == 86343, (
            f"net_pay = 200000 - 33657 - 80000 = 86343, got {pay['net_pay_cents']}"
        )


# =========================================================================
# Queue (A) Difficulty — rule 8 resource_temporal_overlap (instance 2)
# =========================================================================

class TestGarnishmentAggregateCapacity:
    """PRD §3.5 aggregate capacity check distinct from single-intake CCPA check."""

    def test_aggregate_capacity_exceeded_at_intake(self, api):
        """PRD §3.5: "The second is an aggregate-capacity check: the sum of
        `weekly_cap_cents` over all currently-`ACTIVE` `GarnishmentOrder` rows
        for the employee, plus this new order's `weekly_cap_cents`, must not
        exceed the CCPA-derived aggregate capacity."
        PRD §3.5: "An aggregate-capacity violation surfaces as
        `ERR_GARNISHMENT_AGGREGATE_CAP`."

        Setup: employee w/ one PAID $2000 paycheck (disposable ~166,343c) plus
        an existing ACTIVE CHILD_SUPPORT @ 80000 weekly_cap. Adding a CREDITOR
        @ 50000 pushes the sum past the CCPA-derived capacity.

        Design: Difficulty/resource_temporal_overlap/garnishment_aggregate_capacity_on_employee
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-10-01T00:00:00.000Z",
            pay_period_end="2025-10-15T23:59:59.999Z",
            pay_date="2025-10-15T00:00:00.000Z",
        )
        # Existing ACTIVE CHILD_SUPPORT order with weekly_cap=80000
        create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=80000, original_balance_cents=1_000_000,
            served_on="2025-09-01T00:00:00.000Z",
        )
        # New CREDITOR order with weekly_cap=50000 — sum exceeds aggregate cap
        res = api_client.create_garnishment_order(
            create_garnishment_order_payload(
                employee_id=emp["id"],
                order_type="CREDITOR",
                weekly_cap_cents=50000,
                original_balance_cents=1_000_000,
                served_on="2025-09-15T00:00:00.000Z",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_GARNISHMENT_AGGREGATE_CAP", expected_status=422)


# =========================================================================
# Queue (B) Corner — validations garnishment_exceeds_ccpa_single_intake
# =========================================================================

class TestGarnishmentSingleIntakeCCPA:
    """PRD §3.5 first-intake check (single-order CCPA ceiling)."""

    def test_child_support_intake_cap_exceeds_recent_paid_paycheck(self, api):
        """PRD §3.5: "The first is a single-order CCPA ceiling: a `CHILD_SUPPORT`
        order whose `weekly_cap_cents` alone would exceed the CCPA 50% cap
        (`CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT = 5000` basis points, i.e.
        50.00%) of the employee's most recent `PAID`
        `Paycheck.gross_wages_cents` is rejected at intake with
        `ERR_GARNISHMENT_EXCEEDS_CCPA`."

        Setup: one PAID $2000 paycheck (gross=200000c). 50% cap = 100000c.
        A CHILD_SUPPORT order with weekly_cap=150000 exceeds the cap.

        Design: Corner/validations/garnishment_exceeds_ccpa_single_intake
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-10-01T00:00:00.000Z",
            pay_period_end="2025-10-15T23:59:59.999Z",
            pay_date="2025-10-15T00:00:00.000Z",
        )
        res = api_client.create_garnishment_order(
            create_garnishment_order_payload(
                employee_id=emp["id"],
                order_type="CHILD_SUPPORT",
                weekly_cap_cents=150000,
                original_balance_cents=500000,
                served_on="2025-09-01T00:00:00.000Z",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_GARNISHMENT_EXCEEDS_CCPA", expected_status=422)
