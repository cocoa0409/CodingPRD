"""Pricing: dual-variant (provisional vs final) and combinatorial formulas.

Covers PRD §2.8 (dual-variant pricing), §3.11 (volume rebate evaluation
order), §2.8 (pinned per-line rounding), and the cold-chain surcharge tiers.
"""
from test_helpers import (
    FINANCE,
    TEST_USERS,
    api_client,
    confirm_delivery,
    create_scheduled_delivery,
    customs_decision,
    dispatch_delivery,
    get_success_data,
    make_officer_headers,
    setup_accepted_order,
    setup_invoiced_order,
)
from test_helpers.fixtures import (
    arrive_vessel_call,
    create_agent,
    create_catalog_item,
    create_draft_quotation,
    create_stock_lot,
    create_submitted_requisition,
    create_vessel_call,
    set_clock,
)

SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


# ===========================================================================
# dual_variant_calc / provisional_vs_final_pricing_duty_flip
# ===========================================================================

class TestProvisionalVsFinalPricingDutyFlip:
    def test_provisional_dutiable_while_customs_pending(self, api):
        """PRD §2.8: "The **provisional** variant runs at quotation creation and on
        every revise: quantities are the quoted quantities, duty-free eligibility is
        evaluated against the vessel call's *current* `customs_clearance_status` (so
        `PENDING` or `REJECTED` makes every line dutiable at quote time)".

        100 x WHISKY @ 5000, duty 20%, customs PENDING at quote time:
        base 500,000 + duty 100,000 = 600,000 subtotal; 4% rebate 24,000
        => provisional_total_cents == 576000.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_pricing_duty_flip
        """
        agent = create_agent(name="Agent Alpha")
        whisky = create_catalog_item(
            sku="WHISKY-01", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        )
        create_stock_lot(
            whisky["id"], lot_code="BW-1", storage_tier="BONDED_WAREHOUSE",
            received_qty=500, capacity_qty=0,
        )
        call = create_vessel_call(agent["id"], foreign_going=True)
        req = create_submitted_requisition(call["id"], whisky["id"], requested_qty=100)
        quo = create_draft_quotation(req["id"], whisky["id"], qty=100, unit_price_cents=5000)

        assert quo["provisional_total_cents"] == 576000, (
            f"Expected provisional total 576000 (dutiable at quote time), "
            f"got {quo['provisional_total_cents']}"
        )

    def test_final_duty_free_after_clearance_diverges(self, api):
        """PRD §2.8: "The **final** variant runs at invoice issuance: quantities are
        the delivered quantities per line (which may be lower after a shortage),
        duty-free eligibility is evaluated against the clearance status *at the
        moment of issuance*". PRD §2.8: "the two can legitimately diverge for
        identical quoted data."

        Same quoted data (100 x WHISKY @ 5000, delivered in full) priced
        provisionally while PENDING => 576,000; invoiced after CLEARED =>
        duty-free: total_duty_cents == 0, subtotal 500,000, rebate 20,000,
        total_cents == 480,000.

        Design: Difficulty/dual_variant_calc/provisional_vs_final_pricing_duty_flip
        """
        ctx = setup_accepted_order(
            qty=100, unit_price_cents=5000,
            item_overrides=dict(
                sku="WHISKY-01", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ),
            lot_overrides=dict(lot_code="BW-1", storage_tier="BONDED_WAREHOUSE",
                               received_qty=500, capacity_qty=0),
            call_overrides=dict(foreign_going=True),
        )
        officer = make_officer_headers(ctx["call"]["id"])
        # PRD §3.6 customs gate: a delivery carrying bonded_eligible items may
        # only be scheduled while the call's customs_clearance_status is
        # CLEARED — clear customs first, then schedule. The quotation was
        # already priced provisionally while PENDING inside
        # setup_accepted_order, so the divergence this test asserts is intact.
        customs_decision(ctx["call"]["id"], "CLEARED")
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 100)
        dispatch_delivery(delivery["id"])
        set_clock("2026-08-10T12:00:00Z")
        confirm_delivery(delivery["id"], ctx["item"]["id"], 100, officer)
        invoice = get_success_data(api_client.create_invoice(
            ctx["order"]["id"], {"fx_rate_to_settlement": 1.0}, FINANCE,
        ))

        assert invoice["total_duty_cents"] == 0, (
            "Duty-free at issuance: CLEARED + foreign_going + bonded_eligible"
        )
        assert invoice["subtotal_cents"] == 500000
        assert invoice["rebate_cents"] == 20000
        assert invoice["total_cents"] == 480000
        assert ctx["quotation"]["provisional_total_cents"] == 576000
        assert ctx["quotation"]["provisional_total_cents"] != invoice["total_cents"]


