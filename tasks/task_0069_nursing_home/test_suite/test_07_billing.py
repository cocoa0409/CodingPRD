"""Billing: line-item composition (PACKAGE vs A_LA_CARTE), subsidy,
insurance, deposit waterfall, payment idempotency, refund.

Anchored in PRD §3.7.
"""
from __future__ import annotations
from datetime import date
import pytest

from test_helpers import (
    ApiErrorId,
    GOV_SUBSIDY_MONTHLY_CAP_CENTS,
    INSURANCE_COVERAGE_RATE,
    PACKAGE_DAILY_CARE_CENTS,
    PACKAGE_DAILY_MEAL_CENTS,
    SUBSIDY_RATE_BY_LEVEL,
    api_client,
    assert_bill_finalized_invariants,
    create_bill, create_bill_payload,
    finalize_bill, full_cycle_window,
    pay_bill, pay_bill_payload, refund_payload,
    setup_admitted_elder_v2,
    setup_admitted_with_finalized_bill,
    top_up_deposit, unique_payment_ref,
    ADMIN, FAMILY, FINANCE,
    round_half_up_int,
    validate_error, validate_success,
)


# ===========================================================================
# Package billing math (PRD §3.7)
# ===========================================================================
class TestPackageBillingMath:

    def test_package_subtotal_matches_pinned_formula(self):
        """PRD §3.7: "In `PACKAGE` mode, the `care_level_snapshot` ...
        drives a per-level daily care rate — 5,000 cents per day for
        `L1`, 8,000 for `L2`, 12,000 for `L3`, 18,000 for `L4`, and
        30,000 for `INTENSIVE` — multiplied by `admitted_days` to yield
        the `CARE` line in integer cents; the `MEAL` line is 4,000 cents
        per day multiplied by `admitted_days`."

        Claim: for L3 elder + 30-day cycle + bed_fee 60000/mo,
        subtotal_cents = 60000 (bed) + 12000*30 (care) + 4000*30 (meal)
                       = 540000.
        # difficulty: dual_variant_calc/billing_package_vs_a_la_carte_same_cycle
        """
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,  # L3
            monthly_bed_fee_cents=60_000,
            deposit_cents=10_000_000,
        )
        bill = bundle["bill"]
        assert_bill_finalized_invariants(bill)
        assert bill["subtotal_cents"] == 540_000, \
            f"PRD §3.7 PACKAGE — expected subtotal 540000, got {bill['subtotal_cents']}"


# ===========================================================================
# Subsidy and floor semantics (PRD §3.7)
# ===========================================================================
class TestSubsidyMath:

    def test_subsidy_floored_to_integer_cents(self):
        """PRD §3.7: "The raw subsidy is `subtotal_cents` multiplied by the
        rate and then floored to integer cents — never rounded up."

        Claim: subsidy is floor(subtotal * rate), capped at monthly cap.
        For L3 (rate=0.20), subtotal 540000 → floor(108000) = 108000
        (well below 200000 cap).
        """
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=60_000,
            deposit_cents=10_000_000,
        )
        bill = bundle["bill"]
        expected_raw = int(bill["subtotal_cents"] * 0.20)
        expected_subsidy = min(expected_raw, GOV_SUBSIDY_MONTHLY_CAP_CENTS)
        assert bill["government_subsidy_cents"] == expected_subsidy, \
            f"PRD §3.7 — expected subsidy {expected_subsidy}, got " \
            f"{bill['government_subsidy_cents']}"

    def test_subsidy_capped_at_monthly_cap(self):
        """PRD §3.7: "The final `government_subsidy_cents` is the smaller
        of the raw figure and the monthly cap of 2,000.00 (200,000 cents)."

        Claim: when raw subsidy would exceed 200000 cents, the bill is
        capped at exactly 200000.
        """
        # Build INTENSIVE elder (rate 0.40) with a large bed fee →
        # subtotal so high that floor(subtotal * 0.40) >> 200000.
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=20, cognitive_score=5, medical_condition_score=40,
            monthly_bed_fee_cents=600_000,    # 6,000.00/mo
            deposit_cents=20_000_000,
        )
        bill = bundle["bill"]
        # subtotal: bed 600000 + care 30000*30=900000 + meal 4000*30=120000
        # = 1,620,000 → raw subsidy = floor(0.40 * 1,620,000) = 648000
        # → capped at 200000.
        assert bill["government_subsidy_cents"] == GOV_SUBSIDY_MONTHLY_CAP_CENTS


# ===========================================================================
# Deposit waterfall (PRD §3.7)
# ===========================================================================
class TestDepositWaterfall:

    def test_deposit_applied_capped_at_balance_and_remainder(self):
        """PRD §3.7: "the remaining amount, computed as `subtotal_cents`
        minus `government_subsidy_cents` minus `insurance_offset_cents`
        and never permitted to be below zero, is offered to the elder's
        `deposit_balance_cents`; `deposit_applied_cents` is the smaller
        of the remainder and the current `deposit_balance_cents`."

        Claim: deposit_applied_cents == min(remainder, deposit_balance).
        With a tiny deposit, deposit_applied_cents equals the deposit
        balance available at finalize-time.
        """
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=60_000,
            deposit_cents=500_000,  # exactly the floor; little left over
        )
        bill = bundle["bill"]
        # subtotal 540000, subsidy 108000, no medical → no insurance.
        # remainder = 540000 - 108000 - 0 = 432000.
        # deposit available at finalize = 500000.
        # So deposit_applied = min(432000, 500000) = 432000.
        # amount_due = remainder - deposit_applied = 0.
        # However: balance was 500000 going in; deposit applied 432000
        # leaves balance 68000 for any future use.
        assert bill["deposit_applied_cents"] == 432_000
        assert bill["amount_due_cents"] == 0


