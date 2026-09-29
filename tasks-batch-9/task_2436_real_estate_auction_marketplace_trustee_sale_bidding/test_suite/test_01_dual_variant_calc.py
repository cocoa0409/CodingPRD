"""Calculations that exist in two variants reading two different snapshots: the
provisional and final buyer premium, and the screen and audit risk scores."""

from test_helpers import (
    CLOCK_SETUP,
    EVENT_END,
    EVENT_START,
    add_lot,
    assert_settlement_conserved,
    assert_timestamp_equals,
    close_lot,
    confirm_sale,
    create_event,
    create_exclusion,
    create_trustee_sale,
    disclosed_asset,
    eligibility_assessment,
    execute_contract,
    expected_buyer_premium,
    expected_contract_price,
    expected_doc_fee,
    expected_platform_fee,
    fund,
    funded_bidder,
    open_event,
    place_bid,
    postpone_sale,
    read_bidder,
    read_listing,
    read_lot,
    read_sale,
    register_bidder,
    record_title_clearance,
    set_clock,
    settlement_preview,
    verify_bidder,
)


def _hammered_lot_on_a_once_postponed_sale():
    """A lot on a sale the trustee pushed by one week and then re-confirmed,
    hammered down at 40000000 while the title axis still read the seller's own
    `UNKNOWN` disclosure, with a clear title finding recorded after the hammer."""
    set_clock(CLOCK_SETUP)
    bundle = disclosed_asset(
        occupancy_status="VACANT",
        title_condition="UNKNOWN",
        org_name="Cascade Servicing",
        seller_type="SERVICER",
        contact_email="ops@cascade.example",
        settlement_account_ref="ACH-CASCADE-1",
        default_commission_bps=500,
        street_address="812 Fruitvale Ave",
        city="Oakland",
        estimated_value_cents=45000000,
    )
    sale = create_trustee_sale(bundle.listing_id, "2026-09-10T18:00:00Z")
    postpone_sale(
        sale["id"],
        "2026-09-15T18:00:00Z",
        reason="trustee continued the sale by one week",
    )
    sale = confirm_sale(sale["id"])
    event = create_event(
        title="Alameda September Trustee Sale",
        starts_at=EVENT_START,
        ends_at=EVENT_END,
        trustee_sale_id=sale["id"],
    )
    lot = add_lot(
        event["id"],
        bundle.listing_id,
        opening_bid_cents=38000000,
        reserve_price_cents=38000000,
    )
    bidder = funded_bidder(
        2000000, legal_name="Harbor Point Holdings LLC", email="buys@harborpoint.example"
    )

    set_clock("2026-09-15T17:05:00Z")
    open_event(event["id"])
    place_bid(lot["id"], bidder["id"], 40000000)
    set_clock("2026-09-15T18:05:00Z")
    lot = close_lot(lot["id"])
    listing = record_title_clearance(
        bundle.listing_id, "CLEARED", "CLEAR", title_report_reference="TR-2211"
    )
    return {
        "seller": bundle.seller,
        "listing": listing,
        "sale": read_sale(sale["id"]),
        "event": event,
        "lot": lot,
        "bidder": bidder,
    }


