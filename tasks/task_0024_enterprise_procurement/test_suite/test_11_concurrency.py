"""Concurrency and race-loser error contracts (PRD §2.9, §3.5, §3.6, §3.10)."""
from __future__ import annotations
import pytest

from prd_bench_local_runner.testing import (
    assert_exactly_one_succeeds,
    assert_race_outcome,
    run_race,
    validate_error_is_one_of,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    apply_payment_payload,
    award_payload,
    create_clause_template,
    create_contract_payload,
    setup_approved_po,
    setup_awarded_po,
    setup_payment_applied,
    setup_shortlisted_requirement,
    sign_contract_payload,
    stage_actor,
    validate_error,
    validate_success,
)


# ===========================================================================
# Two awards on same requirement (PRD §2.9, §3.5)
# ===========================================================================
class TestAwardRace:
    def test_two_awards_same_requirement_one_wins(self, api):
        """PRD §2.9: "When two buyers attempt to award the same requirement
        at the same instant, first-writer-wins on the requirement's
        status flip from IN_SOURCING to AWARDED and at most one purchase
        order is created; the loser receives ERR_REQUIREMENT_ALREADY_AWARDED
        (HTTP 409)."

        Claim: in a concurrent /award race, exactly one succeeds and the
        loser receives ERR_REQUIREMENT_ALREADY_AWARDED.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        req_id = setup["requirement"]["id"]
        payload_a = award_payload(awarded_quote_id=setup["quotes"][0]["id"])
        payload_b = award_payload(awarded_quote_id=setup["quotes"][1]["id"])

        results = run_race(
            lambda: api.award_requirement(req_id, payload_a, TEST_USERS["buyer_headers"]),
            lambda: api.award_requirement(req_id, payload_b, TEST_USERS["buyer_headers_alt"]),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        # PRD §2.9 names the loser error explicitly.
        validate_error(loser, ApiErrorId.ERR_REQUIREMENT_ALREADY_AWARDED.value)


# ===========================================================================
# Two contracts on same PO (PRD §2.9, §3.6)
# ===========================================================================
class TestContractCreateRace:
    def test_two_contracts_same_po_one_wins(self, api):
        """PRD §2.9: "When two contract creations are attempted on the
        same approved purchase order, the unique index on
        Contract.purchase_order_id admits only one; the loser receives
        ERR_CONTRACT_ALREADY_EXISTS."

        Claim: in a concurrent /contracts create race, exactly one
        succeeds and the loser receives ERR_CONTRACT_ALREADY_EXISTS.
        """
        setup = setup_approved_po()
        clauses_a = [create_clause_template()]
        clauses_b = [create_clause_template()]
        payload_a = create_contract_payload(
            purchase_order_id=setup["po"]["id"],
            clause_template_ids=[clauses_a[0]["id"]],
            payment_terms_type="ON_DELIVERY",
            payment_terms_params={},
            parties_required=["Buyer", "Supplier"],
        )
        payload_b = create_contract_payload(
            purchase_order_id=setup["po"]["id"],
            clause_template_ids=[clauses_b[0]["id"]],
            payment_terms_type="ON_DELIVERY",
            payment_terms_params={},
            parties_required=["Buyer", "Supplier"],
        )
        results = run_race(
            lambda: api.create_contract(payload_a, TEST_USERS["buyer_headers"]),
            lambda: api.create_contract(payload_b, TEST_USERS["buyer_headers_alt"]),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_CONTRACT_ALREADY_EXISTS.value)


# ===========================================================================
# Two approvals on same step (PRD §2.9)
# ===========================================================================
class TestApprovalStepRace:
    def test_two_approvals_same_step_one_wins(self, api):
        """PRD §2.9: "When two approvers simultaneously approve the same
        ApprovalStep, first-writer-wins on the step's status flip from
        PENDING to APPROVED; the second attempt finds the step no longer
        PENDING and is rejected with ERR_INVALID_STATE."

        Claim: in a concurrent /approve race on the same step, exactly
        one succeeds; the loser receives ERR_INVALID_STATE.
        """
        setup = setup_awarded_po(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)],
            quantity=10,
        )
        step = setup["approval_steps"][0]
        # Two distinct DepartmentHead user_ids approve concurrently.
        h_a = stage_actor("DEPARTMENT_HEAD", "race-a")
        h_b = stage_actor("DEPARTMENT_HEAD", "race-b")
        results = run_race(
            lambda: api.approve_step(step["id"], h_a),
            lambda: api.approve_step(step["id"], h_b),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Two payments on same schedule entry (PRD §2.9, §3.10)
# ===========================================================================
class TestPaymentApplyRace:
    def test_two_payments_same_schedule_one_wins(self, api):
        """PRD §2.9: "When two payments are applied against the same
        PaymentSchedule entry, first-writer-wins on the schedule entry's
        flip from PENDING to APPLIED and the loser receives
        ERR_PAYMENT_ALREADY_APPLIED."

        Claim: in a concurrent /payments apply race, exactly one
        succeeds; the loser receives ERR_PAYMENT_ALREADY_APPLIED.
        """
        from test_helpers import setup_invoice_approved
        setup = setup_invoice_approved()
        schedule = setup["payment_schedule"]
        invoice = setup["invoice"]
        first = schedule[0]
        payload = apply_payment_payload(
            payment_schedule_id=first["id"], invoice_id=invoice["id"]
        )
        results = run_race(
            lambda: api.apply_payment(payload, TEST_USERS["finance_headers"]),
            lambda: api.apply_payment(payload, TEST_USERS["finance_headers_alt"]),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_PAYMENT_ALREADY_APPLIED.value)


# ===========================================================================
# Two signatures from the same role (PRD §2.9, §3.6)
# ===========================================================================
class TestContractSignatureRace:
    def test_two_buyer_signatures_one_wins(self, api):
        """PRD §2.9: "When two signatures from the same role are recorded
        on the same contract concurrently, the unique constraint on the
        pair of contract id and signature role admits only one; the
        loser receives ERR_SIGNATURE_ALREADY_COLLECTED."

        Claim: in a concurrent /sign race with role=Buyer, exactly one
        succeeds; the loser receives ERR_SIGNATURE_ALREADY_COLLECTED.
        """
        from test_helpers import (
            create_contract_for,
            finalize_contract_review,
            submit_contract_review,
        )
        setup = setup_approved_po()
        contract = create_contract_for(setup["po"])
        submit_contract_review(contract["id"])
        finalize_contract_review(contract["id"])
        sig = sign_contract_payload(role="Buyer")
        results = run_race(
            lambda: api.sign_contract(contract["id"], sig, TEST_USERS["buyer_headers"]),
            lambda: api.sign_contract(contract["id"], sig, TEST_USERS["buyer_headers_alt"]),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        validate_error(outcome["failures"][0], ApiErrorId.ERR_SIGNATURE_ALREADY_COLLECTED.value)
