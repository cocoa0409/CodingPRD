"""Boundary and precision behaviour on the late-bid extension trigger and on the
reserve comparison that gates the backup-bidder pool."""

from test_helpers import (
    CLOCK_EVENT_OPEN,
    add_lot,
    assert_deposit_pool_conserved,
    assert_timestamp_equals,
    close_lot,
    create_offer,
    disclosed_asset,
    execute_contract,
    funded_bidder,
    funded_bidders,
    holds_for_bidder,
    list_bids,
    live_lot,
    open_event,
    place_bid,
    read_bid,
    read_bidder,
    read_listing,
    read_lot,
    record_fallout,
    scheduled_lot,
    set_clock,
)

LOT_CLOSE_AT = "2026-09-15T18:00:00Z"
BID_AT_61_SECONDS = "2026-09-15T17:58:59Z"
BID_AT_60_SECONDS = "2026-09-15T17:59:00Z"


def _event_with_two_sibling_lots():
    """One live event carrying two lots on two different assets, both windows
    ending at 18:00:00Z, plus one bidder funded for both deposits."""
    scenario = scheduled_lot(
        org_name="Brightline Servicing",
        seller_type="SERVICER",
        contact_email="reo@brightline.example",
        settlement_account_ref="ACH-BRIGHT-1",
        street_address="120 Bright St",
        estimated_value_cents=28000000,
        event_title="Alameda Late-Bid Session",
    )
    sibling = disclosed_asset(
        seller=scenario.seller,
        street_address="122 Bright St",
        estimated_value_cents=28000000,
    )
    lot_b = add_lot(
        scenario.event_id,
        sibling.listing_id,
        lot_number=2,
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
    )
    scenario.listings.append(sibling.listing)
    scenario.lots.append(lot_b)

    set_clock(CLOCK_EVENT_OPEN)
    scenario.event = open_event(scenario.event_id)

    bidder = funded_bidder(
        3000000, legal_name="Bright Bay Capital LLC", email="bids@brightbay.example"
    )
    scenario.bidders = [bidder]
    return scenario, read_lot(scenario.lot_id), read_lot(lot_b["id"]), bidder


class TestLateBidExtensionBoundary:
    def test_bid_with_sixty_one_seconds_remaining_does_not_extend(self):
        """A bid landing 61 seconds before `bid_close_at` leaves the close instant,
        the extension counter and the lot status exactly where they were.

        PRD: "The boundary is inclusive on the trigger side and exclusive on the
        counter: with exactly 60 seconds remaining the lot extends, with 61 seconds
        remaining it does not, and once `extension_count` has reached 3 further late
        bids are still accepted — they simply no longer move the clock."

        Design: Difficulty/boundary_precision_check/extension_fires_at_exactly_sixty_seconds_remaining
        """
        _scenario, _lot_a, lot_b, bidder = _event_with_two_sibling_lots()

        set_clock(BID_AT_61_SECONDS)
        bid = place_bid(lot_b["id"], bidder["id"], 20000000)

        assert bid["triggered_extension"] is False
        after = read_lot(lot_b["id"])
        assert_timestamp_equals(after["bid_close_at"], LOT_CLOSE_AT)
        assert after["extension_count"] == 0
        assert after["lot_status"] == "OPEN"

    def test_bid_with_exactly_sixty_seconds_remaining_extends_the_lot(self):
        """A bid landing exactly 60 seconds before `bid_close_at` pushes the close
        out to the clock plus 120 seconds and moves the lot to `EXTENDED`.

        PRD: "If that remaining time is at most 60 seconds and the lot's
        `extension_count` is still strictly less than 3, the lot is extended:
        `bid_close_at` is rewritten to the logical clock advanced by 120 seconds,
        `extension_count` rises by 1, `lot_status` moves `OPEN → EXTENDED` (or stays
        `EXTENDED` on a self-loop when the lot was already extended), and the
        triggering bid records `triggered_extension` as true."

        Design: Difficulty/boundary_precision_check/extension_fires_at_exactly_sixty_seconds_remaining
        """
        _scenario, lot_a, lot_b, bidder = _event_with_two_sibling_lots()

        set_clock(BID_AT_61_SECONDS)
        place_bid(lot_b["id"], bidder["id"], 20000000)

        set_clock(BID_AT_60_SECONDS)
        bid = place_bid(lot_a["id"], bidder["id"], 20000000)

        assert bid["triggered_extension"] is True
        extended = read_lot(lot_a["id"])
        assert_timestamp_equals(extended["bid_close_at"], "2026-09-15T18:01:00Z")
        assert extended["extension_count"] == 1
        assert extended["lot_status"] == "EXTENDED"

        # Two lots, two deposits of 1000000 each, taken from a 3000000 wallet.
        refreshed = read_bidder(bidder["id"])
        assert refreshed["deposit_available_cents"] == 1000000
        holds = holds_for_bidder(bidder["id"])
        assert len(holds) == 2
        assert_deposit_pool_conserved(refreshed, 2000000)

    def test_extension_is_scoped_to_the_bid_lot_only(self):
        """The sibling lot that received the earlier bid keeps its own close instant
        when the other lot extends, because the extension is a property of the lot
        the bid was placed on.

        PRD: "Otherwise `bid_close_at` is left exactly where it was and the bid
        records `triggered_extension` as false."

        Design: Difficulty/boundary_precision_check/extension_fires_at_exactly_sixty_seconds_remaining
        """
        _scenario, lot_a, lot_b, bidder = _event_with_two_sibling_lots()

        set_clock(BID_AT_61_SECONDS)
        place_bid(lot_b["id"], bidder["id"], 20000000)
        set_clock(BID_AT_60_SECONDS)
        place_bid(lot_a["id"], bidder["id"], 20000000)

        untouched = read_lot(lot_b["id"])
        assert_timestamp_equals(untouched["bid_close_at"], LOT_CLOSE_AT)
        assert untouched["extension_count"] == 0
        assert untouched["lot_status"] == "OPEN"


