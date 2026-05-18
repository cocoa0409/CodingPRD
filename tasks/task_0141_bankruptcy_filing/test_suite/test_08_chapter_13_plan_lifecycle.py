"""Chapter 13 plan lifecycle: propose / withdraw / re-propose / confirm.

PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_plan,
    confirm_plan,
    create_plan_payload,
    make_debtor_headers,
    re_get_case,
    re_get_plan,
    setup_ch13_plan_proposed,
    setup_meeting_held_case,
    submit_plan,
    validate_error,
    withdraw_plan,
)


# ===========================================================================
# Plan submission — PRD §3.8
# ===========================================================================
class TestPlanSubmission:
    """PRD §3.8: 'A Chapter 13 case proceeds instead from MEETING_HELD
    to PLAN_PROPOSED when the debtor submits a reorganization Plan.
    Plan submission is permitted only when chapter_effective is
    CHAPTER_13; submitting a plan against a Chapter 7 case is rejected
    with ERR_NOT_CHAPTER_13.'"""

    def test_submit_plan_against_ch7_case_rejected(self, api):
        """PRD §3.8: "Plan submission is permitted only when
        chapter_effective is CHAPTER_13; submitting a plan against a
        Chapter 7 case is rejected with ERR_NOT_CHAPTER_13."

        Claim: POST /cases/{ch7}/plans -> ERR_NOT_CHAPTER_13.
        """
        debtor, case, _mtr, _cr, _claims = setup_meeting_held_case(
            chapter_requested="CHAPTER_7",
        )
        resp = api.create_plan(
            case["id"],
            create_plan_payload(
                proposed_monthly_payment_cents=10_000, plan_months=36,
            ),
            make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_CHAPTER_13.value)

    def test_submit_plan_advances_case_to_plan_proposed(self, api):
        """PRD §3.8: "A Chapter 13 case proceeds instead from
        MEETING_HELD to PLAN_PROPOSED when the debtor submits a
        reorganization Plan."

        Claim: after submit_plan, Plan.status=PROPOSED and
        Case.status=PLAN_PROPOSED.
        """
        debtor, case, _mtr, plan, _cr, _cl = setup_ch13_plan_proposed()
        assert_plan(plan)
        assert plan["status"] == "PROPOSED"
        assert case["status"] == "PLAN_PROPOSED"

    def test_planned_total_cents_is_payment_times_months(self, api):
        """PRD §3.8: "The server computes planned_total_cents as the
        product of proposed_monthly_payment_cents and plan_months and
        freezes it on the plan row".

        Claim: planned_total_cents = proposed_monthly_payment * months.
        """
        # Build means-test with disposable=0 so any payment value
        # passes the floor check at confirmation.
        debtor, _case, _mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_payment_cents=20_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert plan["proposed_monthly_payment_cents"] == 20_000
        assert plan["plan_months"] == 36
        assert plan["planned_total_cents"] == 20_000 * 36

    def test_plan_starts_with_zero_paid_and_zero_misses(self, api):
        """PRD §3.8: "the plan begins in PROPOSED status with
        paid_to_date_cents and missed_payment_count both initialized
        to zero."

        Claim: paid_to_date_cents=0, missed_payment_count=0 at PROPOSED.
        """
        debtor, _case, _mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert plan["paid_to_date_cents"] == 0
        assert plan["missed_payment_count"] == 0

    def test_plan_months_must_match_required_plan_months(self, api):
        """PRD §3.8: "The plan submission also requires plan_months to
        equal MeansTestResult.required_plan_months; a mismatch is
        rejected with ERR_PLAN_MONTHS_MISMATCH."

        Claim: plan_months != required_plan_months at submission ->
        ERR_PLAN_MONTHS_MISMATCH.
        """
        # required_plan_months=36 for non-presumption income.
        debtor, case, _mtr, _cr, _claims = setup_meeting_held_case(
            chapter_requested="CHAPTER_13",
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        resp = api.create_plan(
            case["id"],
            create_plan_payload(
                proposed_monthly_payment_cents=10_000, plan_months=24,
            ),
            make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_MONTHS_MISMATCH.value)


# ===========================================================================
# At-most-one Plan — PRD §3.8
# ===========================================================================
class TestAtMostOnePlanPerCase:
    """PRD §3.8: 'At most one plan per case may exist in any of the
    active plan states (PROPOSED, CONFIRMED, or IN_REPAYMENT); a
    second plan insert while one of these is current is rejected with
    ERR_PLAN_ALREADY_EXISTS, which also serializes two debtors racing
    a plan submission so that exactly one of the two POSTs wins.'"""

    def test_second_plan_when_first_is_proposed_rejected(self, api):
        """PRD §3.8: "At most one plan per case may exist in any of
        the active plan states (PROPOSED, CONFIRMED, or
        IN_REPAYMENT); a second plan insert while one of these is
        current is rejected with ERR_PLAN_ALREADY_EXISTS, which also
        serializes two debtors racing a plan submission so that
        exactly one of the two POSTs wins."

        Claim: second POST /cases/{c}/plans while first plan is
        PROPOSED -> ERR_PLAN_ALREADY_EXISTS.
        """
        debtor, case, mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        # Second submission with same months parameter.
        resp = api.create_plan(
            case["id"],
            create_plan_payload(
                proposed_monthly_payment_cents=15_000,
                plan_months=mtr["required_plan_months"],
            ),
            make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_EXISTS.value)


# ===========================================================================
# Plan withdrawal cyclic shape — PRD §3.8
# ===========================================================================
class TestPlanWithdrawal:
    """PRD §3.8: 'A PROPOSED plan may be withdrawn by the debtor while
    the case is still in PLAN_PROPOSED, in which case the plan's
    status transitions to WITHDRAWN and the case status reverts to
    MEETING_HELD. From MEETING_HELD the debtor may then submit a
    different plan — this cyclic shape allows iterative refinement of
    the reorganization proposal.'"""

    def test_withdraw_proposed_plan_reverts_case_to_meeting_held(self, api):
        """PRD §3.8: "A PROPOSED plan may be withdrawn by the debtor
        while the case is still in PLAN_PROPOSED, in which case the
        plan's status transitions to WITHDRAWN and the case status
        reverts to MEETING_HELD."

        Claim: DELETE plan -> plan.WITHDRAWN; case.MEETING_HELD.
        # difficulty: non_linear_state_machine/plan_cyclic_propose_withdraw_repropose
        """
        debtor, case, mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        withdrawn = withdraw_plan(case=case, plan=plan, debtor=debtor)
        assert withdrawn["status"] == "WITHDRAWN"
        case_after = re_get_case(case["id"])
        assert case_after["status"] == "MEETING_HELD"

    def test_withdraw_then_resubmit_creates_new_plan(self, api):
        """PRD §3.8: "From MEETING_HELD the debtor may then submit a
        different plan — this cyclic shape allows iterative refinement
        of the reorganization proposal."

        Claim: after withdraw, a second submit_plan succeeds with a
        new id and case back to PLAN_PROPOSED.
        # difficulty: non_linear_state_machine/plan_cyclic_propose_withdraw_repropose
        """
        debtor, case, mtr, plan_a, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        withdraw_plan(case=case, plan=plan_a, debtor=debtor)
        case_back = re_get_case(case["id"])
        assert case_back["status"] == "MEETING_HELD"
        plan_b = submit_plan(
            case=case_back, debtor=debtor,
            proposed_monthly_payment_cents=15_000,
            plan_months=mtr["required_plan_months"],
        )
        assert plan_b["id"] != plan_a["id"]
        assert plan_b["status"] == "PROPOSED"
        case_after2 = re_get_case(case["id"])
        assert case_after2["status"] == "PLAN_PROPOSED"

    def test_withdraw_proposed_preserves_paid_to_date_zero_across_replan(self, api):
        """PRD §3.8: "From MEETING_HELD the debtor may then submit a
        different plan — this cyclic shape allows iterative refinement
        of the reorganization proposal."

        Claim: after withdraw+repropose, the withdrawn Plan retains
        paid_to_date_cents=0 (no payments existed) and the new Plan
        starts with paid_to_date_cents=0. No payment drift is
        introduced by the cycle.
        # difficulty: compensating_invariant/plan_withdraw_repropose_preserves_paid_to_date_zero
        """
        debtor, case, mtr, plan_a, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert plan_a["paid_to_date_cents"] == 0
        withdrawn = withdraw_plan(case=case, plan=plan_a, debtor=debtor)
        # PRD: TrusteePayment is append-only; withdrawing has no payments
        # to undo; paid_to_date_cents remains 0.
        assert withdrawn["paid_to_date_cents"] == 0
        case_back = re_get_case(case["id"])
        plan_b = submit_plan(
            case=case_back, debtor=debtor,
            proposed_monthly_payment_cents=15_000,
            plan_months=mtr["required_plan_months"],
        )
        assert plan_b["paid_to_date_cents"] == 0

    def test_withdraw_plan_when_case_not_plan_proposed_rejected(self, api):
        """PRD §3.8: "Attempting to withdraw a plan when the case is
        not in PLAN_PROPOSED is rejected with ERR_INVALID_STATE."

        Claim: withdraw after Plan has been confirmed (case in
        PLAN_CONFIRMED) -> ERR_INVALID_STATE.
        """
        debtor, case, mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        confirm_plan(case=case, plan=plan)
        case_conf = re_get_case(case["id"])
        assert case_conf["status"] == "PLAN_CONFIRMED"
        resp = api.withdraw_plan(
            case["id"], plan["id"], make_debtor_headers(debtor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Plan confirmation — PRD §3.8
# ===========================================================================
class TestPlanConfirmation:
    """PRD §3.8: 'Confirmation is the judicial act that locks the plan
    and advances the case to PLAN_CONFIRMED. Two preconditions guard
    the confirmation: planned_total_cents must be at least
    MeansTestResult.minimum_plan_total_cents (the floor inclusive;
    less yields ERR_PLAN_UNDERFUNDED), and plan_months must equal
    MeansTestResult.required_plan_months (a mismatch yields
    ERR_PLAN_MONTHS_MISMATCH). On confirmation, the plan's status
    moves to CONFIRMED and the case's status moves to PLAN_CONFIRMED in
    the same transaction.'"""

    def test_confirmation_below_floor_rejected(self, api):
        """PRD §3.8: "planned_total_cents must be at least
        MeansTestResult.minimum_plan_total_cents (the floor inclusive;
        less yields ERR_PLAN_UNDERFUNDED)".

        Claim: planned_total < minimum_plan_total -> ERR_PLAN_UNDERFUNDED.
        # difficulty: cross_entity_state_dependency/plan_confirm_requires_case_means_test_result
        """
        # disposable=190_000, required_months=36 -> min_total=6_840_000.
        # Plan 180_000 * 36 = 6_480_000 (below floor by 360_000).
        debtor, case, mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_payment_cents=180_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=10_000,
        )
        assert plan["planned_total_cents"] == 180_000 * 36
        assert mtr["minimum_plan_total_cents"] == 190_000 * 36
        resp = api.confirm_plan(
            case["id"], plan["id"], None, TEST_USERS["judge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_UNDERFUNDED.value)

    def test_confirmation_at_exact_floor_succeeds(self, api):
        """PRD §3.8: "planned_total_cents must be at least
        MeansTestResult.minimum_plan_total_cents (the floor inclusive;
        less yields ERR_PLAN_UNDERFUNDED)".

        Claim: planned_total = minimum_plan_total (boundary inclusive)
        -> ERR_PLAN_UNDERFUNDED NOT fired; status moves to CONFIRMED.
        """
        # disposable=200_000, required=36 -> min_total=7_200_000.
        # Plan exactly 200_000 × 36 = 7_200_000.
        debtor, case, mtr, plan, _cr, _cl = setup_ch13_plan_proposed(
            monthly_payment_cents=200_000, plan_months=36,
            monthly_income_cents=300_000, monthly_expenses_cents=100_000,
        )
        assert plan["planned_total_cents"] == mtr["minimum_plan_total_cents"]
        result = confirm_plan(case=case, plan=plan)
        assert result["status"] == "CONFIRMED"
        case_after = re_get_case(case["id"])
        assert case_after["status"] == "PLAN_CONFIRMED"
