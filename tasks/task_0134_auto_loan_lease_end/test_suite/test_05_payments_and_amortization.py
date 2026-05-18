"""Payment lifecycle, amortization step, and contract-side counters.

PRD §3.5 — pay transitions (SCHEDULED→PAID, LATE→PAID, DEFAULTED→PAID),
amortization side effects, payments_made_count, principal/interest
portion splits, payment-not-payable rejections.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    DAYS_PER_PERIOD,
    NON_EXISTENT_UUID,
    TIER_1_APR_BPS,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_customer,
    create_vehicle,
    get_loan_contract,
    list_payments_full,
    make_customer_headers,
    pay_n_loan_payments,
    pay_next_unpaid_payment,
    pay_payment,
    setup_active_loan,
    setup_loan_paid_off,
    validate_error,
    validate_success,
)


# ===========================================================================
# Pay — happy path: SCHEDULED → PAID with amortization side effects
# ===========================================================================
class TestPaySchedule:

    def test_pay_first_payment_updates_payment_and_loan(self, api):
        """PRD §3.5: "The customer pays a scheduled payment to
        transition it to PAID; the precondition is that the payment is
        currently SCHEDULED and that the parent contract is ACTIVE or
        DEFAULTED ... On the successful transition, paid_day_index is
        set to the customer's current clock_day_index, and for a
        LOAN-type payment the amortization step ... splits the
        amount_due_cents into principal_portion_cents and
        interest_portion_cents, decrements the loan's
        remaining_principal_cents, and increments
        total_principal_paid_cents and total_interest_paid_cents. The
        parent contract's payments_made_count is incremented in the
        same transaction."

        Claim: paying the first SCHEDULED payment of a TIER_1 loan
        transitions status to PAID, sets paid_day_index, and
        decrements remaining_principal by the principal portion.
        """
        cust, _veh, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        # Advance one period so the payment is due (but still
        # SCHEDULED at the moment of pay — PRD allows pay from
        # SCHEDULED as long as the contract is ACTIVE).
        advance_clock(cust, DAYS_PER_PERIOD)
        # Find the period_index 1 payment.
        payments = list_payments_full(cust, contract_id=loan["id"])
        payments.sort(key=lambda p: p["period_index"])
        p1 = payments[0]
        # Recompute the expected amortization split.
        r = (TIER_1_APR_BPS / 10000) / 12
        expected_interest = math.floor(loan["remaining_principal_cents"] * r)
        expected_principal = p1["amount_due_cents"] - expected_interest
        # Pay it.
        paid = pay_payment(cust, p1)
        assert paid["status"] == "PAID"
        assert paid["paid_day_index"] == DAYS_PER_PERIOD
        assert paid["principal_portion_cents"] == expected_principal
        assert paid["interest_portion_cents"] == expected_interest
        # Re-fetch loan and check counters.
        loan_after = get_loan_contract(cust, loan["id"])
        assert loan_after["payments_made_count"] == 1
        assert loan_after["remaining_principal_cents"] == (
            loan["remaining_principal_cents"] - expected_principal
        )
        assert loan_after["total_principal_paid_cents"] == expected_principal
        assert loan_after["total_interest_paid_cents"] == expected_interest


# ===========================================================================
# Pay — wrong-actor rejection (Customer ownership)
# ===========================================================================
class TestPayOwnership:

    def test_customer_cannot_pay_other_customers_payment(self, api):
        """PRD §2.1: "a Customer calling pay on a payment whose parent
        contract's customer_id does not equal X-User-ID is treated as
        an unauthorized actor and rejected."

        Claim: Customer B trying to pay Customer A's payment is
        rejected. (PRD frames this as a not-found-style isolation; the
        rejection MUST not be a successful 2xx.)
        """
        custA, _, loanA = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        advance_clock(custA, DAYS_PER_PERIOD)
        payments = list_payments_full(custA, contract_id=loanA["id"])
        payments.sort(key=lambda p: p["period_index"])
        p1 = payments[0]
        # A different customer's identity tries the call.
        custB = create_customer(fico_score=750)
        resp = api_client.pay_payment(
            custA["id"], p1["id"], make_customer_headers(custB["id"]),
        )
        # PRD §2.1 frames cross-actor as "unauthorized actor and
        # rejected" — either ERR_FORBIDDEN_ROLE or a NotFound under
        # PRD §2.5's "Cross-customer leakage ... is reported as a
        # not-found on the inner resource". A faithful implementer
        # could ship either framing, so we accept both 4xx outcomes.
        assert resp.status_code >= 400, (
            f"cross-customer pay must be rejected, got "
            f"{resp.status_code}"
        )


# ===========================================================================
# Pay — wrong-state rejections
# ===========================================================================
class TestPayWrongState:

    def test_pay_already_paid_rejected(self, api):
        """PRD §3.5: "Two concurrent pay attempts on the same payment
        serialize on Payment.status: at most one of the transitions
        from SCHEDULED, LATE, or DEFAULTED to PAID succeeds, and the
        loser is rejected with ERR_PAYMENT_NOT_PAYABLE."

        Claim: paying the same payment twice -> ERR_PAYMENT_NOT_PAYABLE
        on the second call.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        advance_clock(cust, DAYS_PER_PERIOD)
        payments = list_payments_full(cust, contract_id=loan["id"])
        payments.sort(key=lambda p: p["period_index"])
        p1 = payments[0]
        pay_payment(cust, p1)
        # Second attempt by the same actor.
        resp = api_client.pay_payment(
            cust["id"], p1["id"], make_customer_headers(cust["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_PAYABLE.value)

    def test_pay_against_charged_off_rejected(self, api):
        """PRD §3.6: "Any attempt to pay a payment against a CHARGED_OFF
        contract is rejected with ERR_PAYMENT_NOT_PAYABLE."

        Claim: paying a payment on a CHARGED_OFF loan ->
        ERR_PAYMENT_NOT_PAYABLE.
        """
        # Drive a loan to DEFAULTED then CHARGED_OFF.
        from test_helpers import (
            setup_loan_defaulted_via_clock,
        )
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        # Charge it off.
        resp = api_client.charge_off_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        validate_success(resp)
        # Find a non-PAID payment row to try.
        rows = list_payments_full(cust, contract_id=loan["id"])
        candidates = [p for p in rows if p["status"] != "PAID"]
        assert candidates, "Setup failed: no non-PAID rows left"
        target = candidates[0]
        resp = api_client.pay_payment(
            cust["id"], target["id"],
            make_customer_headers(cust["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_PAYABLE.value)


# ===========================================================================
# Cascade to PAID_OFF — final payment closes the loan
# ===========================================================================
class TestCascadeToPaidOff:

    def test_final_payment_drives_loan_to_paid_off(self, api):
        """PRD §3.5: "When the final scheduled payment of a loan
        reaches PAID and the contract's remaining_principal_cents
        reaches 0, the loan auto-transitions from ACTIVE to PAID_OFF."

        Claim: after paying all term_months payments, the loan's
        status is PAID_OFF and remaining_principal_cents is 0.
        """
        # Use a short loan to keep the test fast.
        cust, _veh, loan = setup_loan_paid_off(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        assert loan["status"] == "PAID_OFF"
        assert loan["remaining_principal_cents"] == 0
        # PRD §3.5: "the system uses the forward-looking re-pricing
        # convention from §2.10". Final-payment trueing: principal
        # conservation.
        assert loan["total_principal_paid_cents"] == loan["principal_cents"]


# ===========================================================================
# 404 paths under valid customer
# ===========================================================================
class TestPaymentNotFound:

    def test_get_unknown_payment_returns_payment_not_found(self, api):
        """PRD §2.5: "The same principle applies to lease contracts
        and loan contracts (ERR_CONTRACT_NOT_FOUND), to lease-end
        assessments (ERR_ASSESSMENT_NOT_FOUND), to gap riders
        (ERR_RIDER_NOT_FOUND), and to vehicles when looked up directly
        (ERR_VEHICLE_NOT_FOUND)."

        Claim: GET payment with valid customer + unknown payment_id ->
        ERR_PAYMENT_NOT_FOUND.
        """
        cust = create_customer()
        resp = api_client.get_payment(
            cust["id"], NON_EXISTENT_UUID,
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_FOUND.value)