class TestPremiumVariantDivergence:
    def test_provisional_premium_prices_the_hammer_off_the_disclosed_condition(self):
        """The provisional variant runs at close against the hammer price and the
        title condition as it stood then — an `UNKNOWN` disclosure worth 250 basis
        points — giving 4200000 on a 40000000 hammer.

        PRD: "Its price input is the lot's `hammer_price_cents`, with no postponement
        carry, and its `occupancy_status` and `title_condition` inputs are read exactly
        as they stand at the moment of the close request — which in practice usually
        means the title axis is still `PENDING` and the premium is therefore priced off
        the seller's own disclosure rather than a verified finding."

        Design: Difficulty/dual_variant_calc/premium_variant_diverges_when_title_cleared_after_hammer
        """
        state = _hammered_lot_on_a_once_postponed_sale()

        lot = read_lot(state["lot"]["id"])
        assert lot["hammer_price_cents"] == 40000000
        assert (
            lot["provisional_buyer_premium_cents"]
            == expected_buyer_premium(40000000, "VACANT", "UNKNOWN")
            == 4200000
        )

    def test_settlement_preview_shows_the_final_premium_below_the_provisional(self):
        """The final variant reads the higher price base but the cleared title, so the
        preview reports a negative variant delta of 992000.

        PRD: "It returns the `auction_lot_id` it was asked about, the
        `hammer_price_cents` and `contract_price_cents`, the `provisional_premium_cents`
        and `final_premium_cents` side by side, the `premium_variant_delta_cents` as the
        final premium less the provisional premium — a negative figure when a title
        search improved the recorded condition after the hammer fell — and the
        `doc_fee_cents`, `total_due_cents`, `settlement_gross_cents`, `seller_net_cents`
        and `platform_fee_cents` that would be posted."

        Design: Difficulty/dual_variant_calc/premium_variant_diverges_when_title_cleared_after_hammer
        """
        state = _hammered_lot_on_a_once_postponed_sale()

        preview = settlement_preview(state["lot"]["id"])

        assert preview["hammer_price_cents"] == 40000000
        assert (
            preview["contract_price_cents"] == expected_contract_price(40000000, 1) == 40100000
        )
        assert preview["provisional_premium_cents"] == 4200000
        assert (
            preview["final_premium_cents"]
            == expected_buyer_premium(40100000, "VACANT", "CLEAR")
            == 3208000
        )
        assert preview["premium_variant_delta_cents"] == -992000

    def test_executed_contract_posts_the_final_variant_and_the_carry(self):
        """Execution charges the postponement carry of 25 basis points once, prices the
        premium off the cleared title, and posts the settlement the preview projected.

        PRD: "Its price input is `contract_price_cents`, hammer plus postponement carry,
        rather than the bare hammer — so a postponed sale can cross a premium tier
        boundary that the provisional run did not."

        Design: Difficulty/dual_variant_calc/premium_variant_diverges_when_title_cleared_after_hammer
        """
        state = _hammered_lot_on_a_once_postponed_sale()

        contract = execute_contract(state["lot"]["id"], closing_window_days=21)

        assert contract["contract_price_cents"] == 40100000
        assert contract["final_buyer_premium_cents"] == 3208000
        assert contract["doc_fee_cents"] == expected_doc_fee(40100000, 3208000) == 71250
        assert contract["total_due_cents"] == 43379250
        assert contract["settlement_gross_cents"] == 43308000
        assert (
            contract["platform_fee_cents"]
            == expected_platform_fee(40100000, 500, "CLEAR")
            == 2145350
        )
        assert contract["seller_net_cents"] == 37954650
        assert_settlement_conserved(contract)
        assert_timestamp_equals(contract["closing_deadline_at"], "2026-10-06T18:05:00Z")

        # The county sale is deemed conducted, and the verified condition stands.
        assert read_sale(state["sale"]["id"])["status"] == "HELD"
        assert read_sale(state["sale"]["id"])["postponement_count"] == 1
        assert read_listing(state["listing"]["id"])["title_condition"] == "CLEAR"


