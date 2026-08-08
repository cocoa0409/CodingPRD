"""Ledger and revenue: charge/refund compensating invariant, revenue roll-up.

Covers difficulty queue A: compensating_invariant (per-reservation ledger balance
returns to zero). Plus corner case: revenue roll-up after a single charge.
"""
from test_helpers import (
    validate_success,
    make_curb_planner_headers,
    make_permittee_headers,
    setup_active_permit,
    make_confirmed_reservation,
    fetch_ledger_entries,
    ledger_entries_for_reservation,
    ledger_entries_of_type,
    sum_ledger_amount,
)


class TestChargeRefundNetsToZero:
    """Confirm appends CHARGE +900; cancel-before-start appends REFUND -900; sum == 0."""

    def _confirm_then_cancel(self, api):
        ctx = setup_active_permit(api, clock="2026-05-20T00:00:00Z")
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        cancelled = validate_success(
            api.cancel_reservation(res["id"], make_permittee_headers(ctx["permittee_id"])))
        return res["id"], cancelled

    def test_ledger_balance_returns_to_zero(self, api):
        """PRD §2.10: "cancelling a captured reservation before it starts writes a refund
        equal and opposite to its charge, so that reservation's contribution to the ledger
        nets to zero."

        Design: Difficulty/compensating_invariant/reservation_charge_refund_zero
        """
        res_id, _cancelled = self._confirm_then_cancel(api)
        entries = ledger_entries_for_reservation(
            fetch_ledger_entries(api, params={"reservation_id": res_id}), res_id)
        charges = ledger_entries_of_type(entries, "CHARGE")
        refunds = ledger_entries_of_type(entries, "REFUND")
        assert len(charges) == 1 and charges[0]["amount_cents"] == 900
        assert len(refunds) == 1 and refunds[0]["amount_cents"] == -900
        assert sum_ledger_amount(entries) == 0

    def test_payment_status_refunded_after_cancel(self, api):
        """PRD §3.5: "A permitted cancellation of a confirmed reservation moves it to
        CANCELLED, moves payment_status from CAPTURED to REFUNDED, and appends a ledger
        REFUND entry equal to the negative of estimated_price_cents".

        Design: Difficulty/compensating_invariant/reservation_charge_refund_zero
        """
        _res_id, cancelled = self._confirm_then_cancel(api)
        assert cancelled["payment_status"] == "REFUNDED"


def test_revenue_rollup_after_single_charge(api):
    """PRD §2.10: "A zone's revenue_accrued_cents is not stored independently but is
    computed on read as the signed sum of amount_cents across every ledger entry whose
    zone_id is that zone." PRD §3.8: "It reports the sum of amount_cents over CHARGE
    entries as total_charge_cents ... The net_revenue_cents is the sum of those four
    figures".

    Design: Corner/calculations/revenue_rollup_after_charge
    """
    ctx = setup_active_permit(api, clock="2026-05-20T00:00:00Z")
    make_confirmed_reservation(
        api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
        "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
    revenue = validate_success(
        api.get_revenue(make_curb_planner_headers("planner1"), params={"zone_id": ctx["zone_id"]}))
    assert revenue["total_charge_cents"] == 900
    assert revenue["net_revenue_cents"] == 900
    zone = validate_success(api.get_zone(ctx["zone_id"], make_curb_planner_headers("planner1")))
    assert zone["revenue_accrued_cents"] == 900