# ===========================================================================
# dual_variant_calc / committed_vs_settled_agent_exposure
# ===========================================================================

class TestCommittedVsSettledAgentExposure:
    def test_committed_counts_uninvoiced_order_settled_does_not(self, api):
        """PRD §2.7: "`committed_exposure_cents` is the sum of `total_cents` over
        the agent's orders whose `payment_status` is `UNINVOICED` and whose
        `fulfillment_status` is one of `OPEN`, `PARTIALLY_DELIVERED`, or
        `DELIVERED`, plus the `outstanding_cents` of the agent's invoices in
        `ISSUED` or `PARTIALLY_PAID` status. `settled_exposure_cents` is the
        narrower figure: only the `outstanding_cents` of those same `ISSUED` or
        `PARTIALLY_PAID` invoices."

        Order accepted (100 x WHISKY @ 5000, customs PENDING => dutiable
        provisional 576,000 frozen), no invoice: committed == 576,000,
        settled == 0.

        Design: Difficulty/dual_variant_calc/committed_vs_settled_agent_exposure
        """
        ctx = setup_accepted_order(
            qty=100, unit_price_cents=5000,
            item_overrides=dict(
                sku="WHISKY-02", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ),
            lot_overrides=dict(lot_code="BW-2", storage_tier="BONDED_WAREHOUSE",
                               received_qty=500, capacity_qty=0),
            call_overrides=dict(foreign_going=True),
        )
        agent = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert agent["committed_exposure_cents"] == 576000, (
            f"Expected committed 576000 (frozen dutiable provisional), "
            f"got {agent['committed_exposure_cents']}"
        )
        assert agent["settled_exposure_cents"] == 0

    def test_settled_catches_up_after_invoicing(self, api):
        """PRD §2.7: "The two figures diverge whenever an accepted order has not
        yet been invoiced: the committed leg counts the order total, the settled
        leg does not." PRD §3.9: "the agent's exposures are recomputed — the
        order leg leaves the committed sum and the invoice leg joins both sums."

        After delivering and invoicing the same order (clearance revoked to
        REJECTED before issuance => final pricing dutiable: subtotal 600,000,
        rebate 24,000, total 576,000 at fx 1.0), the invoice's outstanding
        576,000 joins the settled leg while the order leg leaves committed.

        Setup note: PRD §3.6's customs gate forbids scheduling a bonded
        delivery while clearance is PENDING, and PRD §3.8 permits
        CLEARED → REJECTED, so the flow clears customs for scheduling and
        revokes it before invoicing — duty-free eligibility is evaluated "at
        the moment of issuance" (PRD §2.8), where REJECTED prices dutiable.

        Design: Difficulty/dual_variant_calc/committed_vs_settled_agent_exposure
        """
        ctx = setup_accepted_order(
            qty=100, unit_price_cents=5000,
            item_overrides=dict(
                sku="WHISKY-02", name="Scotch Whisky 1L", category="BONDED",
                bonded_eligible=True, requires_cold_chain=False,
                base_price_cents=5000, duty_rate_pct=20,
            ),
            lot_overrides=dict(lot_code="BW-2", storage_tier="BONDED_WAREHOUSE",
                               received_qty=500, capacity_qty=0),
            call_overrides=dict(foreign_going=True),
        )
        officer = make_officer_headers(ctx["call"]["id"])
        customs_decision(ctx["call"]["id"], "CLEARED")
        delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], 100)
        dispatch_delivery(delivery["id"])
        confirm_delivery(delivery["id"], ctx["item"]["id"], 100, officer)
        customs_decision(ctx["call"]["id"], "REJECTED")
        ctx["invoice"] = get_success_data(api_client.create_invoice(
            ctx["order"]["id"], {"fx_rate_to_settlement": 1.0}, FINANCE,
        ))
        agent = get_success_data(api_client.get_ship_agent(ctx["agent"]["id"], FINANCE))
        assert ctx["invoice"]["total_cents"] == 576000
        assert agent["settled_exposure_cents"] == 576000, (
            "After issuance the invoice's outstanding joins the settled leg"
        )
        assert agent["committed_exposure_cents"] == 576000, (
            "Order leg leaves committed; invoice leg joins committed: still 576000"
        )


