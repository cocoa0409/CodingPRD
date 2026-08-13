"""The close cascade: sold and unsold branches, invoice creation with the
aggregate and prorata revenue/contribution split, immediate consistency,
and the event financial summary's state filters."""
from test_helpers import (
    ADMIN,
    FO,
    api_client,
    assert_invoice,
    close_bidding,
    create_bidder,
    create_event,
    get_disposition_for_item,
    get_invoice_for_bundle,
    get_success_data,
    pay_invoice_in_full,
    place_bid,
    setup_bidding_open_scenario,
    setup_published_bundle,
    setup_sold_scenario,
    setup_valued_item,
    validate_paginated,
    validate_success,
)


def _two_bundle_close():
    """Event BIDDING_OPEN with two PUBLISHED bundles: an EXPERIENCE lot
    (FMV 40000) carrying one bid of 50000, and a PHYSICAL lot (FMV 30000)
    with no bids. Then the close cascade runs."""
    event = create_event()
    api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
    exp = setup_valued_item(event["id"], 40000, kind="EXPERIENCE",
                            title="Sailing day")
    phys = setup_valued_item(event["id"], 30000, kind="PHYSICAL",
                             title="Lamp")
    api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
    bundle_win = setup_published_bundle(event["id"], [exp["item"]["id"]],
                                        title="Sailing")
    bundle_none = setup_published_bundle(event["id"], [phys["item"]["id"]],
                                         title="Lamp")
    api_client.advance_gala_event(event["id"], ADMIN)  # BIDDING_OPEN
    bidder = create_bidder(event["id"])
    bid = place_bid(bundle_win["id"], 50000, bidder["id"])
    close_bidding(event["id"])
    invoice = get_invoice_for_bundle(bundle_win["id"])
    return {
        "event": event, "exp": exp, "phys": phys,
        "bundle_win": bundle_win, "bundle_none": bundle_none,
        "bidder": bidder, "bid": bid, "invoice": invoice,
    }


class TestCloseCascadeDepthFour:

    def test_close_cascade_sold_branch(self):
        """PRD section 3.6: "For each `PUBLISHED` bundle holding at least
        one `ACTIVE` bid, the bundle transitions to `SOLD`. The single
        remaining `ACTIVE` bid — all earlier bids are already `OUTBID`,
        because each accepted bid strictly exceeded the previous high —
        transitions to `WINNER`. An invoice is then created for that
        winning bid, carrying the event's `gala_event_id` from the bundle,
        the `bundle_id`, the winning `bidder_id`, the `winning_bid_cents`
        pinned at the bid amount, and the `pinned_bundle_fmv_cents` copied
        from the bundle's frozen `bundle_fmv_cents`; the new invoice
        starts with `payment_status` `UNPAID` and `fulfillment_status`
        `PENDING`. If the sold bundle contains at least one member item
        whose `kind` is `EXPERIENCE`, a certificate is created for that
        invoice in `PENDING_ISSUE` status"

        Design: Difficulty/transitive_cascade/close_bidding_cascade_depth_four
        """
        ctx = _two_bundle_close()
        bundle_win = get_success_data(
            api_client.get_bundle(ctx["bundle_win"]["id"], ADMIN))
        assert bundle_win["status"] == "SOLD", "hop 1: bundle sold"

        data, _meta = validate_paginated(
            api_client.list_bundle_bids(ctx["bundle_win"]["id"], ADMIN))
        assert data[0]["id"] == ctx["bid"]["id"]
        assert data[0]["status"] == "WINNER", "hop 2: active bid crowned"

        invoice = ctx["invoice"]
        assert_invoice(invoice)
        assert invoice["winning_bid_cents"] == 50000
        assert invoice["pinned_bundle_fmv_cents"] == 40000
        assert invoice["payment_status"] == "UNPAID"
        assert invoice["fulfillment_status"] == "PENDING", "hop 3"
        assert invoice["bidder_id"] == ctx["bidder"]["id"]

        certs, _m = validate_paginated(
            api_client.list_invoice_certificates(invoice["id"], ADMIN))
        assert len(certs) == 1
        assert certs[0]["status"] == "PENDING_ISSUE", \
            "hop 4: EXPERIENCE member spawns a pending certificate"

    def test_close_cascade_unsold_branch(self):
        """PRD section 3.6: "For each `PUBLISHED` bundle with no `ACTIVE`
        bid at all, the bundle transitions instead to `UNSOLD`, every
        member item moves from `CATALOGED` to `UNSOLD`, and one
        disposition is created per member item in `PROPOSED` status with
        its `decision` null."

        Design: Difficulty/transitive_cascade/close_bidding_cascade_depth_four
        """
        ctx = _two_bundle_close()
        bundle_none = get_success_data(
            api_client.get_bundle(ctx["bundle_none"]["id"], ADMIN))
        assert bundle_none["status"] == "UNSOLD"

        item = get_success_data(
            api_client.get_item(ctx["phys"]["item"]["id"], ADMIN))
        assert item["status"] == "UNSOLD"

        disposition = get_disposition_for_item(ctx["phys"]["item"]["id"])
        assert disposition["status"] == "PROPOSED"
        assert disposition["decision"] is None
        assert disposition["item_id"] == ctx["phys"]["item"]["id"]
        assert disposition["donor_id"] == ctx["phys"]["donor"]["id"]


