"""Closing lots: the two valuations, the award cascade and the PASSED branch."""
from test_helpers import (
    TEST_USERS,
    assert_checkout_invoice,
    close_lot,
    finalize_invoice,
    invoice_lines_of_type,
    read_auction_item,
    read_bid,
    read_event,
    read_invoice,
    setup_awarded_lot_scenario,
    setup_open_lot_scenario,
    setup_proxy_leader_scenario,
    validate_success,
)


class TestAuctionValuationVariants:
    """PRD §3.5's two documented interpretations over identical bid data."""

    def test_proxy_settled_valuation_lifts_leader_one_increment_over_runner_up(self, api):
        """PRD §3.5: "When a runner-up exists, the proxy agent lifts the leader
        only as far as one minimum increment above the runner-up's own
        `effective_max_cents`, but never past the leader's own ceiling: the
        valuation is whichever is smaller of the leader's `effective_max_cents`
        and the runner-up's `effective_max_cents` plus the lot's
        `min_increment_cents`."
        PRD §3.5: "Otherwise the active bids are ranked by `effective_max_cents`
        from highest to lowest, ties broken by `created_at` earliest-first, and
        the top-ranked bid is the leader whose id is reported as the source
        bid."

        Design: Difficulty/dual_variant_calc/auction_valuation_proxy_settled_vs_placed_amount
        """
        env = setup_proxy_leader_scenario()

        response = api.get_valuation(
            env["lot"]["id"], "PROXY_SETTLED", TEST_USERS["auction_manager_headers"]
        )
        valuation = validate_success(response, 200)

        assert valuation["variant"] == "PROXY_SETTLED", (
            "The computed read echoes back the requested variant"
        )
        assert valuation["amount_cents"] == 12_500, (
            "min(leader ceiling 20000, runner-up 12000 + increment 500) is 12500, "
            f"got {valuation['amount_cents']}"
        )
        assert valuation["source_bid_id"] == env["bid_a"]["id"], (
            "The proxy-ceiling holder is the leader"
        )
        assert valuation["active_bid_count"] == 2
        assert read_auction_item(env["lot"]["id"])["current_leading_amount_cents"] == 12_500, (
            "current_leading_amount_cents follows the proxy-settled reading"
        )

    def test_placed_amount_valuation_reports_the_literal_typed_amount(self, api):
        """PRD §3.5: "Under the `PLACED_AMOUNT` interpretation, requested
        explicitly by asking for that variant, the valuation is always the
        leader's literal `amount_cents` — the number the guest actually typed,
        with `proxy_max_cents` disregarded entirely."
        PRD §3.5: "Whenever a leader leads on its proxy ceiling rather than on
        its placed amount, `PLACED_AMOUNT` reports the strictly smaller figure."

        Design: Difficulty/dual_variant_calc/auction_valuation_proxy_settled_vs_placed_amount
        """
        env = setup_proxy_leader_scenario()

        response = api.get_valuation(
            env["lot"]["id"], "PLACED_AMOUNT", TEST_USERS["auction_manager_headers"]
        )
        valuation = validate_success(response, 200)

        assert valuation["variant"] == "PLACED_AMOUNT"
        assert valuation["amount_cents"] == 10_000, (
            "The leader typed 10000; its 20000 ceiling is disregarded, got "
            f"{valuation['amount_cents']}"
        )
        assert valuation["source_bid_id"] == env["bid_a"]["id"]
        assert valuation["active_bid_count"] == 2