# ===========================================================================
# combinatorial_formula / layered_line_pricing_duty_cold_tiers
# ===========================================================================

class TestLayeredLinePricingDutyColdTiers:
    def test_duty_plus_tiered_cold_surcharge_composes(self, api):
        """PRD §2.8: "the cold-chain duration is the whole-hour count of the
        *planned* port stay between `scheduled_eta` and `scheduled_etd`." PRD
        §2.5: "Cold-chain hours are whole hours computed as the floor of elapsed
        seconds divided by 3600, clamped at zero if the interval is negative."

        FISH line: qty 40 @ 2500, duty 5% (bonded_eligible false => always
        dutiable), cold-chain over a 100-hour planned stay straddling the 72h
        kink => per-unit cold 5*72 + 12*28 = 696; line = 100,000 + 5,000 +
        40*696 = 132,840; subtotal < 500,000 => rebate 0.

        Design: Difficulty/combinatorial_formula/layered_line_pricing_duty_cold_tiers
        """
        agent = create_agent(name="Agent Gamma")
        fish = create_catalog_item(
            sku="FISH-01", name="Frozen Salmon 1kg", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=True,
            base_price_cents=2500, duty_rate_pct=5,
        )
        create_stock_lot(
            fish["id"], lot_code="CS-1", storage_tier="COLD_STORE",
            received_qty=1000, capacity_qty=1000,
        )
        call = create_vessel_call(agent["id"], foreign_going=True)
        req = create_submitted_requisition(call["id"], fish["id"], requested_qty=40)
        quo = create_draft_quotation(req["id"], fish["id"], qty=40, unit_price_cents=2500)

        assert quo["provisional_total_cents"] == 132840, (
            f"Expected 132840 = 100000 base + 5000 duty + 27840 cold; "
            f"got {quo['provisional_total_cents']}"
        )

    def test_cold_surcharge_scales_with_qty_and_hours(self, api):
        """PRD §2.8 (provisional variant): "the cold-chain duration is the
        whole-hour count of the *planned* port stay between `scheduled_eta` and
        `scheduled_etd`." The same FISH item quoted for a 20-hour stay prices the
        cold surcharge at the tier-1 rate only (5 cents/hour/unit), a different
        observable value than the 100-hour tier-straddling computation.

        10 x FISH @ 2500 over exactly 20 planned hours: base 25,000 + duty 1,250
        (5%) + cold 10 * (5*20) = 1,000 => provisional_total_cents == 27,250.

        Design: Difficulty/combinatorial_formula/layered_line_pricing_duty_cold_tiers
        """
        agent = create_agent(name="Agent Gamma-2")
        fish = create_catalog_item(
            sku="FISH-01B", name="Frozen Salmon 1kg", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=True,
            base_price_cents=2500, duty_rate_pct=5,
        )
        create_stock_lot(
            fish["id"], lot_code="CS-1B", storage_tier="COLD_STORE",
            received_qty=1000, capacity_qty=1000,
        )
        call = create_vessel_call(
            agent["id"],
            scheduled_eta="2026-08-10T08:00:00Z",
            scheduled_etd="2026-08-11T04:00:00Z",  # exactly 20 hours
        )
        req = create_submitted_requisition(call["id"], fish["id"], requested_qty=10)
        quo = create_draft_quotation(req["id"], fish["id"], qty=10, unit_price_cents=2500)

        # base 25,000 + duty 1,250 + cold 10*100 = 27,250
        assert quo["provisional_total_cents"] == 27250, (
            f"Expected 27250 = 25000 base + 1250 duty + 1000 cold; "
            f"got {quo['provisional_total_cents']}"
        )