def _bidder_with_a_future_platform_wide_exclusion():
    """A verified, funded bidder carrying one `ACTIVE` platform-wide exclusion whose
    `effective_at` is still four days in the future, and one lot to assess against."""
    set_clock(CLOCK_SETUP)
    bundle = disclosed_asset(
        org_name="Bayline Bank",
        seller_type="BANK",
        contact_email="reo@bayline.example",
        settlement_account_ref="ACH-BAYLINE-2",
        street_address="17 Elmhurst Ct",
        city="Hayward",
        estimated_value_cents=26000000,
    )
    event = create_event(
        title="Alameda REO Mid-September", starts_at=EVENT_START, ends_at=EVENT_END
    )
    lot = add_lot(
        event["id"],
        bundle.listing_id,
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
    )
    bidder = register_bidder(
        legal_name="Delta Ridge Capital LLC",
        email="bids@deltaridge.example",
        mailing_address="9 Harbor Way, Alameda CA",
    )

    set_clock("2026-09-01T00:00:00Z")
    verify_bidder(bidder["id"], "VERIFIED", "KYC-9002")
    fund(bidder["id"], 2000000, "WIRE-77001")

    set_clock("2026-09-16T00:00:00Z")
    exclusion = create_exclusion(
        bidder["id"],
        "STATE_INELIGIBLE",
        "2026-09-20T00:00:00Z",
        county_code="ALL",
        notes="state registration lapses 2026-09-20",
    )
    return bundle, lot, bidder, exclusion


class TestRiskScoreVariantDivergence:
    def test_screen_counts_the_future_exclusion(self):
        """The forward-looking screen counts an exclusion that has not yet bitten, so
        the score is 20 and the bidder is still eligible.

        PRD: "Exclusions dated in the future, with an `effective_at` after the logical
        clock, **are** counted, because a screen is asking whether this bidder is safe
        to let in rather than whether they were excluded at some past instant."

        Design: Difficulty/dual_variant_calc/risk_score_screen_counts_future_exclusion_audit_does_not
        """
        _bundle, lot, bidder, _exclusion = _bidder_with_a_future_platform_wide_exclusion()

        screen = eligibility_assessment(bidder["id"], mode="SCREEN", auction_lot_id=lot["id"])

        assert screen["mode"] == "SCREEN"
        assert screen["risk_score"] == 20
        assert screen["counted_exclusion_count"] == 1
        assert screen["eligible"] is True
        assert screen["exclusion_penalty_applied"] == 20
        assert screen["identity_penalty_applied"] == 0
        assert screen["deposit_penalty_applied"] == 0

    def test_audit_anchored_on_the_event_start_does_not_count_it(self):
        """The audit anchors on the lot's event `starts_at`, which precedes the
        exclusion's `effective_at`, so the same row contributes nothing.

        PRD: "The counted exclusions are those whose `effective_at` is at or before the
        reference instant and whose scope is either `ALL` or the event's `county_code`,
        and which were either still `ACTIVE` or were `LIFTED` with a `lifted_at` later
        than the reference instant."

        Design: Difficulty/dual_variant_calc/risk_score_screen_counts_future_exclusion_audit_does_not
        """
        _bundle, lot, bidder, exclusion = _bidder_with_a_future_platform_wide_exclusion()

        audit = eligibility_assessment(bidder["id"], mode="AUDIT", auction_lot_id=lot["id"])

        assert audit["mode"] == "AUDIT"
        assert audit["risk_score"] == 0
        assert audit["counted_exclusion_count"] == 0
        assert audit["identity_penalty_applied"] == 0
        assert audit["eligible"] is True
        assert exclusion["status"] == "ACTIVE"

    def test_a_future_platform_wide_exclusion_does_not_suspend_the_bidder(self):
        """Because the exclusion is dated ahead of the clock it is not a suspension,
        and the stored screen score — refreshed with no lot in context — reads 20.

        PRD: "When the platform refreshes `screen_risk_score` as a side effect of a
        mutation there is no lot in context, so only `ALL`-scoped exclusions are counted
        and the deposit penalty is not applied."

        Design: Difficulty/dual_variant_calc/risk_score_screen_counts_future_exclusion_audit_does_not
        """
        _bundle, _lot, bidder, _exclusion = _bidder_with_a_future_platform_wide_exclusion()

        refreshed = read_bidder(bidder["id"])

        assert refreshed["registration_status"] == "REGISTERED"
        assert refreshed["screen_risk_score"] == 20
