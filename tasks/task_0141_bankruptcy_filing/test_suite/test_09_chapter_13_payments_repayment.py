"""Chapter 13 trustee payments and the PLAN_CONFIRMED → IN_REPAYMENT
transition.

PRD §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_trustee_payment,
    create_payment_payload,
    make_debtor_headers,
    re_get_case,
    re_get_plan,
    record_payment,
    setup_ch13_in_repayment,
    setup_ch13_plan_confirmed,
    validate_error,
)


# ===========================================================================
# Payment shape — PRD §3.9 / §2.4
# ===========================================================================
class TestTrusteePaymentShape:
    """PRD §3.9: 'Each payment carries a sequence_number (the monthly
    index, unique per plan and in the range from 1 to the plan's
    plan_months inclusive), an amount_cents, and a status of either
    APPLIED (paid) or MISSED (recorded missed month). The server
    stamps applied_at with its current clock at the moment the row is
    recorded.'"""

    def test_record_payment_returns_lean_row(self, api):
        """PRD §2.4: "TrusteePayment rows are append-only ledger
        entries and carry only id and created_at."

        Claim: TrusteePayment row carries id + created_at; no version
        or updated_at.
        """
        debtor, case, mtr, plan, _cr, _cl = setup_ch13_plan_confirmed(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        pay = record_payment(
            case=case, plan=plan, debtor=debtor,
            sequence_number=1, amount_cents=10_000, status="APPLIED",
        )
        assert_trustee_payment(pay)
        assert "version" not in pay, (
            f"PRD §2.4: TrusteePayment has no version; got {pay.get('version')!r}"
        )
        assert "updated_at" not in pay, (
            f"PRD §2.4: TrusteePayment has no updated_at; got {pay.get('updated_at')!r}"
        )


# ===========================================================================
# First APPLIED payment triggers IN_REPAYMENT — PRD §3.9
# ===========================================================================
class TestFirstAppliedPaymentTransitionsToInRepayment:
    """PRD §3.9: 'The first APPLIED payment with sequence_number 1 on
    a CONFIRMED plan advances the case from PLAN_CONFIRMED to
    IN_REPAYMENT.'"""

    def test_first_applied_payment_advances_case(self, api):
        """PRD §3.9: "The first APPLIED payment with sequence_number 1
        on a CONFIRMED plan advances the case from PLAN_CONFIRMED to
        IN_REPAYMENT."

        Claim: after first APPLIED payment with seq=1, case.status=
        IN_REPAYMENT.
        """
        debtor, case, _mtr, plan, _cr, _cl = setup_ch13_in_repayment(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        assert case["status"] == "IN_REPAYMENT"


# ===========================================================================
# Plan aggregates — PRD §2.11
# ===========================================================================
class TestPlanAggregates:
    """PRD §2.11: 'Plan.paid_to_date_cents is the sum of amount_cents
    across all TrusteePayment rows on this plan whose status is
    APPLIED. Plan.missed_payment_count is the count of TrusteePayment
    rows on this plan whose status is MISSED.'"""

    def test_paid_to_date_sums_applied_amounts(self, api):
        """PRD §2.11: "Plan.paid_to_date_cents is the sum of
        amount_cents across all TrusteePayment rows on this plan whose
        status is APPLIED."

        Claim: paid_to_date_cents equals sum over APPLIED.
        """
        debtor, case, _mtr, plan_after_first, _cr, _cl = setup_ch13_in_repayment(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        # Record one more APPLIED.
        record_payment(
            case=case, plan=plan_after_first, debtor=debtor,
            sequence_number=2, amount_cents=10_000, status="APPLIED",
        )
        plan_after = re_get_plan(case["id"], plan_after_first["id"])
        assert plan_after["paid_to_date_cents"] == 20_000

    def test_missed_payment_count_counts_missed(self, api):
        """PRD §2.11: "Plan.missed_payment_count is the count of
        TrusteePayment rows on this plan whose status is MISSED."

        Claim: missed_payment_count = number of MISSED rows.
        """
        debtor, case, _mtr, plan_after_first, _cr, _cl = setup_ch13_in_repayment(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        # Two missed.
        record_payment(
            case=case, plan=plan_after_first, debtor=debtor,
            sequence_number=2, amount_cents=0, status="MISSED",
        )
        record_payment(
            case=case, plan=plan_after_first, debtor=debtor,
            sequence_number=3, amount_cents=0, status="MISSED",
        )
        plan_after = re_get_plan(case["id"], plan_after_first["id"])
        assert plan_after["missed_payment_count"] == 2

    def test_missed_payment_does_not_increment_paid_to_date(self, api):
        """PRD §2.11: "Plan.paid_to_date_cents is the sum of
        amount_cents across all TrusteePayment rows on this plan whose
        status is APPLIED."

        Claim: a MISSED payment does NOT contribute to
        paid_to_date_cents (which is APPLIED-only).
        """
        debtor, case, _mtr, plan_after_first, _cr, _cl = setup_ch13_in_repayment(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        # paid_to_date is 10_000 after first APPLIED.
        record_payment(
            case=case, plan=plan_after_first, debtor=debtor,
            sequence_number=2, amount_cents=99_999, status="MISSED",
        )
        plan_after = re_get_plan(case["id"], plan_after_first["id"])
        assert plan_after["paid_to_date_cents"] == 10_000


# ===========================================================================
# Duplicate sequence_number — PRD §3.9
# ===========================================================================
class TestDuplicateSequenceNumber:
    """PRD §3.9: 'Two payments racing the same sequence_number for the
    same plan serialize on the uniqueness constraint and the loser is
    rejected with ERR_PAYMENT_SEQUENCE_DUPLICATE (HTTP 409); the same
    error is returned for any duplicate-sequence insert outside the
    race condition.'"""

    def test_second_insert_with_same_sequence_number_rejected(self, api):
        """PRD §3.9: "Two payments racing the same sequence_number for
        the same plan serialize on the uniqueness constraint and the
        loser is rejected with ERR_PAYMENT_SEQUENCE_DUPLICATE (HTTP
        409); the same error is returned for any duplicate-sequence
        insert outside the race condition."

        Claim: a second payment with the same (plan_id,
        sequence_number) -> ERR_PAYMENT_SEQUENCE_DUPLICATE.
        # difficulty: resource_temporal_overlap/trustee_payment_sequence_no_duplicate_per_plan
        """
        debtor, case, _mtr, plan, _cr, _cl = setup_ch13_in_repayment(
            monthly_payment_cents=20_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        # The setup already recorded seq=1 APPLIED. Re-attempt seq=1.
        resp = api.record_payment(
            case["id"], plan["id"],
            create_payment_payload(
                sequence_number=1, amount_cents=20_000, status="APPLIED",
            ),
            make_debtor_headers(debtor["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_PAYMENT_SEQUENCE_DUPLICATE.value,
        )
        # And paid_to_date_cents should remain 20_000 (the first one),
        # confirming the duplicate did NOT increment.
        plan_after = re_get_plan(case["id"], plan["id"])
        assert plan_after["paid_to_date_cents"] == 20_000

    def test_sequence_number_out_of_range_rejected(self, api):
        """PRD §3.9: "A sequence_number outside the valid range is
        similarly rejected with ERR_PAYMENT_SEQUENCE_DUPLICATE."

        Claim: sequence_number > plan_months ->
        ERR_PAYMENT_SEQUENCE_DUPLICATE (PRD-pinned error).
        """
        debtor, case, _mtr, plan, _cr, _cl = setup_ch13_in_repayment(
            monthly_payment_cents=10_000, plan_months=36,
            monthly_income_cents=200_000, monthly_expenses_cents=400_000,
        )
        # plan_months=36 → seq=37 out of range.
        resp = api.record_payment(
            case["id"], plan["id"],
            create_payment_payload(
                sequence_number=37, amount_cents=10_000, status="APPLIED",
            ),
            make_debtor_headers(debtor["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_PAYMENT_SEQUENCE_DUPLICATE.value,
        )