class TestAggregateVsProrataSplit:

    def _trio_invoice_paid(self):
        """Three PHYSICAL items valued 33333/33333/33334 in one bundle
        (FMV 100000), winning bid 150000, invoice paid in full."""
        ctx = setup_sold_scenario(item_fmvs=[33333, 33333, 33334],
                                  bid_amount=150000)
        pay_invoice_in_full(ctx["invoice"], ctx["bidder"]["id"])
        invoice = get_success_data(
            api_client.get_invoice(ctx["invoice"]["id"], FO))
        return ctx, invoice

    def test_invoice_split_aggregate_and_prorata_values(self):
        """PRD section 3.6: "Under it, `revenue_portion_cents` is the
        smaller of `winning_bid_cents` and `pinned_bundle_fmv_cents`, and
        `contribution_portion_cents` is the excess of `winning_bid_cents`
        over `pinned_bundle_fmv_cents`, floored at zero." PRD section 3.6:
        "a bundle whose three member items carry approved values of 33333,
        33333, and 33334 cents, sold at a winning bid of 150000 cents,
        reports an aggregate contribution of 50000 cents but a prorata
        estimate of 50001 cents."

        Design: Difficulty/dual_variant_calc/invoice_split_aggregate_vs_prorata
        """
        _ctx, invoice = self._trio_invoice_paid()
        assert invoice["winning_bid_cents"] == 150000
        assert invoice["pinned_bundle_fmv_cents"] == 100000
        assert invoice["revenue_portion_cents"] == 100000
        assert invoice["contribution_portion_cents"] == 50000, "AGGREGATE"
        assert invoice["contribution_prorata_cents"] == 50001, (
            "PRORATA per-line round_half_up allocs 50000/50000/50001, "
            "excess 16667+16667+16667")
        assert invoice["payment_status"] == "PAID"

    def test_summary_reflects_split_variants_for_paid_invoice(self):
        """PRD section 3.9: "`recognized_revenue_cents`, the sum of
        `revenue_portion_cents` over invoices with `payment_status` `PAID`
        only; `recognized_contribution_cents`, the sum of
        `contribution_portion_cents` over `PAID` invoices only;
        `prorata_contribution_cents`, the sum of
        `contribution_prorata_cents` over `PAID` invoices only"

        Design: Difficulty/dual_variant_calc/invoice_split_aggregate_vs_prorata
        """
        ctx, _invoice = self._trio_invoice_paid()
        summary = get_success_data(
            api_client.get_event_summary(ctx["event"]["id"], FO))
        assert summary["recognized_revenue_cents"] == 100000
        assert summary["recognized_contribution_cents"] == 50000
        assert summary["prorata_contribution_cents"] == 50001
        assert summary["gross_winning_bids_cents"] == 150000
        assert summary["collected_cents"] == 150000


