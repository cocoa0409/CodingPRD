"""Restitution ledgers, recovery payments, compensating invariants."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, setup_case_closed_substantiated,
    assert_ledger_invariants, create_payment_payload,
)
from test_helpers.api_client import api_client


class TestLedgerInvariant:
    """Difficulty/compensating_invariant/ledger_recovered_plus_outstanding_equals_target"""

    def _setup_ledger_with_payment(self, api):
        ctx = setup_case_closed_substantiated(
            state_code="CA", claimed_amount_cents=100_000_000,
            fraud_amount_cents=35_000_000)
        ledger = ctx["ledger"]
        mh = ctx["manager_headers"]
        resp = api_client.create_recovery_payment(
            ledger["id"],
            create_payment_payload(amount_cents=20_000_000,
                                   received_at="2026-08-12T00:00:00Z"),
            mh)
        payment = validate_success(resp, expected_status=201)
        return ctx, ledger, payment

    def test_clear_then_reverse_preserves_recovered_plus_outstanding(self, api):
        """PRD §3.7: "the outstanding balance is always the target minus the
        recovered total and is never negative."
        PRD §3.7: "On a successful clear the ledger's `recovered_amount_cents` —
        the running sum of cleared payments net of reversals — grows by the
        payment amount, the outstanding balance is recomputed"
        PRD §3.7: "Reversal unwinds a cleared payment: the payment moves from
        `CLEARED` to `REVERSED` with a `reason` and a `reversed_at` timestamp, the
        ledger's recovered total is reduced by the amount"

        Design: Difficulty/compensating_invariant/ledger_recovered_plus_outstanding_equals_target
        """
        ctx, ledger, payment = self._setup_ledger_with_payment(api)
        mh = ctx["manager_headers"]
        # Clear
        resp = api_client.clear_recovery_payment(
            ledger["id"], payment["id"],
            {"expected_ledger_version": ledger["version"]}, mh)
        validate_success(resp)
        after_clear = get_success_data(api_client.get_ledger(ledger["id"], mh))
        assert after_clear["recovered_amount_cents"] == 20_000_000
        assert after_clear["outstanding_amount_cents"] == 15_000_000
        assert_ledger_invariants(after_clear)
        # Reverse
        resp2 = api_client.reverse_recovery_payment(
            ledger["id"], payment["id"], {"reason": "bank returned"}, mh)
        validate_success(resp2)
        after_reverse = get_success_data(api_client.get_ledger(ledger["id"], mh))
        assert after_reverse["recovered_amount_cents"] == 0
        assert after_reverse["outstanding_amount_cents"] == 35_000_000
        assert_ledger_invariants(after_reverse)

    def test_ledger_status_after_reverse_of_partial_clear(self, api):
        """PRD §3.7: "a ledger that had reached `FULLY_RECOVERED` falls back to
        `PARTIALLY_RECOVERED`"
        PRD §3.7: "`FULLY_RECOVERED` and `WRITTEN_OFF` are terminal for a ledger"
        (Here, reversing the only cleared payment on a PARTIALLY_RECOVERED ledger
        returns the ledger to OPEN, since no cleared payment remains.)

        Design: Difficulty/compensating_invariant/ledger_recovered_plus_outstanding_equals_target
        """
        ctx, ledger, payment = self._setup_ledger_with_payment(api)
        mh = ctx["manager_headers"]
        resp = api_client.clear_recovery_payment(
            ledger["id"], payment["id"],
            {"expected_ledger_version": ledger["version"]}, mh)
        validate_success(resp)
        resp2 = api_client.reverse_recovery_payment(
            ledger["id"], payment["id"], {"reason": "bank returned"}, mh)
        validate_success(resp2)
        final = get_success_data(api_client.get_ledger(ledger["id"], mh))
        # After reverse, no cleared payments remain → ledger back to OPEN
        assert final["status"] == "OPEN"


class TestRecoveryExceedsOutstanding:
    def test_clear_amount_exceeding_outstanding_rejected(self, api):
        """PRD §3.7: "the payment's amount must not exceed the ledger's outstanding
        balance at the moment of clearing (`ERR_RECOVERY_EXCEEDS_OUTSTANDING`)"

        Design: Corner/errors/err_recovery_exceeds_outstanding_trigger
        """
        ctx = setup_case_closed_substantiated(
            state_code="CA", claimed_amount_cents=100_000_000,
            fraud_amount_cents=1_000_000)
        ledger = ctx["ledger"]
        mh = ctx["manager_headers"]
        resp = api_client.create_recovery_payment(
            ledger["id"],
            create_payment_payload(amount_cents=2_000_000),
            mh)
        payment = validate_success(resp, expected_status=201)
        resp2 = api_client.clear_recovery_payment(
            ledger["id"], payment["id"],
            {"expected_ledger_version": ledger["version"]}, mh)
        validate_error(resp2, ApiErrorId.ERR_RECOVERY_EXCEEDS_OUTSTANDING)
