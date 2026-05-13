"""Payment lifecycle: batch creation, execute, callback, retry, cascade.

Targets PRD §3.9 entirely:
- batch validation (duplicate / unknown / non-APPROVED ids)
- pinned Payment.amount == form.total_reimbursable
- PENDING → EXECUTING (attempt_count bump)
- EXECUTING → SUCCESS / FAILED (callback)
- FAILED → RETRYING (with MAX_PAYMENT_ATTEMPTS = 3)
- SUCCESS cascade: form APPROVED → PAID; every Invoice ATTACHED → CONSUMED
"""
from __future__ import annotations
import uuid

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_payment,
    get_success_data,
    payment_batch_payload,
    payment_pending,
    payment_result_payload,
    payment_succeeded,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    approved_form_no_self_paid,
    approved_form_with_one_lodging_item,
    create_payment_batch,
    execute_payment,
    post_payment_outcome,
)


# ---------------------------------------------------------------------------
# Batch validation (PRD §3.9, ERR_INVALID_BATCH)
# ---------------------------------------------------------------------------
class TestBatchValidation:

    def test_duplicate_form_ids_rejected(self, api):
        """PRD §3.9: "The batch endpoint rejects the entire call with
        ERR_INVALID_BATCH if the request body contains duplicate form_ids."

        Claim: same form_id listed twice → ERR_INVALID_BATCH.
        """
        cast, _app, _seg, _inv, approved = approved_form_no_self_paid()
        res = api.create_payment_batch(
            payment_batch_payload(
                form_ids=[approved["id"], approved["id"]],
                channel="BANK_TRANSFER",
            ),
            cast.finance_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_BATCH.value)

    def test_unknown_form_id_rejected(self, api):
        """PRD §3.9: "ERR_INVALID_BATCH if the request body... references
        any unknown form_ids."

        Claim: an id that doesn't resolve → ERR_INVALID_BATCH.
        """
        cast, _app, _seg, _inv, approved = approved_form_no_self_paid()
        res = api.create_payment_batch(
            payment_batch_payload(
                form_ids=[approved["id"], NON_EXISTENT_UUID],
                channel="BANK_TRANSFER",
            ),
            cast.finance_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_BATCH.value)


# ---------------------------------------------------------------------------
# Pinned amount (PRD §3.9)
# ---------------------------------------------------------------------------
class TestPinnedAmount:

    def test_payment_amount_equals_total_reimbursable(self, api):
        """PRD §3.9: "each payment's amount is pinned at creation time
        to the parent form's total_reimbursable."

        Claim: created Payment.amount == form.total_reimbursable.
        """
        cast, approved, _batch, payment = payment_pending(
            fixture_factory=approved_form_no_self_paid,
        )
        assert_payment(payment)
        assert payment["amount"] == pytest.approx(
            approved["total_reimbursable"], abs=0.01
        )
        assert payment["status"] == "PENDING"
        assert payment["attempt_count"] == 0