class TestProrataEvaluationOrder:

    def _trio_invoice(self):
        """Same trio fixture, invoice left UNPAID; the split is pinned at
        close and visible immediately."""
        ctx = setup_sold_scenario(item_fmvs=[33333, 33333, 33334],
                                  bid_amount=150000)
        invoice = get_success_data(
            api_client.get_invoice(ctx["invoice"]["id"], FO))
        return ctx, invoice

    def test_prorata_sum_not_reconciled_to_bid(self):
        """PRD section 3.6: "for each member item with an approved
        valuation at close, the item's allocation is the winning bid
        multiplied by that item's approved fair market value and divided
        by the pinned bundle fair market value, rounded half-up to whole
        cents per line; each line's contribution is the excess of its
        allocation over its own fair market value, floored at zero; and
        the prorata contribution is the sum of those per-line
        contributions. Per-line rounding is deliberately not reconciled
        back to the bid, so the sum of the allocations may differ from
        `winning_bid_cents` by a cent."

        Design: Difficulty/combinatorial_formula/prorata_evaluation_order_pinned
        """
        _ctx, invoice = self._trio_invoice()
        assert invoice["contribution_prorata_cents"] == 50001, (
            "allocs rhu(150000*33333/100000)=50000, "
            "rhu(150000*33333/100000)=50000, rhu(150000*33334/100000)="
            "50001 -> sum 150001 != 150000; excess 16667*3")
        assert invoice["contribution_portion_cents"] == 50000

    def test_prorata_basis_is_pinned_bundle_fmv(self):
        """PRD section 3.6: "the `pinned_bundle_fmv_cents` copied from the
        bundle's frozen `bundle_fmv_cents`". PRD section 3.6: "Under it,
        `revenue_portion_cents` is the smaller of `winning_bid_cents` and
        `pinned_bundle_fmv_cents`"

        Design: Difficulty/combinatorial_formula/prorata_evaluation_order_pinned
        """
        _ctx, invoice = self._trio_invoice()
        assert invoice["pinned_bundle_fmv_cents"] == 100000
        assert invoice["revenue_portion_cents"] == 100000
        assert invoice["winning_bid_cents"] == 150000


class TestQuidProQuoBoundary:

    def test_contribution_zero_when_bid_equals_fmv(self):
        """PRD section 3.6: "The quid-pro-quo boundary is exact: a winning
        bid precisely equal to the pinned fair market value yields a
        contribution of zero, because a contribution exists only when the
        winning bid is strictly greater than the pinned value."

        Design: Corner/calculations/contribution_zero_when_bid_equals_fmv
        """
        ctx = setup_sold_scenario(fmv_cents=40000, bid_amount=40000)
        invoice = get_success_data(
            api_client.get_invoice(ctx["invoice"]["id"], FO))
        assert invoice["winning_bid_cents"] == 40000
        assert invoice["pinned_bundle_fmv_cents"] == 40000
        assert invoice["revenue_portion_cents"] == 40000
        assert invoice["contribution_portion_cents"] == 0
        assert invoice["contribution_prorata_cents"] == 0