class TestLotCloseCascade:
    """PRD §3.5's four-level cascade from award through to invoice totals."""

    def test_lot_close_freezes_hammer_price_and_marks_winning_bid(self, api):
        """PRD §3.5: "If at least one is, the lot goes `OPEN → AWARDED`:
        `hammer_price_cents` is frozen to the proxy-settled valuation described
        above, `winning_bid_id` is set to the leading bid's id, that leading bid
        moves `ACTIVE → WON` while every other `ACTIVE` bid on the lot moves
        `ACTIVE → LOST` (each bid advancing its own `version`), and the
        settlement dimension moves `UNSETTLED → INVOICED` in the same request."

        Design: Difficulty/transitive_cascade/lot_close_cascades_through_invoice_totals_to_bidder_balance
        """
        env = setup_proxy_leader_scenario()

        response = api.close_auction_item(
            env["lot"]["id"], TEST_USERS["auction_manager_headers"]
        )
        lot = validate_success(response, 200)

        assert lot["listing_status"] == "AWARDED"
        assert lot["hammer_price_cents"] == 12_500, (
            "The hammer freezes at the proxy-settled valuation, got "
            f"{lot['hammer_price_cents']}"
        )
        assert lot["winning_bid_id"] == env["bid_a"]["id"]
        assert read_bid(env["bid_a"]["id"])["status"] == "WON"
        assert read_bid(env["bid_b"]["id"])["status"] == "LOST", (
            "Every other ACTIVE bid moves to LOST"
        )

    def test_lot_close_appends_auction_line_and_recomputes_invoice_totals(self, api):
        """PRD §3.5: "The cascade then runs four levels deep: the winner's
        `OPEN` invoice for this event is located — and created if the guest has
        none — and an `AUCTION_ITEM` line for `hammer_price_cents` is appended
        to it, with the lot's `invoice_id` set to that invoice; that invoice
        recomputes `line_subtotal_cents`, `processing_fee_cents`,
        `total_due_cents` and `balance_due_cents`; and the invoice's guest
        recomputes `outstanding_balance_cents` from their `PENDING_PAYMENT` and
        `PARTIALLY_PAID` invoices."
        PRD §3.7: "when it is false, `total_due_cents` is simply
        `line_subtotal_cents`."

        Design: Difficulty/transitive_cascade/lot_close_cascades_through_invoice_totals_to_bidder_balance
        """
        env = setup_proxy_leader_scenario()

        lot = close_lot(env["lot"]["id"])

        assert lot["invoice_id"] is not None, (
            "Awarding the lot must attach it to the winner's invoice"
        )
        invoice = read_invoice(lot["invoice_id"])
        assert_checkout_invoice(invoice)
        assert invoice["bidder_id"] == env["bidders"][0]["id"], (
            "The invoice belongs to the winning guest"
        )
        auction_lines = invoice_lines_of_type(invoice, "AUCTION_ITEM")
        assert len(auction_lines) == 1, (
            f"Exactly one AUCTION_ITEM line is appended, got {len(auction_lines)}"
        )
        assert auction_lines[0]["amount_cents"] == 12_500, (
            "The auction line carries the hammer price"
        )
        assert invoice["line_subtotal_cents"] == 12_500
        assert invoice["total_due_cents"] == 12_500, (
            "cover_processing_fee defaults to false, so no fee is added"
        )
        assert invoice["balance_due_cents"] == 12_500


class TestPassedLotBranch:
    """PRD §3.5's zero-active-bid branch, which touches no money at all."""

    def test_close_lot_with_no_bids_passes_without_hammer_or_invoice(self, api):
        """PRD §3.5: "If instead no bid on the lot is `ACTIVE` at close, the lot
        goes `OPEN → PASSED` and the side-effect set is deliberately different:
        `hammer_price_cents` stays null, `settlement_status` stays `UNSETTLED`,
        and no invoice anywhere is created or modified."

        Design: Difficulty/boundary_precision_check/close_lot_with_zero_active_bids_passes_without_invoice
        """
        env = setup_open_lot_scenario(bidder_count=1, title="Unloved Vase")

        response = api.close_auction_item(
            env["lot"]["id"], TEST_USERS["auction_manager_headers"]
        )
        lot = validate_success(response, 200)

        assert lot["listing_status"] == "PASSED", (
            f"An unbid lot passes, got {lot['listing_status']}"
        )
        assert lot["settlement_status"] == "UNSETTLED"
        assert lot["hammer_price_cents"] is None, (
            f"A passed lot has no hammer price, got {lot['hammer_price_cents']}"
        )
        assert lot["invoice_id"] is None, "A passed lot creates no invoice"

    def test_passed_lot_decrements_open_lot_count(self, api):
        """PRD §3.5: "The event still recomputes `open_lot_count`, which
        decreases by one, and the lot's `version` still advances."
        PRD §3.5: "Opening increases the event's `open_lot_count` by one and
        advances the lot's `version`."

        Design: Difficulty/boundary_precision_check/close_lot_with_zero_active_bids_passes_without_invoice
        """
        env = setup_open_lot_scenario(bidder_count=1, title="Unloved Vase")
        assert read_event(env["event"]["id"])["open_lot_count"] == 1

        close_lot(env["lot"]["id"])

        assert read_event(env["event"]["id"])["open_lot_count"] == 0, (
            "Closing the only open lot returns the rollup to zero"
        )