def _four_bidder_lot():
    """A lot opened at 19000000 with a confidential reserve of 20000000, bid up by
    four bidders: one below the reserve, one exactly at it, and two above."""
    scenario = live_lot(
        clear_title=True,
        org_name="Pinnacle GSE Disposition",
        seller_type="GSE",
        contact_email="reo@pinnaclegse.example",
        settlement_account_ref="ACH-PINN-9",
        default_commission_bps=500,
        street_address="505 Telegraph Ave",
        city="Oakland",
        estimated_value_cents=25000000,
        event_title="Alameda Reserve Boundary Session",
        opening_bid_cents=19000000,
        reserve_price_cents=20000000,
    )
    bidders = funded_bidders(4, 1000000, prefix="Reserve Boundary")
    scenario.bidders = bidders

    ladder = [
        ("2026-09-15T17:10:00Z", bidders[3], 19000000),
        ("2026-09-15T17:11:00Z", bidders[1], 20000000),
        ("2026-09-15T17:12:00Z", bidders[2], 20500000),
        ("2026-09-15T17:13:00Z", bidders[0], 21000000),
    ]
    for instant, bidder, amount in ladder:
        set_clock(instant)
        scenario.bids.append(place_bid(scenario.lot_id, bidder["id"], amount))
    return scenario


class TestBackupPoolReserveBoundary:
    def test_is_above_reserve_is_true_at_the_reserve_and_false_below_it(self):
        """The flag fixed at acceptance is a greater-than-or-equal comparison, so a
        bid of exactly the reserve qualifies and a bid one increment below does not.

        PRD: "Its `is_above_reserve` flag is fixed at acceptance as whether the
        `amount_cents` is greater than or equal to the lot's `reserve_price_cents`,
        and it is never revisited afterwards, even if the reserve is somehow
        different later."

        Design: Difficulty/boundary_precision_check/backup_pool_includes_bid_exactly_at_reserve_excludes_bid_below
        """
        scenario = _four_bidder_lot()

        below_reserve, at_reserve = scenario.bids[0], scenario.bids[1]
        assert below_reserve["amount_cents"] == 19000000
        assert below_reserve["is_above_reserve"] is False
        assert at_reserve["amount_cents"] == 20000000
        assert at_reserve["is_above_reserve"] is True

    def test_backup_offer_goes_to_the_highest_outbid_bid_at_or_above_reserve(self):
        """After the winner falls out, the second-chance offer is priced from the
        highest outbid bid that cleared the reserve — the 20500000 bid — and the
        below-reserve bid is never a candidate.

        PRD: "Candidates are the bids on the fallen-out lot whose `bid_status` is
        `OUTBID`, whose `amount_cents` is greater than or equal to the lot's
        `reserve_price_cents`, and whose bidder is currently both `REGISTERED` on the
        registration axis and `VERIFIED` on the identity axis."

        Design: Difficulty/boundary_precision_check/backup_pool_includes_bid_exactly_at_reserve_excludes_bid_below
        """
        scenario = _four_bidder_lot()
        set_clock("2026-09-15T18:05:00Z")
        close_lot(scenario.lot_id)
        set_clock("2026-09-15T18:10:00Z")
        contract = execute_contract(scenario.lot_id, closing_window_days=21)

        set_clock("2026-09-20T00:00:00Z")
        record_fallout(contract["id"])
        set_clock("2026-09-20T00:10:00Z")
        offer = create_offer(scenario.lot_id)

        assert offer["offered_bidder_id"] == scenario.bidders[2]["id"]
        assert offer["offer_price_cents"] == 20500000
        assert offer["status"] == "OUTSTANDING"
        assert_timestamp_equals(offer["expires_at"], "2026-09-23T00:10:00Z")
        assert read_listing(scenario.listing_id)["second_chance_eligible"] is True

    def test_fallout_forfeits_the_winner_deposit_and_leaves_the_hammer_recorded(self):
        """The winner's 950000 hold — five percent of the 19000000 opening bid on a
        vacant asset — is captured, and the hammer price stays on the lot.

        PRD: "The winning bidder's deposit hold on the lot, whose `status` is `HELD`
        or `EXTENDED`, becomes `CAPTURED` with a `released_reason` of `FORFEITED`, and
        the contract's `forfeited_deposit_cents` is set to that hold's `amount_cents`."

        Design: Difficulty/boundary_precision_check/backup_pool_includes_bid_exactly_at_reserve_excludes_bid_below
        """
        scenario = _four_bidder_lot()
        set_clock("2026-09-15T18:05:00Z")
        closed = close_lot(scenario.lot_id)
        assert closed["hammer_price_cents"] == 21000000
        set_clock("2026-09-15T18:10:00Z")
        contract = execute_contract(scenario.lot_id, closing_window_days=21)

        set_clock("2026-09-20T00:00:00Z")
        after_fallout = record_fallout(contract["id"])

        assert after_fallout["forfeited_deposit_cents"] == 950000
        winner = read_bidder(scenario.bidders[0]["id"])
        assert winner["deposit_forfeited_cents"] == 950000
        assert winner["fallout_count"] == 1
        # The below-reserve bid never became a winner, so it is still standing.
        assert read_bid(scenario.bids[0]["id"])["bid_status"] == "OUTBID"
        assert len(list_bids(auction_lot_id=scenario.lot_id)) == 4
