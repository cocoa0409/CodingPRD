"""Distribution lifecycle: propose / approve / execute / reject —
PRD §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_beneficiary,
    advance_clock_to,
    approve_distribution,
    assert_distribution,
    begin_close_tax_year,
    book_transaction,
    create_distribution_payload,
    execute_distribution,
    iso_instant_utc,
    propose_distribution,
    re_get_trust,
    setup_active_trust,
    setup_active_trust_with_approved_income_distribution,
    setup_active_trust_with_income,
    setup_active_trust_with_principal,
    setup_active_trust_with_proposed_income_distribution,
    setup_closed_tax_year,
    validate_error,
    validate_success,
)


# ===========================================================================
# Propose — PRD §3.4
# ===========================================================================
class TestDistributionPropose:

    def test_proposal_starts_in_proposed(self, api):
        """PRD §3.4: "The new Distribution starts in PROPOSED status;
        its trust_id is system-populated, its tax_year_id is resolved
        from scheduled_date, its proposed_by_user_id is pinned to the
        proposer's X-User-ID, and approved_by_user_id is null."

        Claim: returned distribution has status PROPOSED,
        proposed_by_user_id matches caller, approved_by_user_id null.
        """
        scenario = setup_active_trust_with_income(income_amount=5000.00)
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_income=1000.00,
        )
        assert_distribution(dist)
        assert dist["status"] == "PROPOSED"
        assert dist["proposed_by_user_id"] == (
            scenario.primary_trustee_headers["X-User-ID"]
        )
        assert dist.get("approved_by_user_id") in (None, "")

    def test_proposal_blocked_when_year_not_open(self, api):
        """PRD §3.4: "The scheduled_date must fall inside an OPEN
        TaxYear for this trust; otherwise the proposal is rejected
        with ERR_TAX_YEAR_CLOSED."

        Claim: scheduled_date for a year with no OPEN TaxYear ->
        ERR_TAX_YEAR_CLOSED.
        """
        scenario = setup_active_trust(calendar_year=2026)
        resp = api.create_distribution(
            scenario.trust["id"],
            create_distribution_payload(
                beneficiary_id=scenario.beneficiary["id"],
                scheduled_date=iso_instant_utc(2099, 1, 15),
                amount_income=10.00,
                distribution_type="DISCRETIONARY",
            ),
            scenario.primary_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TAX_YEAR_CLOSED.value)


# ===========================================================================
# Approve — PRD §3.4
# ===========================================================================
class TestDistributionApprove:

    def test_approve_pins_approved_by_user_id_and_status(self, api):
        """PRD §3.4: "When all preconditions hold, the Distribution
        transitions PROPOSED → APPROVED; approved_by_user_id is
        pinned to the acting trustee".

        Claim: approved distribution has status APPROVED with
        approved_by_user_id set to the approver.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=1_000.00,
                proposer="primary_trustee",
            )
        )
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        approved = validate_success(resp, 200)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == (
            scenario.second_trustee_headers["X-User-ID"]
        )

    def test_self_approval_rejected(self, api):
        """PRD §3.4: "The approving trustee's X-User-ID must differ
        from the Distribution's proposed_by_user_id; if they match,
        approval is rejected with ERR_SEGREGATION_OF_DUTIES."

        Claim: same user_id as proposer trying to approve ->
        ERR_SEGREGATION_OF_DUTIES.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        # Primary trustee tries to approve their own proposal.
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.primary_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

    def test_approve_requires_trust_active(self, api):
        """PRD §3.4: "Approval requires that the parent Trust is in
        ACTIVE status (otherwise ERR_TRUST_NOT_ACTIVE)".

        Claim: approve on a REVOKED trust's distribution ->
        ERR_TRUST_NOT_ACTIVE.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                trust_type="REVOCABLE",
                grantor_tax_status="GRANTOR",
                proposer="primary_trustee",
            )
        )
        # Revoke the trust.
        api.revoke_trust(
            scenario.trust["id"], scenario.grantor_headers,
        )
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TRUST_NOT_ACTIVE.value)

    def test_approve_blocked_when_beneficiary_terminated(self, api):
        """PRD §3.4: "Approval requires that ... the referenced
        Beneficiary is in ACTIVE status (otherwise
        ERR_BENEFICIARY_TERMINATED)".

        Claim: terminate the beneficiary after proposal, then approve
        -> ERR_BENEFICIARY_TERMINATED.

        PRD §3.2 forbids terminating a beneficiary while any
        Distribution referencing them is in PROPOSED or APPROVED
        status (ERR_HAS_PENDING_DISTRIBUTIONS). The fixture creates
        such a PROPOSED distribution; reject it first so termination
        can proceed, then re-propose against the (about-to-be)
        TERMINATED beneficiary, then approve to surface the §3.4
        check.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        # Step 1: reject the fixture's PROPOSED distribution so it no
        # longer blocks beneficiary termination (PRD §3.2 + §3.4 reject
        # path for PROPOSED).
        reject_resp = api.reject_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_success(reject_resp, 200)
        # Step 2: terminate the beneficiary (now no pending distributions).
        term_resp = api.terminate_beneficiary(
            scenario.trust["id"], scenario.beneficiary["id"],
            scenario.primary_trustee_headers,
        )
        validate_success(term_resp, 200)
        # Step 3: propose a new distribution to the TERMINATED beneficiary
        # (PRD §3.4 does not check beneficiary status at PROPOSE time —
        # only at APPROVE time).
        propose_resp = api.create_distribution(
            scenario.trust["id"],
            create_distribution_payload(
                beneficiary_id=scenario.beneficiary["id"],
                amount_principal=0.00,
                amount_income=500.00,
                distribution_type="DISCRETIONARY",
            ),
            scenario.primary_trustee_headers,
        )
        new_dist = validate_success(propose_resp, 201)
        # Step 4: approve must now surface ERR_BENEFICIARY_TERMINATED.
        resp = api.approve_distribution(
            scenario.trust["id"], new_dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_BENEFICIARY_TERMINATED.value,
        )

    def test_approve_blocked_when_insufficient_income(self, api):
        """PRD §3.4: "the amount_income must be at most the Trust's
        current income_balance (otherwise ERR_INSUFFICIENT_INCOME)".

        Claim: approve with amount_income > income_balance ->
        ERR_INSUFFICIENT_INCOME.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=100.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_INCOME.value,
        )

    def test_approve_blocked_when_insufficient_principal(self, api):
        """PRD §3.4: "The amount_principal must be at most the Trust's
        current principal_balance (otherwise
        ERR_INSUFFICIENT_PRINCIPAL)".

        Claim: approve with amount_principal > principal_balance ->
        ERR_INSUFFICIENT_PRINCIPAL.
        """
        scenario = setup_active_trust_with_principal(
            principal_amount=10.00,
        )
        # Propose a distribution that exceeds principal_balance.
        dist = propose_distribution(
            scenario.trust, scenario.beneficiary,
            scenario.primary_trustee_headers,
            amount_principal=100.00,
            distribution_type="DISCRETIONARY",
        )
        resp = api.approve_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_PRINCIPAL.value,
        )


