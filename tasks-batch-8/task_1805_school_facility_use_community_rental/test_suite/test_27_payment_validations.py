"""Payment posting rules: exact deposit amounts, overpayment rejection, and
idempotency-key replay semantics (PRD §2.10, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    invoice_of_kind,
    make_renter_headers,
    setup_approved_permit,
    capture_deposit, set_clock, get_single_work_order,
    pay_fee,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


def _approved_permit(api):
    return setup_approved_permit(
        event_title="Auction", headcount_estimate=100,
        starts_at="2026-12-01T01:00:00Z", ends_at="2026-12-01T03:00:00Z")


class TestPaymentAmounts:
    def test_payment_amount_mismatch_and_overpayment(self, api):
        """PRD §3.5: "A renter secures the permit by posting a payment of kind
        `DEPOSIT_CAPTURE` while the permit is `ISSUED`; the posted `amount_cents`
        must equal `deposit_required_cents` exactly — any other amount is
        rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` — and on success the
        financial dimension moves `DEPOSIT_PENDING` → `SECURED` with
        `deposit_held_cents` set to the captured amount."
        PRD §3.5: "A `FEE_PAYMENT` may not exceed the target invoice's remaining
        balance — its `total_cents` minus its `amount_paid_cents` so far — or the
        posting is rejected with `ERR_OVERPAYMENT`; when cumulative payments
        bring `amount_paid_cents` level with `total_cents`, the invoice becomes
        `PAID`."

        Design: Corner/validations/payment_amount_mismatch_and_overpayment
        """
        # 4h window on the STANDARD gym: deposit_required == 10000.
        env, req, permit = setup_approved_permit(
            event_title="Auction", headcount_estimate=200,
            starts_at="2026-09-13T00:00:00Z", ends_at="2026-09-13T04:00:00Z")
        assert permit["deposit_required_cents"] == 10000

        # Off by one cent: rejected.
        mismatch = api.post_payment(
            permit["id"],
            {"txn_kind": "DEPOSIT_CAPTURE", "amount_cents": 9999,
             "idempotency_key": "dep-mm-1"},
            make_renter_headers(env["org"]["id"]))
        validate_error(mismatch, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

        capture_deposit(env, permit["id"], 10000, "dep-mm-2")
        set_clock("2026-09-13T12:00:00Z")
        validate_success(api.complete_permit(permit["id"], COORDINATOR))
        order = get_single_work_order(permit["id"])
        validate_success(api.verify_work_order(
            order["id"], {"actual_hours": 6.5}, SUPERVISOR))
        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        final = invoice_of_kind(invoices, "FINAL")
        assert final["total_cents"] == 62225

        # Full settlement: invoice PAID, permit financial dimension SETTLED.
        pay_fee(env, permit["id"], final["id"], 62225, "fee-mm-1")
        assert validate_success(api.get_invoice(final["id"], DIRECTOR))[
            "invoice_status"] == "PAID"
        assert validate_success(api.get_permit(permit["id"], DIRECTOR))[
            "financial_status"] == "SETTLED"

        # Remaining balance is now zero: one more cent is an overpayment.
        over = api.post_payment(
            permit["id"],
            {"txn_kind": "FEE_PAYMENT", "amount_cents": 1,
             "idempotency_key": "fee-mm-2", "invoice_id": final["id"]},
            make_renter_headers(env["org"]["id"]))
        validate_error(over, ApiErrorId.ERR_OVERPAYMENT)


class TestPaymentIdempotency:
    def test_idempotency_key_replay_and_conflict(self, api):
        """PRD §2.10: "Payment posting is idempotent on the client-supplied
        `idempotency_key`. Reusing a key with an identical payload returns the
        original PaymentTransaction row unchanged and does not double-post.
        Reusing a key with a different payload is rejected with
        `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409)."

        Design: Corner/errors/idempotency_key_replay_and_conflict
        """
        env, req, permit = _approved_permit(api)
        org_headers = make_renter_headers(env["org"]["id"])

        first = validate_success(api.post_payment(
            permit["id"],
            {"txn_kind": "DEPOSIT_CAPTURE", "amount_cents": 10000,
             "idempotency_key": "dep-idem-1"},
            org_headers), 201)
        # Identical replay: the original row comes back, no double-post.
        replay = api.post_payment(
            permit["id"],
            {"txn_kind": "DEPOSIT_CAPTURE", "amount_cents": 10000,
             "idempotency_key": "dep-idem-1"},
            org_headers)
        assert replay.status_code < 300, f"replay must succeed: {replay.text}"
        assert replay.json()["data"]["id"] == first["id"]

        # Same key, different payload: conflict.
        conflict = api.post_payment(
            permit["id"],
            {"txn_kind": "DEPOSIT_CAPTURE", "amount_cents": 5000,
             "idempotency_key": "dep-idem-1"},
            org_headers)
        validate_error(conflict, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        assert len(payments) == 1, "no duplicate row was posted"
        assert payments[0]["txn_kind"] == "DEPOSIT_CAPTURE"
        assert payments[0]["amount_cents"] == 10000
