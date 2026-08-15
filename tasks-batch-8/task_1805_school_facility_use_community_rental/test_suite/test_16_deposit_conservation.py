"""Permit money is conserved across cancellation: DEPOSIT_CAPTURE minus
DEPOSIT_REFUND minus DEPOSIT_FORFEIT is exactly zero at every refund tier
(PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    sum_txns, txns_of_kind, invoice_of_kind,
    make_renter_headers,
    setup_secured_permit, set_clock,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]

# Occupancy starts 2026-12-20T01:00:00Z = Sat 2026-12-19 17:00 site-local.
EVENT_START = "2026-12-20T01:00:00Z"
EVENT_END = "2026-12-20T04:00:00Z"


def _setup(api, dep_key):
    return setup_secured_permit(
        10000, idempotency_key=dep_key,
        event_title="Holiday Concert", headcount_estimate=100,
        starts_at=EVENT_START, ends_at=EVENT_END)


class TestDepositCaptureRefundForfeitConservation:
    def test_half_tier_cancel_conserves_captured_deposit(self, api):
        """PRD §3.7: "At least seven but fewer than fourteen days before, half of
        what was paid is refundable, less a processing fee of 2500 cents."
        PRD §3.7: "The refund pays the deposit back first — the deposit refund is
        the smaller of the refund total and the held deposit, posted as
        `DEPOSIT_REFUND` — and any remainder comes back as a `FEE_REFUND`;
        whatever part of the held deposit is not refunded posts as
        `DEPOSIT_FORFEIT` to the district."
        PRD §3.6: "Issuance of a `FINAL` or `DAMAGE` invoice accrues
        `total_cents` onto the renter's `outstanding_balance_cents`."
        PRD §3.6: "A `DRAFT` or `ISSUED` invoice moves to the terminal `VOID`
        when the provisional is superseded by the final or when its permit is
        cancelled, lapsed, or superseded; voiding an invoice that was `ISSUED`
        subtracts its `total_cents` from the outstanding balance, reversing the
        accrual."

        Design: Difficulty/compensating_invariant/deposit_capture_refund_forfeit_conservation
        """
        env, req, permit = _setup(api, "dep-j-1")
        # Clock 2026-12-10T01:00Z = Dec 9 site-local: 10 whole days before
        # Dec 19 -> 50% tier: refund = round_half_up(10000 x 0.5) - 2500.
        set_clock("2026-12-10T01:00:00Z")
        cancelled = validate_success(api.cancel_permit(
            permit["id"], {"cancellation_reason": "renter cancel at day 10"},
            make_renter_headers(env["org"]["id"])))
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "REFUNDED"

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        captured = sum_txns(payments, "DEPOSIT_CAPTURE")
        refunded = sum_txns(payments, "DEPOSIT_REFUND")
        forfeited = sum_txns(payments, "DEPOSIT_FORFEIT")
        assert captured == 10000
        assert refunded == 2500     # 5000 - 2500 processing fee
        assert forfeited == 7500    # 10000 - 2500
        # Conserved quantity: captured money fully accounted, no drift.
        assert captured - refunded - forfeited == 0

        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        prov = invoice_of_kind(invoices, "PROVISIONAL")
        assert prov["invoice_status"] == "VOID"
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["outstanding_balance_cents"] == 0, (
            "the provisional total never accrued to outstanding_balance_cents")

    def test_under_seven_days_full_forfeiture_conserves(self, api):
        """PRD §3.7: "Fewer than seven days before, nothing is refundable — the
        paid amounts are fully forfeited — and no fee applies."
        PRD §3.7: "The financial dimension moves from `SECURED` or
        `DEPOSIT_PENDING` to `REFUND_PENDING` when a refundable amount above zero
        exists, and on to `REFUNDED` once the refund transactions post; when the
        applicable tier refunds nothing at all, it moves instead to `SETTLED`."

        Design: Difficulty/compensating_invariant/deposit_capture_refund_forfeit_conservation
        """
        env, req, permit = _setup(api, "dep-j-2")
        # Clock 2026-12-15T01:00Z = Dec 14 site-local: 5 whole days before
        # Dec 19 -> nothing refundable.
        set_clock("2026-12-15T01:00:00Z")
        cancelled = validate_success(api.cancel_permit(
            permit["id"], {"cancellation_reason": "too late to refund"},
            make_renter_headers(env["org"]["id"])))
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["financial_status"] == "SETTLED"

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        captured = sum_txns(payments, "DEPOSIT_CAPTURE")
        refunded = sum_txns(payments, "DEPOSIT_REFUND")
        forfeited = sum_txns(payments, "DEPOSIT_FORFEIT")
        assert captured == 10000
        assert refunded == 0
        assert txns_of_kind(payments, "DEPOSIT_REFUND") == []
        assert forfeited == 10000
        assert captured - refunded - forfeited == 0
