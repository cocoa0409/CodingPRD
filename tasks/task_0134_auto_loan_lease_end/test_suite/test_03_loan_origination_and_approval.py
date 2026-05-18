"""Loan origination, approval, activation, and the validations around
approve / activate.

PRD §3.3 — pricing, term constraints, FICO-tier APR & down-payment
minima, vehicle/customer preconditions.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    APR_UPLIFT_BPS,
    DAYS_PER_PERIOD,
    LOAN_TERM_MONTHS_ALLOWED,
    TIER_1_APR_BPS,
    TIER_2_APR_BPS,
    TIER_3_APR_BPS,
    TIER_4_APR_BPS,
    TIER_1_DP_BPS_LOAN,
    TIER_2_DP_BPS_LOAN,
    TIER_3_DP_BPS_LOAN,
    TIER_4_DP_BPS_LOAN,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    approve_loan_contract,
    create_approve_activate_loan,
    create_customer,
    create_loan_contract,
    create_vehicle,
    get_loan_contract,
    list_payments_full,
    suspend_customer,
    validate_error,
)


# Helper — expected monthly payment (PRD §3.3 amortization formula).
def _expected_monthly_payment(principal: int, apr_bps: int,
                              term_months: int) -> int:
    r = (apr_bps / 10000) / 12
    if r == 0:
        return math.ceil(principal / term_months)
    factor = (1 + r) ** term_months
    raw = principal * r * factor / (factor - 1)
    return math.ceil(raw)


# ===========================================================================
# Creation — happy + invalid term_months
# ===========================================================================
class TestLoanCreate:

    def test_create_loan_pending_approval(self, api):
        """PRD §3.3: "the contract enters PENDING_APPROVAL." and
        "principal_cents is derived as the vehicle's msrp_cents minus
        the down_payment_cents provided in the body".

        Claim: POST loan-contracts -> status PENDING_APPROVAL,
        principal_cents = msrp - down_payment.
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=150_000, term_months=36,
        )
        assert loan["status"] == "PENDING_APPROVAL"
        assert loan["principal_cents"] == 3_000_000 - 150_000

    @pytest.mark.parametrize("bad_term", [1, 12, 24, 35, 37, 48 + 1, 100, 0])
    def test_invalid_term_months_rejected(self, api, bad_term):
        """PRD §3.3: "The term_months value must be one of the four
        supported terms — 36, 48, 60, or 72 months — and a request
        that names any other value is rejected with ERR_INVALID_REQUEST."

        Claim: term_months outside {36,48,60,72} -> ERR_INVALID_REQUEST.
        """
        if bad_term in LOAN_TERM_MONTHS_ALLOWED:
            pytest.skip("term is actually valid")
        cust = create_customer(fico_score=750)
        veh = create_vehicle()
        resp = api_client.create_loan_contract(
            cust["id"],
            {"vehicle_id": veh["id"],
             "down_payment_cents": 200_000,
             "term_months": bad_term},
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Approval — preconditions
# ===========================================================================
class TestLoanApproval:

    def test_approve_suspended_customer_rejected(self, api):
        """PRD §3.3: "the parent customer's status is ACTIVE (a
        suspended customer cannot be approved, and the rejection is
        ERR_CUSTOMER_NOT_ACTIVE)".

        Claim: approve a loan whose customer was suspended ->
        ERR_CUSTOMER_NOT_ACTIVE.
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle()
        loan = create_loan_contract(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        suspend_customer(cust)
        resp = api_client.approve_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_ACTIVE.value)

    def test_approve_declined_tier_rejected(self, api):
        """PRD §3.3: "the customer's fico_tier is not TIER_5_DECLINED
        (a declined applicant cannot take a loan, and the rejection is
        ERR_LOAN_TIER_DECLINED)".

        Claim: customer with fico_score 500 (TIER_5_DECLINED) ->
        approve -> ERR_LOAN_TIER_DECLINED.
        """
        cust = create_customer(fico_score=500)
        veh = create_vehicle(msrp_cents=2_000_000)
        # Generous down payment so the down-payment check would pass
        # if it were ever reached; the declined-tier check must win
        # because PRD §3.3 names it before the down-payment check.
        loan = create_loan_contract(
            cust, veh, down_payment_cents=1_500_000, term_months=36,
        )
        resp = api_client.approve_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOAN_TIER_DECLINED.value)

    @pytest.mark.parametrize("fico,bps", [
        (750, TIER_1_DP_BPS_LOAN),
        (700, TIER_2_DP_BPS_LOAN),
        (620, TIER_3_DP_BPS_LOAN),
        (560, TIER_4_DP_BPS_LOAN),
    ])
    def test_down_payment_below_minimum_rejected(self, api, fico, bps):
        """PRD §3.3: "The minimum down payment for a loan is a tiered
        fraction of the vehicle's msrp_cents. For TIER_1 it is 5% (500
        basis points), for TIER_2 it is 10% (1000 basis points), for
        TIER_3 it is 20% (2000 basis points), and for TIER_4 it is 35%
        (3500 basis points)." and "approval requires the supplied
        down_payment_cents to be at least that minimum."

        Claim: a down_payment one cent below the FICO-tier minimum ->
        ERR_DOWN_PAYMENT_BELOW_MINIMUM.
        """
        msrp = 3_000_000
        cust = create_customer(fico_score=fico)
        veh = create_vehicle(msrp_cents=msrp)
        min_dp = math.ceil(msrp * bps / 10000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=min_dp - 1, term_months=36,
        )
        resp = api_client.approve_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_DOWN_PAYMENT_BELOW_MINIMUM.value,
        )

    def test_approve_unavailable_vehicle_rejected(self, api):
        """PRD §3.3: "the vehicle's status is still AVAILABLE
        (otherwise ERR_VEHICLE_NOT_AVAILABLE)."

        Claim: a vehicle already SOLD via a prior loan approval -> a
        new loan approval against it -> ERR_VEHICLE_NOT_AVAILABLE.
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        # First approval takes the vehicle.
        create_approve_activate_loan(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        # Second loan on the same vehicle.
        cust2 = create_customer(fico_score=750)
        loan2 = create_loan_contract(
            cust2, veh, down_payment_cents=200_000, term_months=36,
        )
        resp = api_client.approve_loan_contract(
            cust2["id"], loan2["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_VEHICLE_NOT_AVAILABLE.value,
        )

    @pytest.mark.parametrize("fico,apr_bps", [
        (750, TIER_1_APR_BPS),
        (700, TIER_2_APR_BPS),
        (620, TIER_3_APR_BPS),
        (560, TIER_4_APR_BPS),
    ])
    def test_apr_bps_set_from_fico_tier(self, api, fico, apr_bps):
        """PRD §3.3: "TIER_1 carries an APR of 450 basis points
        (4.50%), TIER_2 carries 650 (6.50%), TIER_3 carries 950
        (9.50%), and TIER_4 carries 1450 (14.50%). The chosen rate
        becomes both base_apr_bps (which is immutable after APPROVED)
        and the initial apr_bps".

        Claim: approving a loan sets apr_bps == base_apr_bps == tier APR.
        """
        msrp = 3_000_000
        cust = create_customer(fico_score=fico)
        veh = create_vehicle(msrp_cents=msrp)
        # Compute a down payment that satisfies every tier's minimum
        # (50% of msrp is well above 35% TIER_4 max).
        loan = create_loan_contract(
            cust, veh, down_payment_cents=msrp // 2, term_months=36,
        )
        approved = approve_loan_contract(cust, loan)
        assert approved["apr_bps"] == apr_bps
        assert approved["base_apr_bps"] == apr_bps

    def test_approve_sets_status_and_origination_day(self, api):
        """PRD §3.3: "The vehicle is then transitioned to SOLD, the
        loan's base_apr_bps and apr_bps are set from the FICO-tier
        rate table, the monthly_payment_cents is computed via the
        standard amortization formula described below,
        remaining_principal_cents is initialized to principal_cents,
        payments_scheduled_count is set equal to term_months, and the
        loan's origination_day_index captures the customer's current
        clock_day_index."

        Claim: post-approval loan.origination_day_index ==
        customer.clock_day_index at the moment of the call.
        """
        cust = create_customer(fico_score=750)
        # Advance the clock so origination is non-zero (proving the
        # field tracks the per-customer clock).
        advance_clock(cust, 10)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        approved = approve_loan_contract(cust, loan)
        assert approved["status"] == "APPROVED"
        assert approved["origination_day_index"] == 10
        # PRD §3.3: "payments_scheduled_count is set equal to
        # term_months".
        assert approved["payments_scheduled_count"] == 36

    def test_double_approve_rejected_with_state_error(self, api):
        """PRD §3.3: "Any approve attempt against a loan that is not
        in PENDING_APPROVAL is rejected with ... ERR_LOAN_NOT_PENDING_APPROVAL".

        Claim: approving an already-APPROVED loan -> ERR_LOAN_NOT_PENDING_APPROVAL.
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        approve_loan_contract(cust, loan)
        resp = api_client.approve_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_LOAN_NOT_PENDING_APPROVAL.value,
        )


# ===========================================================================
# Activation — schedule generation
# ===========================================================================
class TestLoanActivation:

    def test_activate_creates_term_months_payments(self, api):
        """PRD §3.3: "Activation is the step that materializes the
        payment schedule: the system generates term_months child
        Payment rows with period_index running from 1 to term_months,
        each row's due_day_index set to the loan's
        origination_day_index plus period_index multiplied by 30."

        Claim: after activate, the customer has term_months SCHEDULED
        Payment rows with monotonically-increasing due_day_index in
        steps of 30, and amount_due_cents snapshotted from
        monthly_payment_cents.
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_approve_activate_loan(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        # Refresh loan to grab monthly_payment_cents.
        loan = get_loan_contract(cust, loan["id"])
        payments = list_payments_full(cust, contract_id=loan["id"])
        assert len(payments) == 36
        # period_index 1..36, ordered by created_at ASC implies same
        # numeric order; tolerate any ordering by sorting first.
        payments.sort(key=lambda p: p["period_index"])
        for i, p in enumerate(payments, start=1):
            assert p["period_index"] == i
            assert p["status"] == "SCHEDULED"
            assert p["contract_type"] == "LOAN"
            assert p["due_day_index"] == (
                loan["origination_day_index"] + i * DAYS_PER_PERIOD
            )
            assert p["amount_due_cents"] == loan["monthly_payment_cents"]

    def test_activate_non_approved_rejected(self, api):
        """PRD §3.3: "An activate attempt against any contract — loan
        or lease — that is not currently in APPROVED is rejected with
        ERR_CONTRACT_NOT_ACTIVATABLE."

        Claim: activating a PENDING_APPROVAL loan -> ERR_CONTRACT_NOT_ACTIVATABLE.
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=200_000, term_months=36,
        )
        # No approve.
        resp = api_client.activate_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVATABLE.value,
        )


# ===========================================================================
# Monthly payment formula — numeric correctness
# ===========================================================================
class TestLoanMonthlyPaymentFormula:

    def test_monthly_payment_three_input_amortization(self, api):
        """PRD §3.3: "Otherwise, the monthly payment is the ceiling of
        P multiplied by r multiplied by one-plus-r-raised-to-the-n,
        divided by one-plus-r-raised-to-the-n-minus-one. The
        intermediate floating-point monthly payment is computed first
        without rounding any of r or P early, and only the final
        dollar amount is rounded up to integer cents."

        Claim: TIER_1 (apr=450bps), 36-month, principal=2_850_000 ->
        monthly_payment_cents == ceil unrounded amortization (84779).
        """
        cust = create_customer(fico_score=750)
        veh = create_vehicle(msrp_cents=3_000_000)
        loan = create_loan_contract(
            cust, veh, down_payment_cents=150_000, term_months=36,
        )
        approved = approve_loan_contract(cust, loan)
        expected = _expected_monthly_payment(
            principal=2_850_000,
            apr_bps=TIER_1_APR_BPS, term_months=36,
        )
        assert approved["monthly_payment_cents"] == expected
        assert approved["monthly_payment_cents"] == 84779
