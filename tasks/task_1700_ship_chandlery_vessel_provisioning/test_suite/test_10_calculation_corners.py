"""Calculation corner cases (corner-design §calculations).

Cold-surcharge 72h tier kink, rebate tier-2 boundary, invoice FX conversion +
due date, payment tolerance write-off, and exposure input-set filtering.
"""
from test_helpers import (
    FINANCE,
    TEST_USERS,
    api_client,
    get_success_data,
    make_clerk_headers,
    make_officer_headers,
    setup_accepted_order,
    setup_invoiced_order,
    validate_success,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    confirm_delivery,
    create_agent,
    create_catalog_item,
    create_draft_quotation,
    create_scheduled_delivery,
    create_sent_quotation,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    customs_decision,
    dispatch_delivery,
    pay_invoice,
    set_clock,
)

OPS = TEST_USERS["ops_headers"]


class TestColdSurchargeTierBoundaryExactly72h:
    def _quote_fish(self, agent, fish, suffix, etd):
        call = create_vessel_call(
            agent["id"], vessel_name=f"MV Iris{suffix}", scheduled_etd=etd,
        )
        req = create_submitted_requisition(call["id"], fish["id"], requested_qty=10)
        return create_draft_quotation(req["id"], fish["id"], qty=10, unit_price_cents=2500)

    def test_cold_surcharge_tier_boundary_exactly_72h(self, api):
        """PRD §2.8: "the cold-chain duration is the whole-hour count of the
        *planned* port stay between `scheduled_eta` and `scheduled_etd`". The
        pinned cold rate is 5 cents/hour/unit up to 72h and 5*72 + 12*(h-72)
        beyond it. At exactly 72 planned hours: cold/unit 5*72 = 360 => 10 units
        @ 2500 base with duty 0% => 25,000 + 3,600 = 28,600.

        Design: Corner/calculations/cold_surcharge_tier_boundary_exactly_72h
        """
        agent = create_agent(name="Agent AI")
        fish = create_catalog_item(
            sku="FISH-C10", name="Frozen Salmon 1kg", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=True,
            base_price_cents=2500, duty_rate_pct=0,
        )
        create_stock_lot(fish["id"], lot_code="CS-C10", storage_tier="COLD_STORE",
                         received_qty=10000, capacity_qty=10000)
        quo72 = self._quote_fish(agent, fish, "72", "2026-08-13T08:00:00Z")  # 72h
        assert quo72["provisional_total_cents"] == 28600, (
            f"base 25000 + cold 10*360; got {quo72['provisional_total_cents']}"
        )

    def test_cold_surcharge_one_hour_past_kink(self, api):
        """PRD §2.8 (provisional variant, planned-stay hours) with the pinned
        tiered cold rate: at 73 planned hours the per-unit cold rate is
        5*72 + 12*1 = 372; 10 units @ 2500 duty 0% => 25,000 + 3,720 = 28,720.
        Exactly one hour past the kink adds 10 x 12 = 120 over the 72h figure.

        Design: Corner/calculations/cold_surcharge_tier_boundary_exactly_72h
        """
        agent = create_agent(name="Agent AI")
        fish = create_catalog_item(
            sku="FISH-C10", name="Frozen Salmon 1kg", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=True,
            base_price_cents=2500, duty_rate_pct=0,
        )
        create_stock_lot(fish["id"], lot_code="CS-C10", storage_tier="COLD_STORE",
                         received_qty=10000, capacity_qty=10000)
        quo73 = self._quote_fish(agent, fish, "73", "2026-08-13T09:00:00Z")  # 73h
        assert quo73["provisional_total_cents"] == 28720, (
            f"base 25000 + cold 10*372; got {quo73['provisional_total_cents']}"
        )


class TestVolumeRebateTier2AtOneMillion:
    def test_volume_rebate_tier2_at_one_million(self, api):
        """PRD §3.11: "a subtotal of at least 1,000,000 cents earns 7 percent".
        200 x WHISKY @ 5000 duty-free (customs CLEARED before quotation) =>
        subtotal exactly 1,000,000 at the inclusive tier-2 boundary => rebate
        70,000 => provisional total 930,000.

        Design: Corner/calculations/volume_rebate_tier2_at_one_million
        """
        agent = create_agent(name="Agent AJ", credit_limit_cents=50000000)
        whisky = create_catalog_item(
            sku="WHISKY-C11", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        )
        create_stock_lot(whisky["id"], lot_code="BW-C11", storage_tier="BONDED_WAREHOUSE",
                         received_qty=1000, capacity_qty=0)
        call = create_vessel_call(agent["id"], vessel_name="MV Juno", foreign_going=True)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])
        customs_decision(call["id"], "CLEARED")
        req = create_submitted_requisition(call["id"], whisky["id"], requested_qty=200)
        quo = create_draft_quotation(req["id"], whisky["id"], qty=200, unit_price_cents=5000)
        assert quo["provisional_total_cents"] == 930000, (
            f"subtotal 1,000,000 => 7% rebate 70,000; got {quo['provisional_total_cents']}"
        )


