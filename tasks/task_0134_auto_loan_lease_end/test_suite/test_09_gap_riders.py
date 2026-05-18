"""Gap insurance riders — create, claim, cancel, ownership and
parent-contract cross-entity dependencies.

PRD §3.7 — rider lifecycle (ACTIVE → CANCELLED / CLAIMED), premium
calc, claim-not-exceeding-gap, parent-contract terminal rejection,
cross-customer ownership mismatch.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    GAP_PREMIUM_BPS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    cancel_gap_rider,
    claim_gap_rider,
    create_customer,
    create_gap_rider,
    create_vehicle,
    get_loan_contract,
    make_customer_headers,
    setup_active_lease,
    setup_active_loan,
    setup_loan_paid_off,
    validate_error,
)


# ===========================================================================
# Rider create — premium computation
# ===========================================================================
class TestRiderCreate:

    def test_loan_rider_monthly_premium_50_bps_of_principal(self, api):
        """PRD §3.7: "The rider's monthly_premium_cents is computed as
        the ceiling of the contract's financed amount multiplied by
        the gap premium of 50 basis points (0.50% per month), divided
        by 10000 — where the financed amount is the loan's
        principal_cents for LOAN-type riders and the lease's
        capitalized_cost_cents for LEASE-type riders."

        Claim: rider on LOAN -> monthly_premium_cents =
        ceil(principal_cents * 50 / 10000).
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        expected = math.ceil(
            loan["principal_cents"] * GAP_PREMIUM_BPS / 10000,
        )
        assert rider["monthly_premium_cents"] == expected
        assert rider["status"] == "ACTIVE"

    def test_lease_rider_monthly_premium_50_bps_of_cap_cost(self, api):
        """PRD §3.7: "The rider's monthly_premium_cents is computed
        as the ceiling of the contract's financed amount multiplied
        by the gap premium of 50 basis points (0.50% per month),
        divided by 10000 — where the financed amount is the loan's
        principal_cents for LOAN-type riders and the lease's
        capitalized_cost_cents for LEASE-type riders."

        Claim: rider on LEASE -> monthly_premium_cents =
        ceil(capitalized_cost_cents * 50 / 10000).
        """
        cust, _, lease = setup_active_lease(
            fico_score=700, msrp_cents=3_275_000,
            residual_factor_bps=5800, down_payment_cents=393_000,
            term_months=36, mileage_allowance=36_000,
        )
        rider = create_gap_rider(cust, lease, contract_type="LEASE")
        expected = math.ceil(
            lease["capitalized_cost_cents"] * GAP_PREMIUM_BPS / 10000,
        )
        assert rider["monthly_premium_cents"] == expected

    def test_rider_ownership_mismatch_rejected(self, api):
        """PRD §3.7: "A rider's contract_id must reference a contract
        owned by the same Customer whose id appears in the URL; a
        cross-customer reference is rejected with
        ERR_RIDER_CONTRACT_OWNERSHIP_MISMATCH, even if the contract
        id is otherwise a valid id elsewhere in the system."

        Claim: POSTing /customers/{B}/gap-riders with contract_id
        belonging to customer A -> ERR_RIDER_CONTRACT_OWNERSHIP_MISMATCH.
        """
        custA, _, loanA = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        custB = create_customer(fico_score=750)
        resp = api_client.create_gap_rider(
            custB["id"],
            {"contract_id": loanA["id"], "contract_type": "LOAN"},
            make_customer_headers(custB["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_RIDER_CONTRACT_OWNERSHIP_MISMATCH.value,
        )


# ===========================================================================
# Rider cancel
# ===========================================================================
class TestRiderCancel:

    def test_cancel_transitions_to_cancelled(self, api):
        """PRD §3.7: "A rider may be cancelled by the customer at any
        time while it is ACTIVE, transitioning to CANCELLED."

        Claim: POST /gap-riders/{id}/cancel from ACTIVE -> CANCELLED.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        rider_after = cancel_gap_rider(cust, rider)
        assert rider_after["status"] == "CANCELLED"

    def test_auto_cancel_on_loan_paid_off(self, api):
        """PRD §3.7: "A rider also auto-cancels when its parent
        contract reaches PAID_OFF (loan), CHARGED_OFF (loan), or
        CLOSED (lease)."

        Claim: paying a loan to PAID_OFF auto-CANCELs an ACTIVE rider.
        """
        # Originate, attach rider, then drive to PAID_OFF.
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        from test_helpers import pay_n_loan_payments
        loan_after = pay_n_loan_payments(cust, loan, 36)
        assert loan_after["status"] == "PAID_OFF"
        # Re-fetch rider.
        resp = api_client.get_gap_rider(
            cust["id"], rider["id"],
            TEST_USERS["finance_manager_headers"],
        )
        from test_helpers import validate_success
        rider_now = validate_success(resp)
        assert rider_now["status"] == "CANCELLED"


# ===========================================================================
# Rider claim — preconditions and cross-entity dependency
# ===========================================================================
class TestRiderClaim:

    def test_claim_succeeds_and_decrements_remaining_principal(self, api):
        """PRD §3.7: "When a claim succeeds, the rider transitions
        from ACTIVE to CLAIMED, and claim_payout_cents records the
        paid amount. For a loan, the contract's
        remaining_principal_cents is decremented by payout_cents".

        Claim: claim against an ACTIVE loan rider -> rider.CLAIMED
        and loan.remaining_principal_cents decremented by payout.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        rp_before = loan["remaining_principal_cents"]
        rider_after = claim_gap_rider(
            cust, rider, payout_cents=100_000,
        )
        assert rider_after["status"] == "CLAIMED"
        assert rider_after["claim_payout_cents"] == 100_000
        loan_after = get_loan_contract(cust, loan["id"])
        assert loan_after["remaining_principal_cents"] == (
            rp_before - 100_000
        )

    def test_claim_exceeds_gap_rejected(self, api):
        """PRD §3.7: "A claim whose payout_cents exceeds the relevant
        gap is rejected with ERR_GAP_CLAIM_EXCEEDS_GAP."

        Claim: payout > remaining_principal -> ERR_GAP_CLAIM_EXCEEDS_GAP.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        resp = api_client.claim_gap_rider(
            cust["id"], rider["id"],
            {"payout_cents": loan["remaining_principal_cents"] + 1},
            TEST_USERS["finance_manager_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_GAP_CLAIM_EXCEEDS_GAP.value,
        )

    def test_claim_against_paid_off_contract_rejected(self, api):
        """PRD §3.7: "A claim whose parent contract is CLOSED,
        PAID_OFF, or CHARGED_OFF is rejected with
        ERR_GAP_RIDER_PARENT_TERMINAL — the rider has auto-cancelled
        with the contract and cannot pay out posthumously."

        Claim: filing a claim against a rider whose parent loan is
        already PAID_OFF -> ERR_GAP_RIDER_PARENT_TERMINAL or
        ERR_GAP_RIDER_NOT_CLAIMABLE (PRD §1 difficulty notes both
        framings as valid).
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        # Drive loan to PAID_OFF; auto-cancels the rider.
        from test_helpers import pay_n_loan_payments
        loan_after = pay_n_loan_payments(cust, loan, 36)
        assert loan_after["status"] == "PAID_OFF"
        resp = api_client.claim_gap_rider(
            cust["id"], rider["id"], {"payout_cents": 50_000},
            TEST_USERS["finance_manager_headers"],
        )
        # PRD §3.7 names BOTH framings as the documented response
        # path. validate_error_is_one_of accepts either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_GAP_RIDER_PARENT_TERMINAL.value,
            ApiErrorId.ERR_GAP_RIDER_NOT_CLAIMABLE.value,
        ])

    def test_claim_on_cancelled_rider_rejected(self, api):
        """PRD §3.7: "A claim against a rider that is not ACTIVE is
        rejected with ERR_GAP_RIDER_NOT_CLAIMABLE."

        Claim: claim against a CANCELLED rider -> ERR_GAP_RIDER_NOT_CLAIMABLE.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        cancel_gap_rider(cust, rider)
        resp = api_client.claim_gap_rider(
            cust["id"], rider["id"], {"payout_cents": 1_000},
            TEST_USERS["finance_manager_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_GAP_RIDER_NOT_CLAIMABLE.value,
        )
