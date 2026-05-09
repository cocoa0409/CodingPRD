"""Payout batch lifecycle: create / approve / execute / mark_exception /
retry_exceptions / settle / SoD (PRD §3.8, §3.9).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    BatchReviewPhase,
    BatchExecutionPhase,
    ClaimPayoutStatus,
    ClaimReviewStatus,
    setup_claim_approved,
    setup_claim_in_executing,
    setup_claim_paid,
    setup_basic_insurer_with_policy,
    setup_basic_claim_in_matched,
    setup_flight_with_delay,
    create_ticket,
    create_claim,
    create_batch,
    create_batch_payload,
    approve_batch,
    approve_batch_payload,
    execute_batch,
    execute_batch_payload,
    reject_batch,
    submit_review,
    approve_claim,
    fresh_operator_id,
    make_batch_approver_headers,
    make_batch_executor_headers,
    make_payout_operator_headers,
    mark_exception,
    retry_exceptions,
    settle_claim,
    run_sweep,
    assert_payout_batch,
)


class TestBatchCreation:
    def test_batch_with_payable_same_flight_claim_is_staged(self, api, batch_approver_headers):
        """PRD §3.8: "On creation, every included claim's payout_batch_id is
        set, and the batch's total_planned_payout_cents is frozen as the sum
        of estimated_payout_cents over the included claims. The batch begins
        with review_phase STAGED and execution_phase PENDING".

        Claim: a batch with one PAYABLE claim returns review_phase=STAGED,
        execution_phase=PENDING, total_planned_payout_cents=claim's estimated.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        resp = api.create_payout_batch(
            insurer["id"],
            create_batch_payload(flight_id=flight["id"], claim_ids=[approved["id"]]),
            batch_approver_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_payout_batch(data)
        assert data["review_phase"] == BatchReviewPhase.STAGED.value
        assert data["execution_phase"] == BatchExecutionPhase.PENDING.value
        assert data["total_planned_payout_cents"] == approved["estimated_payout_cents"]
        assert data["claim_ids"] == [approved["id"]]

    def test_batch_flight_mismatch_rejected(self, api, batch_approver_headers):
        """PRD §3.8: "every such claim must have at least one segment whose
        flight_id equals the batch's flight_id (otherwise
        ERR_BATCH_FLIGHT_MISMATCH)".

        Claim: a batch on flight F2 containing a claim whose only segment
        is on flight F1 → ERR_BATCH_FLIGHT_MISMATCH.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        # A second flight with no claim on it.
        other_flight = setup_flight_with_delay(
            insurer["id"],
            scheduled_departure_epoch_ms=20_000_000,
            scheduled_arrival_epoch_ms=25_000_000,
            departure_delay_minutes=200,
        )
        resp = api.create_payout_batch(
            insurer["id"],
            create_batch_payload(flight_id=other_flight["id"], claim_ids=[approved["id"]]),
            batch_approver_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_FLIGHT_MISMATCH.value)


class TestBatchReviewPhase:
    def test_approve_batch_transitions_review_phase(self, api):
        """PRD §3.8: "Approval transitions review_phase from STAGED to
        APPROVED and leaves execution_phase unchanged at PENDING."

        Claim: approve a STAGED batch → review_phase=APPROVED,
        execution_phase=PENDING.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        batch = create_batch(insurer["id"], flight_id=flight["id"], claim_ids=[approved["id"]])
        approved_batch, _ba_id = approve_batch(insurer["id"], batch["id"])
        assert approved_batch["review_phase"] == BatchReviewPhase.APPROVED.value
        assert approved_batch["execution_phase"] == BatchExecutionPhase.PENDING.value

    def test_batch_approver_cannot_be_claim_approver(self, api):
        """PRD §3.8: "provided the batch approver's X-User-ID does not equal
        any of the per-claim assigned_approver_id values across the batch
        (otherwise ERR_SOD_VIOLATION)".

        Claim: when batch approver's X-User-ID equals the per-claim
        approver id → ERR_SOD_VIOLATION.
        """
        insurer, policy, flight, ticket, approved, _rid, aid = setup_claim_approved()
        batch = create_batch(insurer["id"], flight_id=flight["id"], claim_ids=[approved["id"]])
        # Reuse the per-claim approver id as the batch approver — must fail.
        resp = api.approve_batch(
            insurer["id"], batch["id"],
            approve_batch_payload(assigned_batch_approver_id=aid),
            make_batch_approver_headers(aid),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_reject_batch_review_phase_rejected(self, api):
        """PRD §3.8: "Alternatively, a BatchApprover rejects the staged
        batch — which transitions review_phase from STAGED to REJECTED,
        leaves each child claim's payout_status at PAYABLE (reserves are
        not released because the per-claim review_status is still
        APPROVED), and accepts a reason in the request body."

        Claim: reject a STAGED batch → review_phase=REJECTED; each child
        claim's payout_status remains PAYABLE.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        batch = create_batch(insurer["id"], flight_id=flight["id"], claim_ids=[approved["id"]])
        rejected_batch = reject_batch(insurer["id"], batch["id"], reason="manual review")
        assert rejected_batch["review_phase"] == BatchReviewPhase.REJECTED.value
        # Claim should still be PAYABLE.
        from test_helpers import get_claim
        claim_now = get_claim(insurer["id"], approved["id"])
        assert claim_now["payout_status"] == ClaimPayoutStatus.PAYABLE.value


class TestBatchExecution:
    def test_execute_requires_review_phase_approved(self, api):
        """PRD §3.9: "Execution requires review_phase to be APPROVED
        (otherwise ERR_BATCH_NOT_APPROVED)."

        Claim: execute on a STAGED batch (no approve yet) →
        ERR_BATCH_NOT_APPROVED.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        batch = create_batch(insurer["id"], flight_id=flight["id"], claim_ids=[approved["id"]])
        # Skip approve, go straight to execute.
        xid = fresh_operator_id("bx")
        resp = api.execute_batch(
            insurer["id"], batch["id"],
            execute_batch_payload(assigned_batch_executor_id=xid),
            make_batch_executor_headers(xid),
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_APPROVED.value)

    def test_execute_with_executor_equal_approver_violates_sod(self, api):
        """PRD §3.9: "must equal the caller's X-User-ID and must differ
        from the recorded assigned_batch_approver_id (otherwise
        ERR_SOD_VIOLATION)".

        Claim: when batch executor's X-User-ID equals the recorded batch
        approver id → ERR_SOD_VIOLATION.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved()
        batch = create_batch(insurer["id"], flight_id=flight["id"], claim_ids=[approved["id"]])
        _, ba_id = approve_batch(insurer["id"], batch["id"])
        resp = api.execute_batch(
            insurer["id"], batch["id"],
            execute_batch_payload(assigned_batch_executor_id=ba_id),
            make_batch_executor_headers(ba_id),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_execute_drives_claims_to_executing(self, api):
        """PRD §3.9: "On success, execution_phase advances from PENDING to
        EXECUTING, every child claim whose payout_status is PAYABLE is
        moved to EXECUTING".

        Claim: after approve+execute, batch.execution_phase=EXECUTING and
        every child claim payout_status=EXECUTING.
        """
        (
            insurer, policy, flight, ticket, claim, batch,
            _rid, _aid, _ba, _bx,
        ) = setup_claim_in_executing()
        assert batch["execution_phase"] == BatchExecutionPhase.EXECUTING.value
        assert claim["payout_status"] == ClaimPayoutStatus.EXECUTING.value


class TestSettleAndExceptions:
    def test_settle_executing_claim_drives_to_paid(self, api):
        """PRD §3.9: "A PayoutOperator (or the system) marks the claim as
        paid once banking confirms, advancing the per-claim payout_status
        from EXECUTING to PAID."

        Claim: settle an EXECUTING claim → payout_status=PAID.
        """
        (
            insurer, policy, flight, ticket, claim_paid, batch,
            *_ids,
        ) = setup_claim_paid()
        assert claim_paid["payout_status"] == ClaimPayoutStatus.PAID.value
        assert claim_paid["final_payout_cents"] == claim_paid["estimated_payout_cents"]

    def test_payout_operator_cannot_be_claim_approver(self, api):
        """PRD §3.9: "the per-claim payout_operator_id is also recorded as
        the executor's X-User-ID, with the additional segregation check
        that this operator id cannot equal the per-claim
        assigned_approver_id".

        Claim: settle with X-User-ID equal to the per-claim approver id →
        ERR_SOD_VIOLATION.
        """
        (
            insurer, policy, flight, ticket, claim_exec, batch,
            _rid, aid, _ba, _bx,
        ) = setup_claim_in_executing()
        # Re-attempt settle as the per-claim approver — SoD must fail.
        resp = api.settle_claim(
            insurer["id"], claim_exec["id"],
            make_payout_operator_headers(aid),
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION.value)

    def test_mark_exception_isolates_claim_to_payable(self, api):
        """PRD §3.9: "A PayoutOperator (or the system) marks a failure with
        the mark-exception capability, supplying an optional reason in the
        request body. The per-claim payout_status reverts from EXECUTING
        back to PAYABLE, the claim id is appended to the parent batch's
        exception_claim_ids, and the batch's execution_phase advances to
        EXCEPTIONS if it was previously EXECUTING."

        Claim: mark_exception on an EXECUTING claim drives it back to
        PAYABLE and the batch into EXCEPTIONS.
        """
        (
            insurer, policy, flight, ticket, claim_exec, batch,
            _rid, _aid, _ba, _bx,
        ) = setup_claim_in_executing()
        excepted, _po = mark_exception(insurer["id"], claim_exec["id"])
        assert excepted["payout_status"] == ClaimPayoutStatus.PAYABLE.value
        from test_helpers import api_client
        batch_now = api_client.get_payout_batch(
            insurer["id"], batch["id"], TEST_USERS["claims_admin_headers"]
        )
        from test_helpers import get_success_data
        b = get_success_data(batch_now)
        assert b["execution_phase"] == BatchExecutionPhase.EXCEPTIONS.value
        assert claim_exec["id"] in b["exception_claim_ids"]

    def test_retry_exceptions_clears_and_re_executes(self, api):
        """PRD §3.9: "A BatchExecutor re-dispatches only the exception claims
        with the retry-exceptions capability, which clears
        exception_claim_ids, transitions the per-claim payout_status from
        PAYABLE back to EXECUTING for each formerly excepted claim, and
        returns the batch's execution_phase from EXCEPTIONS to EXECUTING."

        Claim: retry_exceptions clears exception_claim_ids, returns batch to
        EXECUTING, and the claim back to EXECUTING.
        """
        (
            insurer, policy, flight, ticket, claim_exec, batch,
            _rid, _aid, _ba, bx_id,
        ) = setup_claim_in_executing()
        mark_exception(insurer["id"], claim_exec["id"])
        retried = retry_exceptions(insurer["id"], batch["id"], executor_id=bx_id)
        assert retried["execution_phase"] == BatchExecutionPhase.EXECUTING.value
        assert retried["exception_claim_ids"] == []
        # Claim should be back to EXECUTING.
        from test_helpers import get_claim
        c = get_claim(insurer["id"], claim_exec["id"])
        assert c["payout_status"] == ClaimPayoutStatus.EXECUTING.value
