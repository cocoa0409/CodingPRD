"""Invoicing: quote-vs-final divergence, pinned per-line rounding, underrun
credit, overrun cap with stock retention, TP revision fees, single-invoice
uniqueness, payment/memo balance caps, money conservation, and the rebate
tier evaluation order."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_invoice,
    create_completed_order,
    create_order,
    create_queued_order,
    decide_qc_report,
    drive_tooling_to_stamper_ready,
    file_qc_report,
    get_order,
    issue_standard_invoice,
    make_customer_headers,
    press_run,
    produce_test_pressing,
    quote_order,
    review_test_pressing,
    schedule_order,
    setup_world,
    ship_test_pressing,
    start_tooling,
    confirm_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BILLING, CSR


def _invoice_for(world, pressed, rejected, planned_units=None):
    """Drive a canonical order to COMPLETED and issue its STANDARD invoice."""
    staged = create_queued_order(world, quantity_ordered=1000)
    order = schedule_order(staged["order"], world["line"]["id"],
                           planned_units=planned_units or 1000)
    press_run(order["id"], slot_date="2026-08-10")
    qc = file_qc_report(order["id"], pressed, rejected)
    decide_qc_report(qc["id"], "ACCEPT", "NONE")
    invoice = issue_standard_invoice(order["id"])
    return staged["order"], order["id"], invoice


class TestQuoteVsFinalDivergence:
    def test_final_invoice_diverges_from_quote(self, api):
        """PRD §3.9: "Under `ACCEPT_AND_BILL_10` the cap is `quantity_ordered`
        increased by ten percent and rounded down to a whole unit, and the
        billed quantity is the smaller of `accepted_units` and that cap."
        PRD §3.9: "The pressing gross prices those billed units on the same
        marginal tier table used at quote time."
        PRD §3.3: "The `quote_subtotal_cents` is the sum of those four
        components; the `quote_discount_cents` is the subtotal multiplied by
        the snapshotted tier percentage, rounded half-up to whole cents; and
        the `quote_total_cents` is the subtotal minus the discount."

        Design: Difficulty/dual_variant_calc/quote_vs_final_invoice_divergence
        """
        world = setup_world()
        quoted_order, order_id, invoice = _invoice_for(world, 1000, 30)
        # Quote priced quantity_ordered 1000 forward-looking.
        assert quoted_order["quote_total_cents"] == 448420
        # Final prices billed_units = min(accepted 970, cap 1100) = 970:
        # pressing 280205 + surcharge 24250 + tooling 95000 + setup 40000.
        assert_invoice(invoice)
        assert invoice["gross_cents"] == 439455
        assert invoice["net_cents"] == 439455
        assert invoice["discount_cents"] == 0
        assert invoice["net_cents"] != quoted_order["quote_total_cents"], (
            "provisional quote and final invoice must diverge on identical order data"
        )


class TestPerLineRounding:
    def test_invoice_per_line_rounding_totals(self, api):
        """PRD §3.9: "Rounding on the invoice is pinned per line and is not
        negotiable: for each of the seven lines in order, the line's discount
        is its gross multiplied by the order's `discount_pct_snapshot`, rounded
        half-up to whole cents, and the line's net is its gross minus its
        discount. The invoice's `gross_cents` is the sum of the line grosses,
        its `discount_cents` the sum of the line discounts, and its `net_cents`
        the sum of the line nets"

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
        """
        world = setup_world(customer_over={"discount_tier": "SILVER"})
        _q, _oid, invoice = _invoice_for(world, 930, 27)
        # Billed = accepted 903: pressing 261780 + surcharge 22575
        # + tooling 95000 + setup 40000.
        assert invoice["gross_cents"] == 419355
        # Per-line 3% discounts: 7853 + 677 + 2850 + 1200.
        assert invoice["discount_cents"] == 12580
        assert invoice["net_cents"] == 406775

    def test_invoice_per_line_rounding_not_sum_first(self, api):
        """PRD §3.9: "builds the invoice's `lines` — seven entries in the fixed
        order pressing, surcharge, tooling, setup, test-pressing revision,
        underrun, and repress, each carrying `label`, `gross_cents`,
        `discount_cents`, and `net_cents`"
        PRD §3.9: "computing one discount on the grand total instead is a
        different algorithm and yields different cents."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
        """
        world = setup_world(customer_over={"discount_tier": "SILVER"})
        _q, _oid, invoice = _invoice_for(world, 930, 27)
        lines = invoice["lines"]
        assert len(lines) == 7, "the invoice must carry seven lines in the fixed order"
        # Pinned order: pressing, surcharge, tooling, setup, tp revision,
        # underrun, repress.
        assert lines[0]["gross_cents"] == 261780
        assert lines[1]["gross_cents"] == 22575
        assert lines[2]["gross_cents"] == 95000
        assert lines[3]["gross_cents"] == 40000
        expected_discounts = [7853, 677, 2850, 1200, 0, 0, 0]
        for line, disc in zip(lines, expected_discounts):
            assert line["discount_cents"] == disc, (
                f"line {line['label']}: expected per-line discount {disc}, "
                f"got {line['discount_cents']}"
            )
            assert line["net_cents"] == line["gross_cents"] - line["discount_cents"]
        # Sum-then-round on 419355 at 3% would yield 12581 -> net 406774.
        assert invoice["net_cents"] == 406775
        assert invoice["net_cents"] != 406774, (
            "per-line rounding must produce 406775, not the sum-first 406774"
        )


class TestUnderrunOverrun:
    def test_underrun_credit_line_applied(self, api):
        """PRD §3.9: "The underrun line credits the customer when accepted
        units fall short: if `accepted_units` is less than ninety percent of
        `quantity_ordered` rounded down, the shortfall is that floor minus
        `accepted_units`, and the line's gross is negative — the shortfall
        times the pressing gross divided by the billed quantity, rounded
        half-up, then negated (applicable when the billed quantity is
        positive)."

        Design: Corner/calculations/underrun_credit_line_applied
        """
        world = setup_world()
        _q, _oid, invoice = _invoice_for(world, 900, 20)
        # Accepted 880 < floor(0.9*1000) = 900: shortfall 20;
        # round_half_up(20 * 255455 / 880) = 5806 -> line gross -5806.
        assert invoice["gross_cents"] == 406649
        assert invoice["net_cents"] == 406649  # STANDARD tier, no discount
        underrun_lines = [l for l in invoice["lines"] if l["gross_cents"] == -5806]
        assert len(underrun_lines) == 1, (
            "expected one negative underrun credit line of -5806"
        )

    def test_overrun_cap_billing_and_stock_retention(self, api):
        """PRD §3.9: "Under `ACCEPT_AND_BILL_10` the cap is `quantity_ordered`
        increased by ten percent and rounded down to a whole unit, and the
        billed quantity is the smaller of `accepted_units` and that cap."
        PRD §3.9: "Overrun beyond a cap is neither billed nor shipped-invoiced
        — it remains in the inventory lot."
        PRD §3.7: "the good units are credited to inventory by finding or
        creating the release's zone-`A` InventoryLot, incrementing its
        `on_hand_units` and `received_units_cum` by the accepted count and
        assigning it the next `receipt_seq`"

        Design: Corner/calculations/overrun_cap_billing_and_stock_retention
        """
        world = setup_world()
        _q, order_id, invoice = _invoice_for(world, 1200, 50, planned_units=1200)
        # Accepted 1150, billed capped at floor(1000 * 1.10) = 1100:
        # pressing 312420 + surcharge 27500 + tooling 95000 + setup 40000.
        assert invoice["net_cents"] == 474920

        lots = validate_success(api.list_order_inventory_lots(order_id, CSR), 200)
        assert len(lots) == 1
        assert lots[0]["zone"] == "A"
        assert lots[0]["on_hand_units"] == 1150, (
            "all 1150 accepted units (incl. 50 unbilled overrun) stay in the lot"
        )
        assert lots[0]["received_units_cum"] == 1150


class TestTpRevisionFeeChain:
    def test_tp_revision_fee_and_supersede_chain(self, api):
        """PRD §3.9: "The test-pressing revision gross is 45000 cents for every
        round beyond the first — zero when `tp_round` is one or less."
        PRD §3.4: "Supplying `REQUEST_REVISION` moves the pressing to
        `REVISION_REQUESTED`, cascades the order back `AWAITING_TP_APPROVAL` →
        `TOOLING`, supersedes the current tooling job and opens a fresh re-cut
        job with `round_number` one higher in `QUEUED`"
        PRD §3.4: "it increments the order's `tp_round`, stamps the new
        TestPressing's `round_number` with that value, and supersedes any prior
        round still resting in `REVISION_REQUESTED`."

        Design: Corner/calculations/tp_revision_fee_and_supersede_chain
        """
        world = setup_world()
        cust_id = world["customer"]["id"]
        order = create_order(world["release"]["id"], quantity_ordered=1000)
        order = quote_order(order)
        order = confirm_order(order, cust_id)
        job1 = start_tooling(order["id"])
        drive_tooling_to_stamper_ready(job1["id"], world["bath"]["id"])
        tp1 = produce_test_pressing(order["id"])
        tp1 = ship_test_pressing(tp1["id"])
        tp1 = review_test_pressing(tp1["id"], cust_id, "REQUEST_REVISION",
                                   notes="sibilance on side B")
        assert tp1["status"] == "REVISION_REQUESTED"

        jobs = validate_success(api.list_order_tooling_jobs(order["id"], CSR), 200)
        assert len(jobs) == 2
        assert jobs[0]["status"] == "SUPERSEDED", (
            "the revision must supersede the round-1 tooling job"
        )
        assert jobs[1]["status"] == "QUEUED"
        assert jobs[1]["round_number"] == 2

        drive_tooling_to_stamper_ready(jobs[1]["id"], world["bath"]["id"],
                                       plating_start=8, plating_end=12)
        tp2 = produce_test_pressing(order["id"])
        assert tp2["round_number"] == 2
        tps = validate_success(api.list_order_test_pressings(order["id"], CSR), 200)
        assert tps[0]["status"] == "SUPERSEDED", (
            "creating the round-2 pressing must supersede the REVISION_REQUESTED round"
        )
        tp2 = ship_test_pressing(tp2["id"])
        tp2 = review_test_pressing(tp2["id"], cust_id, "APPROVE")
        assert tp2["status"] == "APPROVED"

        order = get_order(order["id"])
        assert order["tp_round"] == 2
        order = schedule_order(order, world["line"]["id"], planned_units=1000)
        press_run(order["id"], slot_date="2026-08-10")
        qc = file_qc_report(order["id"], 1000, 30)
        decide_qc_report(qc["id"], "ACCEPT", "NONE")
        invoice = issue_standard_invoice(order["id"])
        # 439455 base + 45000 revision fee for the second round.
        assert invoice["net_cents"] == 484455
        assert invoice["lines"][4]["gross_cents"] == 45000, (
            "the fifth line (test-pressing revision) must carry the 45000 fee"
        )


class TestSingleInvoicePerOrder:
    def test_second_standard_invoice_rejected(self, api):
        """PRD §3.9: "Issuing the final invoice is a `BillingClerk` action on a
        `COMPLETED` order — any other production state is rejected with
        `ERR_INVOICE_INVALID_STATE`, and exactly one `STANDARD` invoice may
        ever exist for an order, a second attempt drawing
        `ERR_ORDER_INVALID_STATE`."

        Design: Corner/state_machines/second_standard_invoice_rejected
        """
        world = setup_world()
        done = create_completed_order(world, units_pressed=1000, units_rejected=30)
        issue_standard_invoice(done["order"]["id"])

        r1 = api.issue_invoice(done["order"]["id"], BILLING)
        validate_error(r1, ApiErrorId.ERR_ORDER_INVALID_STATE)
        r2 = api.issue_invoice(done["order"]["id"], BILLING)
        validate_error(r2, ApiErrorId.ERR_ORDER_INVALID_STATE)

        invoices, _m = validate_paginated(
            api.list_invoices(CSR, params={"press_order_id": done["order"]["id"]})
        )
        standard = [i for i in invoices if i["kind"] == "STANDARD"]
        assert len(standard) == 1, "exactly one STANDARD invoice may exist per order"


class TestPaymentBalanceCap:
    def _invoiced_439455(self):
        world = setup_world()
        _q, order_id, invoice = _invoice_for(world, 1000, 30)
        assert invoice["net_cents"] == 439455
        return world, order_id, invoice

    def test_payment_and_memo_over_balance_rejected(self, api):
        """PRD §3.9: "A payment of `amount_cents` against an `ISSUED` or
        `PARTIALLY_PAID` invoice (any other status is
        `ERR_INVOICE_INVALID_STATE`) adds to `paid_cents` and may not exceed
        the remaining balance — `net_cents` less `paid_cents` less
        `credited_cents` — on pain of `ERR_PAYMENT_EXCEEDS_BALANCE`"
        PRD §3.9: "A credit memo of `amount_cents` with a `reason` posts a new
        self-referential Invoice row of `kind` `CREDIT_MEMO` whose
        `parent_invoice_id` names the invoice it credits, adds the amount to
        the parent's `credited_cents` under the same remaining-balance cap"

        Design: Corner/validations/payment_and_memo_over_balance_rejected
        """
        _world, _oid, invoice = self._invoiced_439455()

        r1 = api.post_payment(invoice["id"], {"amount_cents": 439456}, BILLING)
        validate_error(r1, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        r2 = api.post_credit_memo(
            invoice["id"], {"amount_cents": 439456, "reason": "too much"}, BILLING
        )
        validate_error(r2, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        paid = validate_success(
            api.post_payment(invoice["id"], {"amount_cents": 439455}, BILLING), 200
        )
        assert paid["status"] == "PAID", (
            "a payment of exactly the remaining balance must close the invoice"
        )

    def test_invoice_money_conservation_partial_and_memo(self, api):
        """PRD §3.9: "a payment short of the remaining balance moves the
        invoice `ISSUED` → `PARTIALLY_PAID` (mirroring the order's billing
        dimension `INVOICED` → `PARTIALLY_PAID`)"
        PRD §3.9: "A credit memo of `amount_cents` with a `reason` posts a new
        self-referential Invoice row of `kind` `CREDIT_MEMO` whose
        `parent_invoice_id` names the invoice it credits, adds the amount to
        the parent's `credited_cents` under the same remaining-balance cap"

        Design: Difficulty/compensating_invariant/invoice_money_conservation_pay_and_credit
        """
        world, order_id, invoice = self._invoiced_439455()

        partial = validate_success(
            api.post_payment(invoice["id"], {"amount_cents": 100000}, BILLING), 200
        )
        assert partial["status"] == "PARTIALLY_PAID"
        assert partial["paid_cents"] == 100000
        order = get_order(order_id)
        assert order["billing_status"] == "PARTIALLY_PAID"

        memo = validate_success(
            api.post_credit_memo(
                invoice["id"],
                {"amount_cents": 39455, "reason": "scratch goodwill"},
                BILLING,
            ),
            201,
        )
        assert memo["kind"] == "CREDIT_MEMO"
        assert memo["parent_invoice_id"] == invoice["id"]
        assert memo["net_cents"] == 39455

    def test_invoice_money_conservation_paid_out(self, api):
        """PRD §3.9: "a payment short of the remaining balance moves the
        invoice `ISSUED` → `PARTIALLY_PAID` (mirroring the order's billing
        dimension `INVOICED` → `PARTIALLY_PAID`), and one that completes the
        balance moves it to `PAID` from either state (billing dimension to
        `PAID`)."
        PRD §3.9: "an order's billing dimension reaches its terminal states
        `PAID` or `CREDIT_CLOSED` only through these settlement events,
        independently of where production stands."

        Design: Difficulty/compensating_invariant/invoice_money_conservation_pay_and_credit
        """
        _world, order_id, invoice = self._invoiced_439455()
        validate_success(
            api.post_payment(invoice["id"], {"amount_cents": 100000}, BILLING), 200
        )
        validate_success(
            api.post_credit_memo(
                invoice["id"],
                {"amount_cents": 39455, "reason": "scratch goodwill"},
                BILLING,
            ),
            201,
        )
        final = validate_success(
            api.post_payment(invoice["id"], {"amount_cents": 300000}, BILLING), 200
        )
        assert final["status"] == "PAID"
        assert final["paid_cents"] == 400000
        assert final["credited_cents"] == 39455
        # Conservation: net 439455 == 400000 paid + 39455 credited exactly.
        assert final["net_cents"] == final["paid_cents"] + final["credited_cents"]

        order = get_order(order_id)
        assert order["billing_status"] == "PAID"
        assert order["production_status"] == "COMPLETED"


class TestRebateTierEvaluationOrder:
    def _setup_completed_gold_order(self, api):
        """GOLD customer; order quoted at a 5% snapshot and completed with
        970 accepted units; the customer is then revised down to STANDARD."""
        world = setup_world(customer_over={"discount_tier": "GOLD"})
        cust = world["customer"]
        staged = create_queued_order(world, quantity_ordered=1000)
        assert staged["order"]["discount_pct_snapshot"] == pytest.approx(0.05)
        order = schedule_order(staged["order"], world["line"]["id"],
                               planned_units=1000)
        press_run(order["id"], slot_date="2026-08-10")
        qc = file_qc_report(order["id"], 1000, 30)
        decide_qc_report(qc["id"], "ACCEPT", "NONE")
        # Downgrade the tier before invoicing.
        revised = validate_success(
            api.revise_credit_limit(
                cust["id"],
                {"new_credit_limit_cents": 100000000,
                 "discount_tier": "STANDARD",
                 "expected_customer_version": cust["version"]},
                CSR,
            ),
            200,
        )
        assert revised["discount_tier"] == "STANDARD"
        return world, order["id"], revised

    def test_invoice_uses_snapshot_after_tier_downgrade(self, api):
        """PRD §3.1: "a quote snapshots the customer's tier percentage at quote
        time (zero if the customer is `SUSPENDED` then), an invoice prices its
        lines from that snapshot — never from the customer's current tier"

        Design: Difficulty/combinatorial_formula/rebate_tier_evaluation_order_pinned
        """
        world, order_id, revised = self._setup_completed_gold_order(api)
        invoice = issue_standard_invoice(order_id)
        # 5% GOLD snapshot per line: 14010 + 1213 + 4750 + 2000 = 21973.
        assert invoice["discount_cents"] == 21973
        assert invoice["net_cents"] == 417482, (
            "the current 0% STANDARD tier must NOT be used on this invoice"
        )
        order = get_order(order_id)
        assert order["discount_pct_snapshot"] == pytest.approx(0.05)

    def test_trailing_billed_posts_after_issuance_forward_only(self, api):
        """PRD §3.1: "only after an invoice is issued does its `net_cents`
        accrue into `trailing_billed_cents`. That trailing total informs future
        tier assignments made by staff; it never re-rates an existing quote or
        invoice, and no retroactive recomputation of any kind is performed."

        Design: Difficulty/combinatorial_formula/rebate_tier_evaluation_order_pinned
        """
        world, order_id, _revised = self._setup_completed_gold_order(api)
        cust_id = world["customer"]["id"]

        before = validate_success(api.get_customer(cust_id, CSR), 200)
        assert before["trailing_billed_cents"] == 0, (
            "net_cents must not accrue before issuance"
        )

        invoice = issue_standard_invoice(order_id)
        after = validate_success(api.get_customer(cust_id, CSR), 200)
        assert after["trailing_billed_cents"] == invoice["net_cents"] == 417482

        # A new quote uses the current (STANDARD, 0%) tier forward only.
        order2 = create_order(world["release"]["id"], quantity_ordered=1000)
        quoted2 = quote_order(order2)
        assert quoted2["discount_pct_snapshot"] == 0
        assert quoted2["quote_discount_cents"] == 0
        assert quoted2["quote_total_cents"] == 448420