# ===========================================================================
# combinatorial_formula / invoice_per_line_rounding_order
# ===========================================================================

class TestInvoicePerLineRoundingOrder:
    def test_per_line_duty_rounding_then_sum(self, api):
        """PRD §2.8: "Rounding order is pinned: every line is fully computed and
        rounded at its duty step before any summation, then the subtotal is the
        sum of those rounded line totals. Summing unrounded components and
        rounding once at the end produces different cents when several lines
        carry fractional duty and is therefore forbidden."

        Two lines of 1 unit each at 333 cents with 5% duty: per-line duty
        round_half_up(333*0.05)=17 each => total_duty_cents 34; the forbidden
        sum-then-round order would give round_half_up(666*0.05)=33.

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
        """
        agent = create_agent(name="Agent Delta")
        rice_a = create_catalog_item(
            sku="RICE-A", name="Rice 5kg A", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=333, duty_rate_pct=5,
        )
        rice_b = create_catalog_item(
            sku="RICE-B", name="Rice 5kg B", category="PROVISIONS",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=333, duty_rate_pct=5,
        )
        create_stock_lot(rice_a["id"], lot_code="DS-1", received_qty=100)
        create_stock_lot(rice_b["id"], lot_code="DS-2", received_qty=100)
        call = create_vessel_call(agent["id"])
        officer = make_officer_headers(call["id"])
        req = get_success_data(api_client.create_requisition(call["id"], {
            "title": "Dry stores",
            "lines": [
                {"catalog_item_id": rice_a["id"], "requested_qty": 1,
                 "allows_substitution": False},
                {"catalog_item_id": rice_b["id"], "requested_qty": 1,
                 "allows_substitution": False},
            ],
        }, officer))
        get_success_data(api_client.submit_requisition(req["id"], officer))
        quo = create_draft_quotation(req["id"], rice_a["id"], line_overrides=[
            {"catalog_item_id": rice_a["id"], "qty": 1, "unit_price_cents": 333,
             "is_substitution": False},
            {"catalog_item_id": rice_b["id"], "qty": 1, "unit_price_cents": 333,
             "is_substitution": False},
        ])
        get_success_data(api_client.send_quotation(quo["id"], SALES))
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])
        order = get_success_data(api_client.accept_quotation(quo["id"], officer))
        delivery = get_success_data(api_client.create_delivery(order["id"], {
            "window_start": "2026-08-10T10:00:00Z",
            "window_end": "2026-08-10T14:00:00Z",
            "lines": [
                {"catalog_item_id": rice_a["id"], "qty": 1},
                {"catalog_item_id": rice_b["id"], "qty": 1},
            ],
        }, WAREHOUSE))
        dispatch_delivery(delivery["id"])
        get_success_data(api_client.confirm_delivery(delivery["id"], {
            "receiver_name": "Chief Cook", "signature_ref": "sig-004",
            "confirmed_lines": [
                {"catalog_item_id": rice_a["id"], "qty": 1},
                {"catalog_item_id": rice_b["id"], "qty": 1},
            ],
        }, officer))
        invoice = get_success_data(api_client.create_invoice(
            order["id"], {"fx_rate_to_settlement": 1.0}, FINANCE,
        ))
        assert invoice["total_duty_cents"] == 34, (
            f"Per-line rounding must yield 17 + 17 = 34, got {invoice['total_duty_cents']}"
        )
        assert invoice["subtotal_cents"] == 700
        assert invoice["total_cents"] == 700

    def test_single_line_fractional_duty_rounds_half_up(self, api):
        """PRD §2.5: "Wherever a multiplication or division produces a fraction —
        duty computation, volume rebate, currency conversion, credit-note
        pro-rating, restocking fee — the value is rounded half-up to whole cents
        at the pinned step and nowhere else inside the same line computation."
        One line of 1 x 333 @ 5% duty: duty round_half_up(16.65) = 17, line
        total 350.

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order
        """
        ctx = setup_invoiced_order(
            qty=1, unit_price_cents=333,
            item_overrides=dict(
                sku="RICE-A1", name="Rice 5kg A", category="PROVISIONS",
                bonded_eligible=False, requires_cold_chain=False,
                base_price_cents=333, duty_rate_pct=5,
            ),
            lot_overrides=dict(lot_code="DS-1B", received_qty=100),
        )
        assert ctx["invoice"]["total_duty_cents"] == 17
        assert ctx["invoice"]["subtotal_cents"] == 350
        assert ctx["invoice"]["total_cents"] == 350


