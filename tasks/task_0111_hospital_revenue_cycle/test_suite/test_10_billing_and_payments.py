"""Issue-bill, payments, outstanding balance, RESOLVED transition.

Covers PRD §3.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_patient_payment,
    post_payment,
    post_payment_payload,
    re_get_encounter,
    setup_billed_encounter,
    setup_billed_with_balance,
    setup_cleared_encounter,
    setup_resolved_encounter,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 — Issue-bill
# ===========================================================================
class TestIssueBill:
    """PRD §3.7: "a `Biller` issues the bill, advancing the encounter from `CLEARED` to `BILLED` and stamping `billed_at` to the request instant.\""""

    def test_issue_bill_advances_to_billed(self, api):
        """PRD §3.7: "a `Biller` issues the bill, advancing the encounter from `CLEARED` to `BILLED` and stamping `billed_at` to the request instant."

        Claim: a successful issue-bill sets Encounter.status to
        BILLED.
        """
        patient, policy, encounter, _ = setup_cleared_encounter(
            unit_price_cents=10_000,
        )
        res = api.issue_bill(
            encounter["id"], TEST_USERS["biller_headers"],
        )
        validate_success(res)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "BILLED"


# ===========================================================================
# §3.7 — Payment posting + outstanding_balance_cents
# ===========================================================================
class TestPaymentPosting:
    """PRD §3.7: Each posting supplies amount_cents and method."""

    def test_partial_payment_reduces_outstanding_balance(self, api):
        """PRD §3.7: "Each `PatientPayment`, processed in ascending order of `posted_at` with `id` ascending as the tie-breaker, is applied to the running balance: when the payment's `method` is `REFUND`, the payment's `amount_cents` is added to the running balance; otherwise the payment's `amount_cents` is subtracted from the running balance."

        Claim: with patient_responsibility_cents=10000 and a single
        CARD payment of 4000, outstanding_balance_cents drops to
        6000.
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        res = api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=4000, method="CARD"),
            TEST_USERS["biller_headers"],
        )
        payment = validate_success(res, expected_status=201)
        assert_patient_payment(payment)
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["outstanding_balance_cents"] == 6000
        assert refreshed["status"] == "BILLED"

    def test_full_payment_advances_to_resolved(self, api):
        """PRD §3.7: "If the running balance reaches exactly zero after a non-`REFUND` payment is applied, the encounter transitions from `BILLED` to `RESOLVED` — a terminal status."

        Claim: a CASH payment of exactly patient_responsibility_cents
        advances the encounter to RESOLVED.
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=10_000, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["status"] == "RESOLVED"
        assert refreshed["outstanding_balance_cents"] == 0

    def test_refund_restores_balance(self, api):
        """PRD §3.7: "when the payment's `method` is `REFUND`, the payment's `amount_cents` is added to the running balance".

        Claim: a CARD payment of 4000 followed by a REFUND of 4000
        leaves outstanding_balance_cents back at the starting
        patient_responsibility_cents (10000) and the encounter
        remains in BILLED (the REFUND undoes the would-be resolution).
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=4000, method="CARD"),
            TEST_USERS["biller_headers"],
        )
        api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=4000, method="REFUND"),
            TEST_USERS["biller_headers"],
        )
        refreshed = re_get_encounter(encounter["id"])
        assert refreshed["outstanding_balance_cents"] == 10_000
        assert refreshed["status"] == "BILLED"


# ===========================================================================
# §3.7 — Payment amount validation
# ===========================================================================
class TestPaymentAmountValidation:
    """PRD §3.7: "amount_cents (which must be at least 1)\""""

    def test_payment_amount_below_one_rejected(self, api):
        """PRD §3.7: "The same error covers a payment whose `amount_cents` is below 1."

        Claim: amount_cents=0 returns ERR_PAYMENT_AMOUNT_INVALID.
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        res = api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=0, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_PAYMENT_AMOUNT_INVALID")

    def test_payment_exceeding_outstanding_balance_rejected(self, api):
        """PRD §3.7: "For non-`REFUND` postings, `amount_cents` must additionally be no greater than the current `outstanding_balance_cents` at the moment the post arrives. A payment that would push the running balance below zero on a non-`REFUND` method is rejected with `ERR_PAYMENT_AMOUNT_INVALID`."

        Claim: with outstanding_balance_cents=10000, a CASH payment of
        15000 returns ERR_PAYMENT_AMOUNT_INVALID.
        """
        patient, policy, encounter = setup_billed_with_balance(
            patient_responsibility_cents=10_000,
        )
        res = api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=15_000, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_PAYMENT_AMOUNT_INVALID")


# ===========================================================================
# §3.7 — payments after RESOLVED rejected
# ===========================================================================
class TestPaymentAfterResolved:
    """PRD §3.7: "`RESOLVED` is final: any subsequent attempt to post a payment on the same encounter is rejected with `ERR_INVALID_STATE`."""

    def test_payment_after_resolved_rejected(self, api):
        """PRD §3.7: "`RESOLVED` is final: any subsequent attempt to post a payment on the same encounter is rejected with `ERR_INVALID_STATE`."

        Claim: posting a CASH payment on a RESOLVED encounter returns
        ERR_INVALID_STATE.
        """
        patient, policy, encounter = setup_resolved_encounter(
            patient_responsibility_cents=10_000,
        )
        res = api.post_payment(
            encounter["id"],
            post_payment_payload(amount_cents=1, method="CASH"),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
