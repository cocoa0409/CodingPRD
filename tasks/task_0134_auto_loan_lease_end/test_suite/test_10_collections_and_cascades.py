"""Collections workflows: reinstate and charge-off, and the
cross-entity side-effect of charge-off on linked riders.

PRD §3.6 — DEFAULTED → ACTIVE reinstate (requires all DEFAULTED
payments paid first), DEFAULTED → CHARGED_OFF (terminal), apr_bps
uplift retained on reinstate.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    APR_UPLIFT_BPS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_customer,
    create_gap_rider,
    get_loan_contract,
    list_payments_full,
    pay_payment,
    setup_active_loan,
    setup_loan_defaulted_via_clock,
    validate_error,
    validate_success,
)


# ===========================================================================
# Reinstate — requires all DEFAULTED payments paid
# ===========================================================================
class TestReinstate:

    def test_reinstate_with_outstanding_defaults_rejected(self, api):
        """PRD §3.6: "a DEFAULTED loan may be returned to ACTIVE only
        after every one of its DEFAULTED child Payment rows has been
        paid (transitioned to PAID). If any DEFAULTED payment remains
        unpaid on the contract, reinstatement is rejected with
        ERR_REINSTATE_HAS_OUTSTANDING_DEFAULTS."

        Claim: calling reinstate while at least one DEFAULTED payment
        remains unpaid -> ERR_REINSTATE_HAS_OUTSTANDING_DEFAULTS.
        """
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        assert loan["status"] == "DEFAULTED"
        resp = api_client.reinstate_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        validate_error(
            resp,
            ApiErrorId.ERR_REINSTATE_HAS_OUTSTANDING_DEFAULTS.value,
        )

    def test_reinstate_after_paying_all_defaults_restores_active(self, api):
        """PRD §3.6: "When reinstatement succeeds, the loan returns to
        ACTIVE; the APR uplift applied during the original default
        cascade is retained — the apr_bps is not reset to base_apr_bps,
        consistent with the forward-looking convention."

        Claim: pay every DEFAULTED payment, then reinstate ->
        status=ACTIVE; apr_bps unchanged from the uplifted value.
        """
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        uplifted_apr = loan["apr_bps"]
        assert uplifted_apr == loan["base_apr_bps"] + APR_UPLIFT_BPS
        # Pay every DEFAULTED payment row.
        rows = list_payments_full(cust, contract_id=loan["id"])
        defaulted = [p for p in rows if p["status"] == "DEFAULTED"]
        for p in sorted(defaulted, key=lambda x: x["period_index"]):
            pay_payment(cust, p)
        # Now reinstate.
        resp = api_client.reinstate_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        re = validate_success(resp)
        assert re["status"] == "ACTIVE"
        assert re["apr_bps"] == uplifted_apr, (
            "apr_bps must be retained (not reset to base_apr_bps) on "
            "reinstate per PRD §3.6 forward-looking convention"
        )

    def test_reinstate_non_defaulted_loan_rejected(self, api):
        """PRD §3.6: "A loan that is neither DEFAULTED nor in any
        prior state expected by these endpoints — for example, a
        PENDING_APPROVAL loan submitted for reinstatement — is
        rejected with ERR_LOAN_NOT_DEFAULTED."

        Claim: reinstate on ACTIVE -> ERR_LOAN_NOT_DEFAULTED.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        resp = api_client.reinstate_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_LOAN_NOT_DEFAULTED.value,
        )


# ===========================================================================
# Charge-off — terminal transition
# ===========================================================================
class TestChargeOff:

    def test_charge_off_transitions_defaulted_to_charged_off(self, api):
        """PRD §3.6: "A DEFAULTED loan may be charged off,
        transitioning to CHARGED_OFF."

        Claim: charge-off on DEFAULTED -> CHARGED_OFF.
        """
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        resp = api_client.charge_off_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        co = validate_success(resp)
        assert co["status"] == "CHARGED_OFF"

    def test_charge_off_cascades_to_active_gap_rider(self, api):
        """PRD §3.6: "On charge-off, any linked ACTIVE
        GapInsuranceRider is auto-transitioned to CANCELLED".

        Claim: charging off a DEFAULTED loan with an ACTIVE rider
        flips rider.status to CANCELLED.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        rider = create_gap_rider(cust, loan, contract_type="LOAN")
        # Drive to DEFAULTED.
        from test_helpers import advance_clock
        advance_clock(cust, 180)
        loan_now = get_loan_contract(cust, loan["id"])
        assert loan_now["status"] == "DEFAULTED"
        # Charge off.
        resp = api_client.charge_off_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        validate_success(resp)
        # Re-fetch rider.
        resp = api_client.get_gap_rider(
            cust["id"], rider["id"],
            TEST_USERS["finance_manager_headers"],
        )
        rider_now = validate_success(resp)
        assert rider_now["status"] == "CANCELLED"

    def test_charge_off_non_defaulted_rejected(self, api):
        """PRD §3.6: "A loan that is neither DEFAULTED nor in any
        prior state expected by these endpoints ... is rejected with
        ERR_LOAN_NOT_DEFAULTED."

        Claim: charge-off on ACTIVE -> ERR_LOAN_NOT_DEFAULTED.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        resp = api_client.charge_off_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["collections_agent_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_LOAN_NOT_DEFAULTED.value,
        )

    def test_loan_officer_cannot_reinstate_or_charge_off(self, api):
        """PRD §4 / §2.1: reinstate and charge-off are CollectionsAgent
        exclusive operations.

        Claim: LoanOfficer calling charge-off -> ERR_FORBIDDEN_ROLE.
        """
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        resp = api_client.charge_off_loan_contract(
            cust["id"], loan["id"],
            TEST_USERS["loan_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
