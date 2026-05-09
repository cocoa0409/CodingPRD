"""Concurrency tests for race outcomes that PRD prose explicitly pins
(PRD §2.9). Skipped patterns:

- Generic "two reviewers approve" — PRD §2.9 says "the loser receives
  ERR_INVALID_STATE", which IS pinned, so we DO assert it.
- "Two simultaneous dispatches on the same payout batch resolve to one
  entry into EXECUTING, and the loser receives ERR_BATCH_ALREADY_DISPATCHED".
  This IS pinned and we DO assert it.
- "Two concurrent ingests of the same (insurer_id, source, source_event_id)
  triple persist exactly one event; the duplicate is rejected idempotently
  with ERR_DUPLICATE_EVENT". Pinned — we assert.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_error_is_one_of,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    run_race,
    ApiErrorId,
    TEST_USERS,
    BatchExecutionPhase,
    setup_claim_under_review,
    setup_claim_approved,
    setup_claim_in_executing,
    create_insurer,
    create_flight,
    flight_event_payload,
    fresh_operator_id,
    make_claims_approver_headers,
    make_batch_executor_headers,
    make_payout_operator_headers,
    approve_claim_payload,
    execute_batch_payload,
    create_batch,
    approve_batch,
    unique_source_event_id,
)


class TestConcurrentApprove:
    def test_two_concurrent_approvals_one_wins_other_rejected(self, api):
        """PRD §2.9: "Two simultaneous reviews or approvals on the same
        claim, or an approve-and-reject race, resolve to a single
        transition and the loser receives ERR_INVALID_STATE (HTTP 409) on
        observing the new state."

        Claim: two distinct approvers approving the same UNDER_REVIEW claim
        concurrently — exactly one succeeds; the loser receives
        ERR_INVALID_STATE.
        """
        insurer, policy, flight, ticket, claim_uw, _rid = setup_claim_under_review(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        a1 = fresh_operator_id("apr1")
        a2 = fresh_operator_id("apr2")

        def call_a():
            return api.approve_claim(
                insurer["id"], claim_uw["id"],
                approve_claim_payload(assigned_approver_id=a1),
                make_claims_approver_headers(a1),
            )

        def call_b():
            return api.approve_claim(
                insurer["id"], claim_uw["id"],
                approve_claim_payload(assigned_approver_id=a2),
                make_claims_approver_headers(a2),
            )

        results = run_race(call_a, call_b)
        outcome = assert_exactly_one_succeeds(*results)
        # PRD §2.9 names ERR_INVALID_STATE explicitly for this race.
        loser = outcome["failures"][0]
        # Loser is a Response — extract the error_id via validate.
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(loser, [ApiErrorId.ERR_INVALID_STATE.value])


class TestConcurrentBatchExecute:
    def test_two_concurrent_dispatches_one_wins_other_already_dispatched(self, api):
        """PRD §2.9: "Two simultaneous dispatches on the same payout batch
        resolve to one entry into EXECUTING, and the loser receives
        ERR_BATCH_ALREADY_DISPATCHED (HTTP 409)."

        Claim: two distinct BatchExecutor users concurrently dispatch the
        same APPROVED batch — one wins, the other receives
        ERR_BATCH_ALREADY_DISPATCHED.
        """
        insurer, policy, flight, ticket, approved, _rid, _aid = setup_claim_approved(
            departure_delay_minutes=200,
            deductible_cents=2500,
            policy_limit_cents=150000,
        )
        batch = create_batch(insurer["id"], flight_id=flight["id"], claim_ids=[approved["id"]])
        _, ba_id = approve_batch(insurer["id"], batch["id"])
        x1 = fresh_operator_id("bx1")
        x2 = fresh_operator_id("bx2")
        # SoD: both must differ from ba_id.
        assert x1 != ba_id and x2 != ba_id

        def call_a():
            return api.execute_batch(
                insurer["id"], batch["id"],
                execute_batch_payload(assigned_batch_executor_id=x1),
                make_batch_executor_headers(x1),
            )

        def call_b():
            return api.execute_batch(
                insurer["id"], batch["id"],
                execute_batch_payload(assigned_batch_executor_id=x2),
                make_batch_executor_headers(x2),
            )

        results = run_race(call_a, call_b)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(loser, [ApiErrorId.ERR_BATCH_ALREADY_DISPATCHED.value])


class TestConcurrentEventIngest:
    def test_duplicate_event_ingest_rejects_one(self, api):
        """PRD §2.9: "Two concurrent ingests of the same (insurer_id,
        source, source_event_id) triple persist exactly one event; the
        duplicate is rejected idempotently with ERR_DUPLICATE_EVENT (HTTP
        409)."

        Claim: two concurrent POST /flights/{id}/events with the same
        (source, source_event_id) — exactly one is persisted; the loser
        receives ERR_DUPLICATE_EVENT.
        """
        insurer = create_insurer()
        flight = create_flight(insurer["id"])
        evt_id = unique_source_event_id()

        def make_call():
            return api.ingest_flight_event(
                insurer["id"], flight["id"],
                flight_event_payload(
                    source="AIRLINE",
                    reported_status="DELAYED",
                    source_event_id=evt_id,
                    reported_actual_departure_epoch_ms=10_000_000 + 200 * 60_000,
                    reported_actual_arrival_epoch_ms=15_000_000 + 200 * 60_000,
                ),
                TEST_USERS["claims_admin_headers"],
            )

        results = run_race(make_call, make_call)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(loser, [ApiErrorId.ERR_DUPLICATE_EVENT.value])


class TestConcurrentSettle:
    def test_two_concurrent_settle_one_wins_other_invalid_state(self, api):
        """PRD §2.9: "Two concurrent settlements of the same claim release
        the reserve exactly once; the second receives ERR_INVALID_STATE
        (HTTP 409)."

        Claim: two concurrent /claims/{id}/settle calls on an EXECUTING
        claim — one wins, the other receives ERR_INVALID_STATE.
        """
        (
            insurer, policy, flight, ticket, claim_exec, batch,
            _rid, aid, _ba, _bx,
        ) = setup_claim_in_executing()
        po1 = fresh_operator_id("po1")
        po2 = fresh_operator_id("po2")
        # SoD: both must differ from aid.
        assert po1 != aid and po2 != aid

        def settle_a():
            return api.settle_claim(
                insurer["id"], claim_exec["id"],
                make_payout_operator_headers(po1),
            )

        def settle_b():
            return api.settle_claim(
                insurer["id"], claim_exec["id"],
                make_payout_operator_headers(po2),
            )

        results = run_race(settle_a, settle_b)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(loser, [ApiErrorId.ERR_INVALID_STATE.value])