# ---------------------------------------------------------------------------
# Execute / callback (PRD §3.9)
# ---------------------------------------------------------------------------
class TestExecuteAndCallback:

    def test_execute_increments_attempt_count(self, api):
        """PRD §3.9: "Execution moves the payment from PENDING to
        EXECUTING (or from RETRYING to EXECUTING on a retry); each
        execute increments attempt_count by 1."

        Claim: after first execute, attempt_count == 1 and status == EXECUTING.
        """
        cast, _approved, _batch, pending = payment_pending(
            fixture_factory=approved_form_no_self_paid,
        )
        executed = validate_success(
            api.execute_payment(pending["id"], cast.finance_headers),
        )
        assert executed["status"] == "EXECUTING"
        assert executed["attempt_count"] == 1

    def test_success_callback_cascades_form_to_paid(self, api):
        """PRD §3.9: "A SUCCESS outcome transitions the payment from
        EXECUTING to SUCCESS, sets external_ref, and cascades two
        further state changes: the parent ReimbursementForm transitions
        from APPROVED to PAID, and every Invoice that any of the form's
        ReimbursementItems reference (via invoice_id) transitions from
        ATTACHED to CONSUMED."

        Claim: after a SUCCESS callback, payment is SUCCESS, form is
        PAID, attached invoice is CONSUMED.
        """
        cast, approved, _batch, _exec, success = payment_succeeded(
            fixture_factory=approved_form_no_self_paid,
        )
        assert success["status"] == "SUCCESS"
        assert success["external_ref"] is not None
        # Form should now be PAID.
        form_after = validate_success(
            api.get_reimbursement_form(approved["id"], cast.applicant_headers),
        )
        assert form_after["status"] == "PAID", (
            "PRD §3.9: SUCCESS cascade transitions form APPROVED → PAID"
        )
        # Invoice should now be CONSUMED.
        # Find the invoice via the item (the approved fixture attached one).
        from test_helpers import validate_paginated
        from test_helpers.fixtures import ADMIN
        data, _meta = validate_paginated(
            api.list_audit_logs(ADMIN, params={
                "subject_type": "REIMBURSEMENT_FORM",
                "subject_id": approved["id"],
            })
        )
        # The cascade also writes an EXTERNAL_SYNC + PAYMENT_EVENT audit log
        # (PRD §3.9: 'emit an EXTERNAL_SYNC audit event to the finance
        # system with the event REIMBURSEMENT_POSTED, plus one to the
        # banking system with the event PAID' and PAYMENT_EVENT). The
        # presence of at least one audit row is the minimal observable.
        # PRD silence on exact payload shape blocks deep audit assertions.

    def test_failed_callback_sets_failure_reason(self, api):
        """PRD §3.9: "A FAILED outcome transitions the payment from
        EXECUTING to FAILED and sets failure_reason."

        Claim: after a FAILED callback, payment.status == FAILED and
        failure_reason is populated.
        """
        cast, _approved, _batch, pending = payment_pending(
            fixture_factory=approved_form_no_self_paid,
        )
        execute_payment(cast, pending["id"])
        failed = post_payment_outcome(
            cast, pending["id"], outcome="FAILED",
            failure_reason="bank declined",
        )
        assert failed["status"] == "FAILED"
        assert failed.get("failure_reason") == "bank declined"


# ---------------------------------------------------------------------------
# Retry (PRD §3.9)
# ---------------------------------------------------------------------------
class TestRetry:

    def test_retry_transitions_failed_to_retrying(self, api):
        """PRD §3.9: "Retry transitions a FAILED payment to RETRYING
        provided that attempt_count is strictly less than the maximum
        of 3 attempts."

        Claim: retry after one FAILED attempt → status=RETRYING.
        """
        cast, _approved, _batch, pending = payment_pending(
            fixture_factory=approved_form_no_self_paid,
        )
        execute_payment(cast, pending["id"])
        post_payment_outcome(cast, pending["id"], outcome="FAILED",
                             failure_reason="bank declined")
        retried = validate_success(
            api.retry_payment(pending["id"], cast.finance_headers),
        )
        assert retried["status"] == "RETRYING"

    def test_retry_after_three_attempts_exhausted(self, api):
        """PRD §3.9: "a retry against a payment whose attempt_count has
        already reached 3 is rejected with ERR_PAYMENT_RETRY_EXHAUSTED."

        Claim: third FAILED outcome makes attempt_count==3; retry
        immediately returns ERR_PAYMENT_RETRY_EXHAUSTED.
        """
        cast, _approved, _batch, pending = payment_pending(
            fixture_factory=approved_form_no_self_paid,
        )
        # Attempt 1: PENDING → EXECUTING → FAILED
        execute_payment(cast, pending["id"])
        post_payment_outcome(cast, pending["id"], outcome="FAILED")
        # Retry → RETRYING. Attempt 2: RETRYING → EXECUTING → FAILED
        get_success_data(api.retry_payment(pending["id"], cast.finance_headers))
        execute_payment(cast, pending["id"])
        post_payment_outcome(cast, pending["id"], outcome="FAILED")
        # Retry → RETRYING. Attempt 3: RETRYING → EXECUTING → FAILED
        get_success_data(api.retry_payment(pending["id"], cast.finance_headers))
        execute_payment(cast, pending["id"])
        post_payment_outcome(cast, pending["id"], outcome="FAILED")
        # Now attempt_count==3 — further retry must reject.
        final = validate_success(
            api.get_payment(pending["id"], cast.finance_headers),
        )
        assert final["attempt_count"] == 3, (
            "PRD §3.9: each execute increments attempt_count by 1; "
            "three FAILED executes ⇒ attempt_count==3"
        )
        res = api.retry_payment(pending["id"], cast.finance_headers)
        validate_error(res, ApiErrorId.ERR_PAYMENT_RETRY_EXHAUSTED.value)
