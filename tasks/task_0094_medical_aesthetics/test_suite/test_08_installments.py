"""Installment financing — PRD §3.7.

Covers:
  - Tiered APR table {3→0, 6→600, 12→1200, 24→1800} bps.
  - Annuity-formula schedule generation with last-period residual
    absorption so sum(principal_cents) == principal_cents.
  - KYC + credit gate at activation.
  - downpayment / payment-amount range guards.
  - exactly-one InstallmentPlan per TreatmentPlan.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GRACE_DAYS,
    MIN_CREDIT_SCORE,
    SECONDS_PER_DAY,
    TEST_USERS,
    TERM_APR_TABLE,
    activate_installment_plan,
    advance_clock,
    api_client,
    assert_installment_plan,
    assert_installment_principal_sum,
    create_installment_plan,
    create_installment_payload,
    get_installment,
    pay_installment,
    setup_active_installment,
    setup_approved_plan_simple,
    validate_error,
    validate_success,
    verify_customer_kyc,
)


# ===========================================================================
# Schedule for term=6 (Rule 2 instance 1)
# ===========================================================================
# difficulty: combinatorial_formula/installment_schedule_tiered_rate_mode_a
class TestInstallmentScheduleTerm6:
    """PRD §3.7: "The annual percentage rate in basis points is
    selected from a term-keyed table: 0 for a 3-month term ... 600 for
    6 months ... With principal P equal to principal_cents and term n
    equal to term_months, the monthly total in cents is computed by
    the standard annuity formula — principal times monthly rate times
    one-plus-monthly-rate raised to the power n, divided by one-plus-
    monthly-rate raised to the power n minus one — and that value is
    rounded half-up to integer cents."

    Worked example from the difficulty index: principal_cents=30000,
    term_months=6, downpayment=0:
      - apr_bps == 600
      - schedule.length == 6
      - schedule[0].principal_cents == 4938, interest_cents == 150,
        total_cents == 5088
      - schedule[5].principal_cents == 5061 (final-period residual)
      - sum(schedule[i].principal_cents) == 30000
    """

    def test_term_6_yields_apr_600(self, api):
        """PRD §3.7: "The annual percentage rate in basis points is
        selected from a term-keyed table: 0 for a 3-month term (a
        promotional zero-interest tier), 600 for 6 months, 1200 for
        12 months, and 1800 for 24 months."

        Claim: term_months=6 → apr_bps == 600.

        # difficulty: combinatorial_formula/installment_schedule_tiered_rate_mode_a
        """
        bundle = setup_active_installment(
            term_months=6, base_price_cents=30000, credit_score=800,
        )
        inst = bundle["installment"]
        assert inst["apr_bps"] == 600, (
            f"PRD §3.7 APR table: term_months=6 → apr_bps=600; got "
            f"{inst['apr_bps']}"
        )

    def test_term_6_schedule_length_matches(self, api):
        """PRD §3.7: "The schedule is therefore an array of {index,
        due_date, principal_cents, interest_cents, total_cents,
        status} entries with each due_date equal to the activation
        timestamp plus index months."

        Claim: len(schedule) == term_months (6).

        # difficulty: combinatorial_formula/installment_schedule_tiered_rate_mode_a
        """
        bundle = setup_active_installment(
            term_months=6, base_price_cents=30000, credit_score=800,
        )
        inst = bundle["installment"]
        assert len(inst["schedule"]) == 6, (
            f"PRD §3.7: schedule length must equal term_months=6; "
            f"got {len(inst['schedule'])}"
        )

    def test_term_6_first_period_principal_interest_total(self, api):
        """PRD §3.7: "for each period from 1 to n-1, the period's
        interest in cents is the running balance times the monthly
        rate rounded half-up, and the period's principal in cents is
        the monthly total minus the period's interest; the running
        balance is reduced by the period's principal."

        Claim: schedule[0].principal_cents == 4938, interest_cents
        == 150, total_cents == 5088 (worked example from the
        difficulty index for principal 30000, term 6, APR 600 bps).

        # difficulty: combinatorial_formula/installment_schedule_tiered_rate_mode_a
        """
        bundle = setup_active_installment(
            term_months=6, base_price_cents=30000, credit_score=800,
        )
        inst = bundle["installment"]
        first = inst["schedule"][0]
        assert first["principal_cents"] == 4938, (
            f"PRD §3.7 worked example: schedule[0].principal_cents == "
            f"4938; got {first['principal_cents']}"
        )
        assert first["interest_cents"] == 150, (
            f"PRD §3.7 worked example: schedule[0].interest_cents == "
            f"150; got {first['interest_cents']}"
        )
        assert first["total_cents"] == 5088, (
            f"PRD §3.7 worked example: schedule[0].total_cents == "
            f"5088; got {first['total_cents']}"
        )

    def test_term_6_final_period_absorbs_residual(self, api):
        """PRD §3.7: "The final period absorbs any residual: its
        principal in cents equals the remaining running balance
        exactly."

        Claim: schedule[5].principal_cents == 5061 (worked example).

        # difficulty: combinatorial_formula/installment_schedule_tiered_rate_mode_a
        """
        bundle = setup_active_installment(
            term_months=6, base_price_cents=30000, credit_score=800,
        )
        inst = bundle["installment"]
        last = inst["schedule"][-1]
        assert last["principal_cents"] == 5061, (
            f"PRD §3.7 final-period residual absorption: "
            f"schedule[5].principal_cents == 5061; got "
            f"{last['principal_cents']}"
        )

    def test_term_6_principal_sum_invariant(self, api):
        """PRD §3.7: "so that the sum of per-period principal equals
        the original principal exactly."

        Claim: sum(schedule[i].principal_cents) == principal_cents.

        # difficulty: combinatorial_formula/installment_schedule_tiered_rate_mode_a
        """
        bundle = setup_active_installment(
            term_months=6, base_price_cents=30000, credit_score=800,
        )
        inst = bundle["installment"]
        assert_installment_principal_sum(inst)
        # And explicitly check the worked-example number.
        total_principal = sum(
            int(e["principal_cents"]) for e in inst["schedule"]
        )
        assert total_principal == 30000


# ===========================================================================
# Zero-APR 3-month tier
# ===========================================================================
class TestZeroAPRTier:

    def test_term_3_zero_apr_no_interest(self, api):
        """PRD §3.7: "0 for a 3-month term (a promotional zero-interest
        tier) ... For the zero-APR 3-month tier the formula
        degenerates: every period's interest_cents is 0 and every
        monthly total is the original principal divided by 3 rounded
        half-up with the last period absorbing the residual."

        Claim: term_months=3 → every schedule entry has interest_cents
        == 0; apr_bps == 0.
        """
        bundle = setup_active_installment(
            term_months=3, base_price_cents=30000, credit_score=600,
        )
        inst = bundle["installment"]
        assert inst["apr_bps"] == 0
        for entry in inst["schedule"]:
            assert entry["interest_cents"] == 0, (
                f"PRD §3.7 zero-APR tier: every interest_cents must "
                f"be 0; got {entry['interest_cents']}"
            )
        # Sum invariant holds.
        assert_installment_principal_sum(inst)


# ===========================================================================
# Activation gates (term, KYC, credit)
# ===========================================================================
class TestActivationGates:

    @pytest.mark.parametrize("bad_term", [0, 1, 4, 9, 15, 36])
    def test_invalid_term_rejected(self, api, bad_term):
        """PRD §3.7: "The term_months must be one of 3, 6, 12, or 24
        — any other value yields ERR_INVALID_INSTALLMENT_TERM (HTTP
        422)."

        Claim: term outside {3,6,12,24} → ERR_INVALID_INSTALLMENT_TERM.
        """
        bundle = setup_approved_plan_simple(base_price_cents=30000)
        payload = create_installment_payload(
            treatment_plan_id=bundle["plan"]["id"],
            downpayment_cents=0,
            term_months=int(bad_term),
        )
        res = api.create_installment(
            payload, TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_INSTALLMENT_TERM.value)

    def test_downpayment_above_final_total_rejected(self, api):
        """PRD §3.7: "The downpayment_cents must lie within the
        inclusive range from 0 to TreatmentPlan.final_total_cents; an
        out-of-range downpayment is rejected with
        ERR_DOWNPAYMENT_OUT_OF_RANGE (HTTP 422)."

        Claim: downpayment > final_total_cents →
        ERR_DOWNPAYMENT_OUT_OF_RANGE.
        """
        bundle = setup_approved_plan_simple(base_price_cents=10000)
        plan = bundle["plan"]
        # final_total_cents = 10000 (no promo with 1 item).
        payload = create_installment_payload(
            treatment_plan_id=plan["id"],
            downpayment_cents=999999,
            term_months=6,
        )
        res = api.create_installment(
            payload, TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DOWNPAYMENT_OUT_OF_RANGE.value)

    def test_negative_downpayment_rejected(self, api):
        """PRD §3.7: "The downpayment_cents must lie within the
        inclusive range from 0 to TreatmentPlan.final_total_cents."

        Claim: downpayment_cents < 0 → ERR_DOWNPAYMENT_OUT_OF_RANGE.
        """
        bundle = setup_approved_plan_simple(base_price_cents=10000)
        payload = create_installment_payload(
            treatment_plan_id=bundle["plan"]["id"],
            downpayment_cents=-100,
            term_months=6,
        )
        res = api.create_installment(
            payload, TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_DOWNPAYMENT_OUT_OF_RANGE.value)

    def test_kyc_or_credit_fail_blocks_activation(self, api):
        """PRD §3.7: "the customer's credit_score to be at least the
        term-specific minimum: 500 for a 3-month term, 600 for 6
        months, 700 for 12 months, and 750 for 24 months. A failed
        KYC-or-credit gate is reported as ERR_KYC_OR_CREDIT_FAIL (HTTP
        422)."

        Claim: a 12-month installment with the customer's
        credit_score=699 (below the 700 minimum) → ERR_KYC_OR_CREDIT_FAIL.
        """
        bundle = setup_approved_plan_simple(base_price_cents=30000)
        # Override the customer's credit score to 699.
        verify_customer_kyc(
            bundle["customer"]["id"], credit_score=699,
        )
        inst = create_installment_plan(
            treatment_plan_id=bundle["plan"]["id"],
            downpayment_cents=0,
            term_months=12,
        )
        res = api.activate_installment(
            inst["id"], TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_KYC_OR_CREDIT_FAIL.value)


# ===========================================================================
# Exactly-one installment plan per treatment plan
# ===========================================================================
class TestInstallmentUniqueness:

    def test_second_installment_plan_on_same_treatment_plan_rejected(
        self, api,
    ):
        """PRD §3.7: "Exactly one InstallmentPlan exists per
        TreatmentPlan; a second creation racing on the same parent is
        rejected with ERR_INSTALLMENT_ALREADY_EXISTS (HTTP 409)."

        Claim: second POST /aesthetics/installments for the same
        treatment_plan_id → ERR_INSTALLMENT_ALREADY_EXISTS.
        """
        bundle = setup_approved_plan_simple(base_price_cents=30000)
        # First creation.
        create_installment_plan(
            treatment_plan_id=bundle["plan"]["id"],
            downpayment_cents=0,
            term_months=6,
        )
        # Second creation collides.
        payload = create_installment_payload(
            treatment_plan_id=bundle["plan"]["id"],
            downpayment_cents=0,
            term_months=6,
        )
        res = api.create_installment(
            payload, TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INSTALLMENT_ALREADY_EXISTS.value)


# ===========================================================================
# Payment amount validation
# ===========================================================================
class TestPaymentAmountValidation:

    def test_payment_amount_zero_rejected(self, api):
        """PRD §3.7: "The payment must be strictly greater than 0 and
        not exceed the remaining unpaid balance ... a payment outside
        this range is rejected with ERR_PAYMENT_AMOUNT_INVALID (HTTP
        422)."

        Claim: amount_cents == 0 → ERR_PAYMENT_AMOUNT_INVALID.
        """
        bundle = setup_active_installment(
            term_months=3, base_price_cents=30000, credit_score=600,
        )
        from test_helpers import installment_payment_payload
        # 0 is not allowed per "strictly greater than 0" — but the
        # schema layer may reject this as ERR_INVALID_INPUT. PRD §3.7
        # explicitly says ERR_PAYMENT_AMOUNT_INVALID, so we test that.
        payload = installment_payment_payload(
            amount_cents=0, external_ref="ref",
        )
        res = api.pay_installment(
            bundle["installment"]["id"], payload,
            TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value)

    def test_payment_exceeding_remaining_balance_rejected(self, api):
        """PRD §3.7: "The payment must be strictly greater than 0 and
        not exceed the remaining unpaid balance (the sum of
        total_cents for schedule entries whose status is not PAID); a
        payment outside this range is rejected with
        ERR_PAYMENT_AMOUNT_INVALID (HTTP 422)."

        Claim: amount_cents > remaining unpaid balance →
        ERR_PAYMENT_AMOUNT_INVALID.
        """
        bundle = setup_active_installment(
            term_months=3, base_price_cents=30000, credit_score=600,
        )
        inst = bundle["installment"]
        remaining = sum(
            int(e["total_cents"]) for e in inst["schedule"]
            if e.get("status") != "PAID"
        )
        from test_helpers import installment_payment_payload
        payload = installment_payment_payload(
            amount_cents=remaining + 1, external_ref="ref",
        )
        res = api.pay_installment(
            inst["id"], payload, TEST_USERS["finance_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID.value)


# ===========================================================================
# Activation requires APPROVED TreatmentPlan
# ===========================================================================
class TestActivationRequiresApprovedPlan:

    def test_installment_creates_on_approved_treatment_plan(self, api):
        """PRD §3.7: "An InstallmentPlan is created against an APPROVED
        TreatmentPlan."

        Claim: a brand-new installment plan opens in PENDING_KYC.
        """
        bundle = setup_approved_plan_simple(base_price_cents=10000)
        inst = create_installment_plan(
            treatment_plan_id=bundle["plan"]["id"],
            downpayment_cents=0, term_months=3,
        )
        assert_installment_plan(inst)
        assert inst["status"] == "PENDING_KYC"
        assert inst["paid_amount_cents"] == 0
        assert inst["default_strike_count"] == 0