# ===========================================================================
# combinatorial_formula / volume_rebate_evaluation_order_pinned
# ===========================================================================

class TestVolumeRebateEvaluationOrderPinned:
    def test_tier_read_from_pre_rebate_subtotal(self, api):
        """PRD §3.11: "Then the tier is read from that pre-rebate subtotal: a
        subtotal of at least 1,000,000 cents earns 7 percent; a subtotal of at
        least 500,000 cents but below 1,000,000 earns 4 percent". "The tier is
        **never** re-evaluated on the post-rebate total, even though that total
        can drop below the tier boundary — a 500,000-cent subtotal yields a
        20,000-cent rebate and a 480,000-cent total, and the 4 percent tier
        stands."

        100 x WHISKY @ 5000 duty-free (customs CLEARED before quotation):
        subtotal exactly 500,000 => rebate 20,000 => provisional total 480,000.

        Design: Difficulty/combinatorial_formula/volume_rebate_evaluation_order_pinned
        """
        agent = create_agent(name="Agent Epsilon")
        whisky = create_catalog_item(
            sku="WHISKY-05", name="Scotch Whisky 1L", category="BONDED",
            bonded_eligible=True, requires_cold_chain=False,
            base_price_cents=5000, duty_rate_pct=20,
        )
        create_stock_lot(whisky["id"], lot_code="BW-5", storage_tier="BONDED_WAREHOUSE",
                         received_qty=500, capacity_qty=0)
        call = create_vessel_call(agent["id"], foreign_going=True)
        set_clock("2026-08-10T08:00:00Z")
        arrive_vessel_call(call["id"])
        customs_decision(call["id"], "CLEARED")
        req = create_submitted_requisition(call["id"], whisky["id"], requested_qty=100)
        quo = create_draft_quotation(req["id"], whisky["id"], qty=100, unit_price_cents=5000)

        assert quo["provisional_total_cents"] == 480000, (
            f"Pre-rebate subtotal 500000 >= 500000 inclusive => 4% rebate 20000; "
            f"expected 480000, got {quo['provisional_total_cents']}"
        )

    def test_one_cent_below_tier_gets_no_rebate(self, api):
        """PRD §3.11: "The boundary is inclusive — a subtotal of exactly 500,000
        cents earns 4 percent." A subtotal one cent below the 500,000 tier earns
        nothing: a single DECK line at 499,999 cents (duty 0, not cold, not
        bonded) => rebate 0 => total equals subtotal.

        Design: Difficulty/combinatorial_formula/volume_rebate_evaluation_order_pinned
        """
        agent = create_agent(name="Agent Epsilon-2")
        deck = create_catalog_item(
            sku="DECK-BELOW", name="Mooring line", category="DECK",
            bonded_eligible=False, requires_cold_chain=False,
            base_price_cents=499999, duty_rate_pct=0,
        )
        create_stock_lot(deck["id"], lot_code="DS-B1", received_qty=10)
        call = create_vessel_call(agent["id"])
        req = create_submitted_requisition(call["id"], deck["id"], requested_qty=1)
        quo = create_draft_quotation(req["id"], deck["id"], qty=1, unit_price_cents=499999)

        assert quo["provisional_total_cents"] == 499999, (
            "Subtotal 499,999 is below the inclusive 500,000 tier => rebate 0, "
            "total unchanged"
        )
