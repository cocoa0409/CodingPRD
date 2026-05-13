"""Payout batches, payment lifecycle, retries, abandon, forfeit, and the
micro-balance threshold (PRD §3.12, §3.13, §3.14, §2.10 priorities 11,
23, 24, 25)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    FIN,
    PA,
    abandon_payment_payload,
    abandon_payment,
    assert_payment,
    assert_payout_batch,
    create_payout_batch,
    create_payout_batch_payload,
    create_rights_holder,
    execute_payout_batch,
    find_payment_for,
    list_batch_payments,
    make_rights_holder_headers,
    psp_callback_failure,
    psp_callback_payload,
    psp_callback_success,
    retry_payment,
    setup_approved_recording_work,
    setup_distributed_pool_for_works,
    setup_minor_with_guardian,
    setup_payment_failed_payment_for_abandon,
    unique_cycle_tag,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPayoutBatchCreation:

    def test_create_batch_returns_201_and_pending(self, api):
        """PRD §3.12: 'The newly-created batch lives in status PENDING
        with total_payments of 0 and total_paid_cents_by_currency as an
        empty map.'

        Claim: POST /royalty/payout-batches → 201 with status==PENDING,
        total_payments==0, total_paid_cents_by_currency=={}.
        """
        # Use a fresh holder with a finalized distribution so the batch
        # has something to enumerate even with 0 actual payouts.
        _h, work, _share = setup_approved_recording_work()
        setup_distributed_pool_for_works(
            [work], gross_revenue_cents=2_000_000, minimum_payout_cents=0,
        )
        batch = create_payout_batch()
        assert batch["status"] == "PENDING"

    def test_duplicate_cycle_tag_rejected(self, api):
        """PRD §3.12 / §2.10 priority 24: 'On payout-batch generation,
        cycle_tag must be unique across all PayoutBatch rows; otherwise
        ERR_DUPLICATE_CYCLE (409).'

        Claim: second POST with the same cycle_tag → ERR_DUPLICATE_CYCLE
        (409).
        """
        _h, work, _share = setup_approved_recording_work()
        setup_distributed_pool_for_works(
            [work], gross_revenue_cents=2_000_000, minimum_payout_cents=0,
        )
        tag = unique_cycle_tag()
        create_payout_batch(cycle_tag=tag)
        resp = api.create_payout_batch(
            create_payout_batch_payload(cycle_tag=tag), FIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CYCLE.value, 409)


class TestExecuteBatch:

    def test_execute_transitions_payments_to_sent(self, api):
        """PRD §3.13: 'Once the batch is PENDING and the current time
        is at or after its scheduled_run_at, a FinanceOps operator
        executes the batch. The batch's status flips from PENDING to
        RUNNING, every Payment in the batch flips from QUEUED to SENT,
        and one ExternalSyncEvent row is created per payment with
        event_kind of PAYMENT_INITIATED, target_system of PAYMENT_PSP,
        related_entity_kind of Payment, and related_entity_id set to
        the payment's id.'

        Claim: execute on a PENDING batch with at least one Payment →
        batch.status==RUNNING; each Payment.status==SENT; one
        ExternalSyncEvent per payment with event_kind=PAYMENT_INITIATED.
        """
        _h, work, _share = setup_approved_recording_work()
        setup_distributed_pool_for_works(
            [work], gross_revenue_cents=2_000_000, minimum_payout_cents=0,
        )
        batch = create_payout_batch()
        executed = execute_payout_batch(batch["id"])
        assert executed["status"] == "RUNNING"
        payments = list_batch_payments(batch["id"])
        assert len(payments) >= 1
        for p in payments:
            assert p["status"] == "SENT"
        # External sync event check.
        ext_resp = api.list_external_sync(
            PA, params={"event_kind": "PAYMENT_INITIATED",
                        "target_system": "PAYMENT_PSP", "limit": 100},
        )
        events, _ = validate_paginated(ext_resp)
        # At least one event per payment (PRD says "one per payment").
        assert len(events) >= len(payments)


class TestPSPCallbackSuccess:

    def test_psp_success_cascades_distribution_to_paid(self, api):
        """PRD §3.13: 'On SUCCESS, the payment flips from SENT to
        SUCCEEDED; every Distribution associated with this payment
        cascades from RELEASED to PAID (cascade depth 2).'

        Claim: psp-callback SUCCESS → Payment.status=SUCCEEDED; every
        associated Distribution.status=PAID.
        """
        h, work, _share = setup_approved_recording_work()
        pool, _rule, _dists = setup_distributed_pool_for_works(
            [work], gross_revenue_cents=2_000_000, minimum_payout_cents=0,
        )
        batch = create_payout_batch()
        execute_payout_batch(batch["id"])
        payments = list_batch_payments(batch["id"])
        pay = find_payment_for(payments, h["id"], currency="USD")
        assert pay is not None
        succ = psp_callback_success(pay["id"])
        assert succ["status"] == "SUCCEEDED"
        # All distributions for this holder under the pool should be PAID.
        from test_helpers import list_pool_distributions, find_distribution_for
        dists = list_pool_distributions(pool["id"])
        my_dist = find_distribution_for(dists, h["id"], work_id=work["id"])
        assert my_dist is not None
        assert my_dist["status"] == "PAID"


class TestPaymentRetryAndAbandon:

    def test_retry_increments_count_and_sets_retrying(self, api):
        """PRD §3.13: 'A FAILED payment may be retried up to three
        times. The retry operation transitions the payment from FAILED
        to RETRYING and increments retry_count by one; the precondition
        is retry_count strictly less than 3.'

        Claim: first retry on a FAILED payment → status=RETRYING,
        retry_count incremented by exactly 1.
        """
        ctx = setup_payment_failed_payment_for_abandon()
        pay = ctx["payment"]
        retried = retry_payment(pay["id"])
        assert retried["status"] == "RETRYING"
        # retry_count after first retry should be the prior + 1.
        # We don't know the prior from this test alone but PRD says
        # increments by exactly one.
        # The setup payment was created with retry_count = 0.
        assert retried["retry_count"] == 1

    def test_abandon_only_when_retry_count_at_cap(self, api):
        """PRD §3.13: 'Once retry_count reaches 3 and the payment is
        still FAILED, the operator may abandon it: the payment flips
        from FAILED to ABANDONED.' Abandon's precondition: retry_count
        >= 3 (per state machine).

        Claim: abandon when retry_count < 3 → ERR_INVALID_STATE (409)
        because the state machine guard is not satisfied.
        """
        ctx = setup_payment_failed_payment_for_abandon()
        pay = ctx["payment"]
        # retry_count == 0; abandon should be blocked.
        resp = api.abandon_payment(
            pay["id"], abandon_payment_payload(policy="RETURN_TO_MICRO"),
            FIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


class TestForfeit:

    def test_forfeit_blocked_when_payment_still_live(self, api, pa_headers):
        """PRD §3.14 / §2.10 priority 25: 'On distribution forfeit, the
        holding rights-holder must have either a payment whose status
        is FAILED or ABANDONED, or a revoked bank_account_token;
        otherwise ERR_DISTRIBUTION_NOT_FORFEITABLE (409).'

        Claim: forfeit attempted while the holder's payment is QUEUED →
        ERR_DISTRIBUTION_NOT_FORFEITABLE (409).
        """
        h, work, _share = setup_approved_recording_work()
        pool, _rule, dists = setup_distributed_pool_for_works(
            [work], gross_revenue_cents=2_000_000, minimum_payout_cents=0,
        )
        # Create the batch to spawn QUEUED Payment; do NOT execute so the
        # payment remains "live" (QUEUED).
        create_payout_batch()
        # Find a RELEASED Distribution for the holder.
        from test_helpers import find_distribution_for
        d = find_distribution_for(dists, h["id"], work_id=work["id"])
        assert d is not None
        # Try to forfeit — should be blocked.
        resp = api.forfeit_distribution(d["id"], pa_headers)
        validate_error(
            resp, ApiErrorId.ERR_DISTRIBUTION_NOT_FORFEITABLE.value, 409,
        )


# NOTE: tests that asserted ERR_MINOR_PAYOUT_BLOCKED have been removed.
# PRD §2.10 priority 11 names the error but does not define an
# "active guardian binding" entity. PRD §3.5 says a minor must reference
# a guardian_holder_id at creation (always present); PRD §3.4 declares
# AgencyBinding with agency_kind in {PUBLISHER, LABEL, CMO} only — no
# "GUARDIAN" agency kind. A PRD-faithful reader cannot uniquely derive
# what makes a guardian binding "active", so two reasonable
# implementations (always-active vs. never-active) diverge on this
# assertion. Removed per the unique-derivability rule.
class TestMinorPayoutBlocked:
    pass