class TestParallelListingAndSettlementAxes:
    """PRD §3.5's two independent dimensions on a single lot row."""

    def test_awarded_lot_is_invoiced_but_not_yet_paid(self, api):
        """PRD §3.5: "Like a ticket order, a lot carries two independent
        dimensions. The listing dimension runs `DRAFT → OPEN` and then forks to
        either `AWARDED` or `PASSED`, both terminal. The settlement dimension
        runs `UNSETTLED → INVOICED → PAID`, with a compensating edge
        `INVOICED → UNSETTLED` when the invoice carrying the lot is voided. The
        two evolve independently on the same row."

        Design: Difficulty/non_linear_state_machine/auction_item_listing_and_settlement_axes_move_independently
        """
        env = setup_awarded_lot_scenario()

        lot = read_auction_item(env["lot"]["id"])
        assert lot["listing_status"] == "AWARDED", (
            "The listing axis reaches its terminal state at close"
        )
        assert lot["settlement_status"] == "INVOICED", (
            f"The settlement axis is only INVOICED at close, got "
            f"{lot['settlement_status']}"
        )

    def test_payment_moves_settlement_axis_without_touching_listing_axis(self, api):
        """PRD §3.5: "The settlement dimension later moves `INVOICED → PAID`
        when the invoice carrying the lot reaches `PAID`, and reverts
        `INVOICED → UNSETTLED` with `invoice_id` cleared to null when that
        invoice is voided; both hops advance the lot's `version`."
        PRD §3.7: "If the capture clears the balance to exactly zero, the
        invoice moves to `PAID` — from `PENDING_PAYMENT` directly if this was
        the only payment, or from `PARTIALLY_PAID` if earlier payments had
        already landed — and the same full cascade runs in both cases: every
        auction lot whose `invoice_id` is this invoice moves its
        `settlement_status` `INVOICED → PAID`, every paddle-raise gift likewise,
        and every ticket order moves its `payment_status` `INVOICED → PAID`; the
        event then recomputes `gross_collected_cents` and `unpaid_invoice_count`
        and re-derives its posture; the guest recomputes
        `outstanding_balance_cents`; and the invoice's `version` advances."

        Design: Difficulty/non_linear_state_machine/auction_item_listing_and_settlement_axes_move_independently
        """
        env = setup_awarded_lot_scenario()
        invoice = finalize_invoice(env["invoice_id"])

        response = api.create_payment(
            {
                "invoice_id": env["invoice_id"],
                "amount_cents": invoice["balance_due_cents"],
                "method": "CARD",
            },
            TEST_USERS["finance_headers"],
        )
        validate_success(response, 201)

        lot = read_auction_item(env["lot"]["id"])
        assert lot["settlement_status"] == "PAID", (
            f"Full payment settles the lot, got {lot['settlement_status']}"
        )
        assert lot["listing_status"] == "AWARDED", (
            "The listing axis is untouched by settlement"
        )
        assert read_invoice(env["invoice_id"])["status"] == "PAID"