class TestInvoiceFxConversionAndDueDate:
    def test_invoice_fx_conversion_and_due_date(self, api):
        """PRD §3.9: "`total_cents` converts to settlement cents by multiplying
        `total_usd_cents` by `fx_rate_to_settlement` and rounding half-up" and
        "`due_date` is `issued_at` plus the agent's `payment_terms_days`".
        12,345 USD cents at fx 0.855: 12,345 x 0.855 = 10,554.975 ->
        round_half_up 10,555 EUR cents. Invoice issued at logical clock
        2026-08-10T12:00:00Z with a 14-day agent => due 2026-08-24T12:00:00Z.

        Design: Corner/calculations/invoice_fx_conversion_and_due_date
        """
        ctx = setup_invoiced_order(
            qty=1, unit_price_cents=12345, fx_rate_to_settlement=0.855,
            agent_overrides=dict(name="Agent AK", settlement_currency="EUR",
                                 payment_terms_days=14),
            item_overrides=dict(sku="DECK-C12", name="Mooring line", category="DECK",
                                base_price_cents=12345, duty_rate_pct=0),
            lot_overrides=dict(lot_code="DS-C12", received_qty=100),
            invoice_clock="2026-08-10T12:00:00Z",
        )
        invoice = ctx["invoice"]
        assert invoice["total_usd_cents"] == 12345
        assert invoice["total_cents"] == 10555, (
            f"round_half_up(12345 x 0.855 = 10554.975) = 10555; got {invoice['total_cents']}"
        )
        assert invoice["due_date"] == "2026-08-24T12:00:00Z", (
            f"issued_at 2026-08-10T12:00:00Z + 14 days; got {invoice['due_date']}"
        )


class TestPaymentFxWriteoffWithinToleranceClosesInvoice:
    def _fresh_invoice(self, vessel_name, imo_number):
        return setup_invoiced_order(
            qty=1000, unit_price_cents=120, fx_rate_to_settlement=1.0,
            agent_overrides=dict(name="Agent AL"),
            item_overrides=dict(sku="WATER-C13", name="Water 1L"),
            lot_overrides=dict(lot_code="DS-C13", received_qty=100000),
            call_overrides=dict(vessel_name=vessel_name, imo_number=imo_number),
        )

    def test_payment_30_cents_short_closes_with_writeoff(self, api):
        """PRD §3.10: "If the delta lands within the inclusive band of minus 50 to
        plus 50 cents, the invoice closes: it becomes `PAID`, `outstanding_cents`
        becomes zero, and the difference is booked as `fx_writeoff_cents` on the
        invoice — a positive write-off forgives an underpayment". Payment
        119,970 against a 120,000 invoice (30 short) => PAID, writeoff 30,
        outstanding 0.

        Design: Corner/calculations/payment_fx_writeoff_within_tolerance_closes_invoice
        """
        ctx = self._fresh_invoice("MV Leto A", "9074772")
        pay_invoice(ctx["invoice"]["id"], ctx["agent"]["id"], 119970, currency="USD")
        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["status"] == "PAID"
        assert invoice["fx_writeoff_cents"] == 30
        assert invoice["outstanding_cents"] == 0

    def test_payment_51_cents_short_stays_partially_paid(self, api):
        """PRD §3.10: "If the new paid figure still falls short of outstanding by
        more than 50 cents, the invoice moves to `PARTIALLY_PAID` and
        `outstanding_cents` simply decreases by the converted amount." Payment
        119,949 against 120,000 (51 short) => PARTIALLY_PAID, outstanding 51,
        no write-off.

        Design: Corner/calculations/payment_fx_writeoff_within_tolerance_closes_invoice
        """
        ctx = self._fresh_invoice("MV Leto B", "9074773")
        pay_invoice(ctx["invoice"]["id"], ctx["agent"]["id"], 119949, currency="USD")
        invoice = get_success_data(api_client.get_invoice(ctx["invoice"]["id"], FINANCE))
        assert invoice["status"] == "PARTIALLY_PAID"
        assert invoice["outstanding_cents"] == 51
        assert invoice["fx_writeoff_cents"] == 0, "No write-off outside the band"


class TestInputSetFilteringExposureExcludesTerminal:
    def test_input_set_filtering_exposure_excludes_terminal(self, api):
        """PRD §2.7: "Cancelled orders and `VOID`, `PAID`, or `CREDITED` invoices
        contribute nothing to either figure." Two orders on one agent: order-1
        delivered + invoiced + paid in full (120,000); order-2 (48,000)
        accepted then cancelled. Both committed and settled exposure are 0 —
        terminal rows are filtered out, not merely zero-valued.

        Design: Corner/calculations/input_set_filtering_exposure_excludes_terminal
        """
        agent = create_agent(name="Agent AM")
        water = create_catalog_item(
            sku="WATER-C14", name="Water 1L", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=120, duty_rate_pct=0,
        )
        lot = create_stock_lot(water["id"], lot_code="DS-C14", received_qty=100000)

        # Order 1 on the shared agent: delivered + invoiced + paid in full.
        ctx1 = setup_accepted_order(
            qty=1000, unit_price_cents=120,
            agent=agent, item=water, lot=lot,
            call_overrides=dict(vessel_name="MV Maia"),
        )
        delivery1 = create_scheduled_delivery(ctx1["order"]["id"], ctx1["item"]["id"], 1000)
        dispatch_delivery(delivery1["id"])
        confirm_delivery(delivery1["id"], ctx1["item"]["id"], 1000,
                         make_officer_headers(ctx1["call"]["id"]))
        invoice1 = get_success_data(api_client.create_invoice(
            ctx1["order"]["id"], {"fx_rate_to_settlement": 1.0}, FINANCE,
        ))
        pay_invoice(invoice1["id"], agent["id"], 120000, currency="USD")

        # Order 2 on the same agent (400 x 120 = 48,000): accepted then cancelled.
        ctx2 = setup_accepted_order(
            qty=400, unit_price_cents=120,
            agent=agent, item=water, lot=lot,
            call_overrides=dict(vessel_name="MV Metis"),
        )
        get_success_data(api_client.cancel_order(ctx2["order"]["id"], OPS))

        agent_after = get_success_data(api_client.get_ship_agent(agent["id"], FINANCE))
        assert agent_after["committed_exposure_cents"] == 0, (
            "PAID invoice contributes 0 outstanding; CANCELLED order excluded"
        )
        assert agent_after["settled_exposure_cents"] == 0
