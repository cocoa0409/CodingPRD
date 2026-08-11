"""Spec-line drawdown conservation and the pinned-order install closeout
calculation (PRD §2.10, §3.4)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, assert_spec_line_drawdown_invariant,
    make_district_buyer_headers, validate_success, add_po_line,
    build_accepted_award_context, build_verified_line_context, cancel_po_line,
    create_po, get_po, get_spec_line,
)

FC = TEST_USERS["fulfillment_coordinator_headers"]


def _buyer(ctx):
    return make_district_buyer_headers(ctx["district"]["id"])


class TestSpecLineDrawdownInvariant:
    def _setup_drawdown(self, api):
        """Spec line qty 500; PO (RECEIVED) with lines 200 and 150 -> remaining 150."""
        ctx = build_accepted_award_context(with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        po = create_po(ctx["award"]["id"], d_id, po_number="PO-1")
        add_po_line(po["id"], ctx["spec_line"]["id"], d_id, 200)
        add_po_line(po["id"], ctx["spec_line"]["id"], d_id, 150)
        return ctx, po

    def test_poline_create_debits_remaining_qty_and_cancel_restores(self, api):
        """PRD §2.10: "A spec line's `remaining_qty` is always its `qty` minus the
        summed ordered quantities of non-cancelled PO lines referencing it; ordering
        debits it and cancelling credits it back, leaving the invariant sum
        unchanged."

        Design: Difficulty/compensating_invariant/specline_drawdown_create_then_cancel_restores_remaining_qty
        """
        ctx, po = self._setup_drawdown(api)
        d_id = ctx["district"]["id"]
        sl_id = ctx["spec_line"]["id"]
        assert get_spec_line(sl_id, d_id)["remaining_qty"] == 150

        line3 = add_po_line(po["id"], sl_id, d_id, 50)
        assert get_spec_line(sl_id, d_id)["remaining_qty"] == 100

        cancel_po_line(line3["id"], d_id)
        restored = get_spec_line(sl_id, d_id)
        assert restored["remaining_qty"] == 150
        assert_spec_line_drawdown_invariant(restored, 350)

    def test_po_total_recomputed_after_compensating_cancel(self, api):
        """PRD §3.4: "triggers recompute of the order's `total_cents` — the sum of
        `line_total_cents` over the order's non-`CANCELLED` lines."
        PRD §3.4: "Individual lines may also be cancelled on their own: a line in
        `PENDING` ... becomes `CANCELLED`; the same drawdown compensation and
        order-total recompute apply"

        Design: Difficulty/compensating_invariant/specline_drawdown_create_then_cancel_restores_remaining_qty
        """
        ctx, po = self._setup_drawdown(api)
        d_id = ctx["district"]["id"]
        line3 = add_po_line(po["id"], ctx["spec_line"]["id"], d_id, 50)
        assert get_po(po["id"])["total_cents"] == 350 * 11000 + 550000

        cancel_po_line(line3["id"], d_id)
        assert get_po(po["id"])["total_cents"] == 3850000  # (200 + 150) x 11000
        assert get_spec_line(ctx["spec_line"]["id"], d_id)["remaining_qty"] == 150


class TestInstallCloseout:
    def test_closeout_per_line_rounding_before_sum(self, api):
        """PRD §3.4: "First, for each non-`CANCELLED` line, the installation charge
        is `ordered_qty` multiplied by the award's `install_rate_cents`, divided by
        one hundred, rounded half-up to a whole number, and multiplied back by one
        hundred — each line's charge rounded half-up to whole dollars before any
        summation."
        PRD §3.4: "if the latest `installed_at` date among the order's
        non-`CANCELLED` lines falls on or before that midpoint date, an
        early-completion credit of three percent of the subtotal — again rounded
        half-up to whole dollars — is granted; otherwise the credit is zero."

        Design: Difficulty/combinatorial_formula/install_closeout_per_line_rounding_before_sum
        """
        ctx = build_verified_line_context(
            line_qtys=(2, 2), complete_clock="2026-07-08T10:00:00Z")
        resp = api.close_purchase_order(
            ctx["po"]["id"],
            FC)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        # Per line: round_half_up(2*25125/100)*100 = 50300; subtotal 100600.
        # Credit: round_half_up(100600*0.03/100)*100 = 3000. Closeout 97600.
        assert closed["closeout_total_cents"] == 97600

    def test_closeout_single_line_rounds_half_up_to_whole_dollars(self, api):
        """PRD §3.4: "rounded half-up to a whole number, and multiplied back by one
        hundred — each line's charge rounded half-up to whole dollars before any
        summation."
        PRD §3.4: "Closing is a `FulfillmentCoordinator` action valid only on a
        `FULFILLED` order, and it computes `closeout_total_cents`"

        Design: Difficulty/combinatorial_formula/install_closeout_per_line_rounding_before_sum
        """
        ctx = build_verified_line_context(
            line_qtys=(2,), complete_clock="2026-07-08T10:00:00Z")
        resp = api.close_purchase_order(
            ctx["po"]["id"],
            FC)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        # Line: round_half_up(502.5) = 503 -> 50300. Credit round_half_up(15.09) = 15
        # -> 1500. Closeout 48800.
        assert closed["closeout_total_cents"] == 48800

    def test_closeout_credit_omitted_after_window_mid_date(self, api):
        """PRD §3.4: "if the latest `installed_at` date among the order's
        non-`CANCELLED` lines falls on or before that midpoint date, an
        early-completion credit of three percent of the subtotal — again rounded
        half-up to whole dollars — is granted; otherwise the credit is zero."

        Design: Corner/calculations/closeout_credit_omitted_after_window_mid_date
        """
        ctx = build_verified_line_context(
            line_qtys=(2, 2), complete_clock="2026-07-20T10:00:00Z")
        resp = api.close_purchase_order(
            ctx["po"]["id"],
            FC)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        # Installed 2026-07-20 > midpoint 2026-07-15: credit 0, closeout == subtotal.
        assert closed["closeout_total_cents"] == 100600