# ===========================================================================
# Payment lifecycle + idempotency (PRD §3.7)
# ===========================================================================
class TestPayment:

    def test_pay_with_unfinalized_bill_rejected(self):
        """PRD §3.7: "A pay request against a bill that is not in
        `FINALIZED` is rejected with `ERR_BILL_NOT_FINALIZED`."

        Claim: posting /pay on a DRAFT bill → ERR_BILL_NOT_FINALIZED.
        """
        bundle = setup_admitted_elder_v2(80, 10, 20, deposit_cents=600_000)
        start, end, _ = full_cycle_window(date(2025, 6, 1))
        bill = create_bill(bundle["elder"]["id"], start, end, "PACKAGE")
        # Do NOT finalize.
        resp = api_client.pay_bill(
            bill["id"], pay_bill_payload(), FAMILY,
        )
        validate_error(resp, ApiErrorId.ERR_BILL_NOT_FINALIZED.value)

    def test_duplicate_payment_ref_on_different_bill_rejected(self):
        """PRD §3.7: "The same `external_payment_ref` posted to a different
        bill is rejected with `ERR_DUPLICATE_PAYMENT`."

        Claim: reusing an external_payment_ref on a *different* bill →
        ERR_DUPLICATE_PAYMENT.
        """
        # Engineer bills with guaranteed positive amount_due so each /pay
        # actually requires the external_payment_ref. With L3 PACKAGE month
        # at bed_fee 600_000 and deposit at the §2.7 #23 floor 500_000, the
        # subtotal (1_080_000) exceeds subsidy_cap+deposit, so amount_due>0.
        # Bill A: pay with ref.
        bundleA = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=600_000,
            deposit_cents=500_000,
        )
        assert bundleA["bill"]["amount_due_cents"] > 0, (
            "fixture must produce non-zero amount_due so /pay is exercised"
        )
        ref = unique_payment_ref()
        pay_bill(bundleA["bill"]["id"], external_payment_ref=ref)
        # Bill B: reuse ref.
        bundleB = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 7, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=600_000,
            deposit_cents=500_000,
        )
        assert bundleB["bill"]["amount_due_cents"] > 0, (
            "fixture must produce non-zero amount_due so /pay is exercised"
        )
        resp = api_client.pay_bill(
            bundleB["bill"]["id"], pay_bill_payload(ref), FAMILY,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYMENT.value)


# ===========================================================================
# Refund deposit invariant (PRD §3.7)
# ===========================================================================
class TestRefundDepositInvariant:

    def test_refund_restores_deposit_up_to_applied(self):
        """PRD §3.7: "On refund, the elder's `deposit_balance_cents` is
        incremented by the smaller of `refund_amount_cents` and the bill's
        original `deposit_applied_cents` (so that the deposit is never
        inflated beyond what was originally drawn), the bill moves to
        `REFUNDED`."

        Claim: refunding restores deposit_balance by exactly the
        deposit_applied portion.
        # difficulty: compensating_invariant/deposit_refund_invariant
        """
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=60_000,
            deposit_cents=1_000_000,
        )
        bill = bundle["bill"]
        deposit_applied = bill["deposit_applied_cents"]
        if bill["amount_due_cents"] > 0:
            pay_bill(bill["id"])
        # Now refund the full deposit_applied portion.
        if deposit_applied <= 0:
            pytest.skip("no deposit was applied")
        resp = api_client.refund_bill(
            bill["id"], refund_payload(deposit_applied), FINANCE,
        )
        refunded = validate_success(resp, expected_status=200)
        assert refunded["status"] == "REFUNDED"
        # Elder.deposit_balance_cents increased by deposit_applied.
        from test_helpers import get_elder
        elder = get_elder(bundle["elder"]["id"])
        # Original balance was 1,000,000; after finalize: 1,000,000 -
        # deposit_applied; after refund: should be back to 1,000,000.
        assert elder["deposit_balance_cents"] == 1_000_000

    def test_refund_above_eligible_amount_rejected(self):
        """PRD §3.7: "The refund amount must not exceed the bill's
        original `deposit_applied_cents` plus the amount actually paid
        externally; an excess is rejected with `ERR_REFUND_OVER_LIMIT`."

        Claim: refund > (deposit_applied + paid_externally) →
        ERR_REFUND_OVER_LIMIT.
        """
        bundle = setup_admitted_with_finalized_bill(
            cycle_start=date(2025, 6, 1),
            billing_mode="PACKAGE",
            adl_score=80, cognitive_score=10, medical_condition_score=20,
            monthly_bed_fee_cents=60_000,
            deposit_cents=1_000_000,
        )
        bill = bundle["bill"]
        if bill["amount_due_cents"] > 0:
            pay_bill(bill["id"])
        eligible = bill["deposit_applied_cents"] + bill["amount_due_cents"]
        # Request 10000 cents more than eligible.
        resp = api_client.refund_bill(
            bill["id"], refund_payload(eligible + 10_000), FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_OVER_LIMIT.value)