# ===========================================================================
# Execute — PRD §3.4
# ===========================================================================
class TestDistributionExecute:

    def test_execute_transitions_to_executed_and_debits_balance(
        self, api,
    ):
        """PRD §3.4: "On success the Distribution transitions
        APPROVED → EXECUTED and four cascade effects fire: the
        Trust's principal_balance is reduced by amount_principal; its
        income_balance is reduced by amount_income".

        Claim: executing an APPROVED distribution moves status to
        EXECUTED and debits Trust.income_balance by amount_income.
        """
        scenario, dist = (
            setup_active_trust_with_approved_income_distribution(
                income_amount=5_000.00, distribution_income=1_500.00,
            )
        )
        before_income = re_get_trust(scenario.trust["id"])[
            "income_balance"
        ]
        resp = api.execute_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        ex = validate_success(resp, 200)
        assert ex["status"] == "EXECUTED"
        trust_after = re_get_trust(scenario.trust["id"])
        assert trust_after["income_balance"] == pytest.approx(
            before_income - 1_500.00, abs=0.01,
        )

    def test_execute_rejected_when_not_approved(self, api):
        """PRD §3.4: "A Trustee executes an APPROVED Distribution."
        PRD §2.8: "State-machine acceptability comes sixth, producing
        ERR_INVALID_STATE when the target resource is not in a state
        from which the requested action is allowed."

        Claim: execute on a PROPOSED distribution -> ERR_INVALID_STATE.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        resp = api.execute_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Reject — PRD §3.4
# ===========================================================================
class TestDistributionReject:

    def test_reject_proposed_succeeds(self, api):
        """PRD §3.4: "A Trustee may reject a Distribution that is in
        PROPOSED status, which transitions it PROPOSED → REJECTED".

        Claim: reject on PROPOSED moves status to REJECTED.
        """
        scenario, dist = (
            setup_active_trust_with_proposed_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
                proposer="primary_trustee",
            )
        )
        resp = api.reject_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        rejected = validate_success(resp, 200)
        assert rejected["status"] == "REJECTED"

    def test_reject_approved_by_same_trustee_rejected(self, api):
        """PRD §3.4: "in this second case the rejecting trustee's
        X-User-ID must differ from approved_by_user_id ... a
        same-trustee approve-then-reject is rejected with
        ERR_SEGREGATION_OF_DUTIES."

        Claim: same trustee tries to reject the distribution they
        approved -> ERR_SEGREGATION_OF_DUTIES.
        """
        scenario, dist = (
            setup_active_trust_with_approved_income_distribution(
                income_amount=5_000.00, distribution_income=500.00,
            )
        )
        # second_trustee approved; have second_trustee try to reject.
        resp = api.reject_distribution(
            scenario.trust["id"], dist["id"],
            scenario.second_trustee_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