class TestImmediateConsistency:

    def test_close_cascade_immediately_visible(self):
        """PRD section 2.10: "The system maintains consistency across
        entity boundaries automatically, without requiring an explicit
        client request on each affected resource." and "advancing an event
        past the close of bidding rewrites bundles, bids, items, invoices,
        certificates, and dispositions in one transaction"

        Design: Corner/consistency_model/close_cascade_immediately_visible
        """
        ctx = setup_bidding_open_scenario(fmv_cents=40000, title="Vase")
        bidder = create_bidder(ctx["event"]["id"])
        place_bid(ctx["bundle"]["id"], 50000, bidder["id"])

        advance = validate_success(
            api_client.advance_gala_event(ctx["event"]["id"], ADMIN))
        assert advance["status"] == "BIDDING_CLOSED"

        data, _meta = validate_paginated(api_client.list_invoices(
            ADMIN, params={"bundle_id": ctx["bundle"]["id"]}))
        assert len(data) == 1
        invoice = data[0]
        assert invoice["contribution_portion_cents"] == 10000
        assert invoice["payment_status"] == "UNPAID"


class TestSummaryStateFilters:

    def test_summary_aggregation_state_filters(self):
        """PRD section 3.9: "`outstanding_cents`, the sum of each
        invoice's `winning_bid_cents` minus its `amount_paid_cents`, taken
        only over invoices with `payment_status` `UNPAID` or
        `PARTIALLY_PAID`; `written_off_cents`, the sum of
        `winning_bid_cents` over invoices with `payment_status`
        `WRITTEN_OFF`; `refunded_cents`, the same sum over invoices with
        `payment_status` `REFUNDED`" and "`unsold_item_count`, the count
        of the event's items in `UNSOLD` status; and
        `open_disposition_count`, the count of the event's dispositions in
        `PROPOSED` or `DONOR_NOTIFIED`."

        Design: Corner/calculations/summary_aggregation_state_filters
        """
        event = create_event()
        api_client.advance_gala_event(event["id"], ADMIN)  # SOLICITING
        parts = [setup_valued_item(event["id"], fmv)
                 for fmv in (25000, 15000, 30000, 20000, 10000)]
        api_client.advance_gala_event(event["id"], ADMIN)  # CATALOGING
        b1 = setup_published_bundle(
            event["id"], [parts[0]["item"]["id"], parts[1]["item"]["id"]],
            title="B1 pair")
        b2 = setup_published_bundle(event["id"], [parts[2]["item"]["id"]],
                                    title="B2")
        b3 = setup_published_bundle(event["id"], [parts[3]["item"]["id"]],
                                    title="B3")
        setup_published_bundle(event["id"], [parts[4]["item"]["id"]],
                               title="B4")
        api_client.advance_gala_event(event["id"], ADMIN)  # BIDDING_OPEN
        bidder = create_bidder(event["id"])
        place_bid(b1["id"], 50000, bidder["id"])
        place_bid(b2["id"], 40000, bidder["id"])
        place_bid(b3["id"], 25000, bidder["id"])
        close_bidding(event["id"])

        inv1 = get_invoice_for_bundle(b1["id"])
        inv3 = get_invoice_for_bundle(b3["id"])
        pay_invoice_in_full(inv1, bidder["id"])
        validate_success(api_client.write_off_invoice(inv3["id"], FO))

        summary = get_success_data(
            api_client.get_event_summary(event["id"], FO))
        assert summary["gross_winning_bids_cents"] == 115000
        assert summary["collected_cents"] == 50000
        assert summary["outstanding_cents"] == 40000, \
            "only UNPAID/PARTIALLY_PAID invoices contribute"
        assert summary["written_off_cents"] == 25000
        assert summary["refunded_cents"] == 0
        assert summary["recognized_revenue_cents"] == 40000
        assert summary["recognized_contribution_cents"] == 10000
        # b1 prorata: allocs rhu(50000*25000/40000)=31250 and
        # rhu(50000*15000/40000)=18750 -> excess 6250+3750 = 10000.
        assert summary["prorata_contribution_cents"] == 10000
        assert summary["unsold_item_count"] == 2, \
            "b3 item (write-off) and b4 item (no bids) are UNSOLD"
        assert summary["open_disposition_count"] == 2
