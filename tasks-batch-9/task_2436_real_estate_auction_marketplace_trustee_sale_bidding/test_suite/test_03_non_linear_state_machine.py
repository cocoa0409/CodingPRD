"""Lifecycles that revisit states they have already occupied: the event that cycles
back into `LIVE`, and the asset whose two status axes loop independently."""

from test_helpers import (
    api_client,
    assert_timestamp_equals,
    close_lot,
    confirm_sale,
    funded_bidder,
    list_holds,
    live_lot,
    make_seller_headers,
    open_event,
    place_bid,
    postpone_sale,
    read_bid,
    read_bidder,
    read_event,
    read_listing,
    read_lot,
    read_sale,
    relist_payload,
    reschedule_event,
    scheduled_lot,
    set_clock,
    validate_success,
)

RIDGEVIEW = {
    "org_name": "Ridgeview Trustee Services",
    "seller_type": "SERVICER",
    "contact_email": "sales@ridgeview.example",
    "settlement_account_ref": "ACH-RIDGE-9",
    "street_address": "77 Skyline Dr",
    "city": "Berkeley",
    "estimated_value_cents": 52000000,
}

ALDERWOOD = {
    "org_name": "Alderwood Private Sales",
    "seller_type": "PRIVATE_SELLER",
    "contact_email": "seller@alderwood.example",
    "settlement_account_ref": "ACH-ALDER-4",
    "street_address": "410 Alder Way",
    "city": "Alameda",
    "estimated_value_cents": 31000000,
}

SECOND_PASS_START = "2026-09-22T17:00:00Z"
SECOND_PASS_OPEN = "2026-09-22T17:05:00Z"


def _event_taken_live_twice_across_a_county_postponement():
    """A trustee-linked session opened, postponed by the county, rescheduled a week
    out and then opened a second time — one full turn of the event cycle."""
    scenario = scheduled_lot(
        event_title="Alameda Skyline Trustee Sale",
        opening_bid_cents=40000000,
        reserve_price_cents=40000000,
        trustee_sale_at="2026-09-15T18:00:00Z",
        **RIDGEVIEW,
    )
    set_clock("2026-09-15T17:05:00Z")
    scenario.event = open_event(scenario.event_id)

    postpone_sale(
        scenario.sale_id, "2026-09-22T18:00:00Z", reason="county continued the sale"
    )
    confirm_sale(scenario.sale_id, "TS-ALA-7781-R2")
    scenario.event = reschedule_event(
        scenario.event_id, SECOND_PASS_START, "2026-09-22T19:00:00Z"
    )

    set_clock(SECOND_PASS_OPEN)
    scenario.event = open_event(scenario.event_id)
    return scenario


class TestEventCycle:
    def test_the_event_re_enters_live_carrying_a_reschedule_count(self):
        """The session reaches `LIVE` for the second time, and the loop counter plus
        the replaced window show this is a later pass rather than the original one.

        PRD: "The event axis runs `SCHEDULED`, `LIVE`, `POSTPONED`, `CANCELLED` and
        `CLOSED`, with the last two terminal, and it cycles
        `SCHEDULED → LIVE → POSTPONED → SCHEDULED → LIVE` across county postponements."

        Design: Difficulty/non_linear_state_machine/event_cycles_scheduled_live_postponed_scheduled_live
        """
        scenario = _event_taken_live_twice_across_a_county_postponement()

        event = read_event(scenario.event_id)
        assert event["event_status"] == "LIVE"
        assert event["reschedule_count"] == 1
        assert_timestamp_equals(event["starts_at"], SECOND_PASS_START)
        assert_timestamp_equals(event["opened_at"], SECOND_PASS_OPEN)

    def test_the_lot_travels_with_the_event_and_gets_its_extensions_back(self):
        """Rescheduling shifted the lot's window by exactly the week the county added
        and cleared its extension counter; taking the session live resumes the lot.

        PRD: "Every non-terminal lot of the rescheduled event — those whose `lot_status`
        is `PENDING` or `SUSPENDED` — travels with the event: `lot_window_start_at` and
        `lot_window_end_at` are both shifted by exactly the offset between the new start
        and the old start, `bid_close_at` is reset to the shifted `lot_window_end_at`, and
        `extension_count` is reset to 0, so a lot that had already consumed its late-bid
        extensions gets them back for the new session."

        Design: Difficulty/non_linear_state_machine/event_cycles_scheduled_live_postponed_scheduled_live
        """
        scenario = _event_taken_live_twice_across_a_county_postponement()

        lot = read_lot(scenario.lot_id)
        assert lot["lot_status"] == "OPEN"
        assert_timestamp_equals(lot["lot_window_start_at"], SECOND_PASS_START)
        assert_timestamp_equals(lot["lot_window_end_at"], "2026-09-22T18:00:00Z")
        assert_timestamp_equals(lot["bid_close_at"], "2026-09-22T18:00:00Z")
        assert lot["extension_count"] == 0

    def test_the_county_leg_is_confirmed_again_at_its_new_date(self):
        """The statutory sale sits back at `CONFIRMED` for the new date while its
        postponement counter records the round trip.

        PRD: "The sale moves to `POSTPONED` from either `PENDING` or `CONFIRMED`,
        `postponement_count` rises by 1, and `sale_scheduled_at` is replaced by
        `new_sale_at`."

        Design: Difficulty/non_linear_state_machine/event_cycles_scheduled_live_postponed_scheduled_live
        """
        scenario = _event_taken_live_twice_across_a_county_postponement()

        sale = read_sale(scenario.sale_id)
        assert sale["status"] == "CONFIRMED"
        assert sale["postponement_count"] == 1
        assert_timestamp_equals(sale["sale_scheduled_at"], "2026-09-22T18:00:00Z")


def _no_sale_lot_on_a_cleared_asset():
    """A cleared-title asset whose only lot closed with the single bid below reserve,
    so the marketplace axis has fallen to `UNSOLD` while the title axis reads `CLEARED`."""
    scenario = live_lot(
        clear_title=True,
        event_title="Alameda REO Block E",
        opening_bid_cents=20000000,
        reserve_price_cents=25000000,
        **ALDERWOOD,
    )
    bidder = funded_bidder(
        2000000, legal_name="Foothill Rentals LLC", email="bid@foothill.example"
    )
    scenario.bidders = [bidder]

    set_clock("2026-09-15T17:10:00Z")
    scenario.bids = [place_bid(scenario.lot_id, bidder["id"], 20000000)]
    set_clock("2026-09-15T18:05:00Z")
    scenario.lot = close_lot(scenario.lot_id)
    return scenario


def _relist(scenario):
    return validate_success(
        api_client.relist_asset_listing(
            scenario.listing_id, relist_payload(), make_seller_headers(scenario.seller_id)
        )
    )


class TestListingAxesLoopIndependently:
    def test_the_below_reserve_close_pushes_only_the_marketplace_axis(self):
        """No candidate cleared the reserve, so the lot closes unsold, the standing bid
        stays `ACTIVE`, the hold is released for no sale — and the title axis is untouched.

        PRD: "Here `hammer_price_cents` stays 0 and `provisional_buyer_premium_cents`
        stays 0; a standing `ACTIVE` bid below reserve stays `ACTIVE`, since it never
        became a winner; every deposit hold on the lot whose `status` is `HELD` or
        `EXTENDED` is `RELEASED` with a `released_reason` of `NO_SALE`, and every affected
        bidder's deposit ledger is recomputed; and the asset moves `LISTED → UNSOLD`,
        which makes it relistable."

        Design: Difficulty/non_linear_state_machine/listing_axes_move_independently_and_title_axis_reloops
        """
        scenario = _no_sale_lot_on_a_cleared_asset()

        lot = read_lot(scenario.lot_id)
        assert lot["lot_status"] == "CLOSED_NO_SALE"
        assert lot["hammer_price_cents"] == 0
        assert lot["provisional_buyer_premium_cents"] == 0

        bid = read_bid(scenario.bids[0]["id"])
        assert bid["bid_status"] == "ACTIVE"
        assert bid["is_above_reserve"] is False

        holds = list_holds(auction_lot_id=scenario.lot_id)
        assert len(holds) == 1
        assert holds[0]["status"] == "RELEASED"
        assert holds[0]["released_reason"] == "NO_SALE"
        assert read_bidder(scenario.bidder_id)["deposit_available_cents"] == 2000000

        listing = read_listing(scenario.listing_id)
        assert listing["listing_status"] == "UNSOLD"
        assert listing["title_clearance_status"] == "CLEARED"

    def test_the_last_lot_reaching_a_terminal_status_closes_the_event(self):
        """The session bubbles up to `CLOSED` because no lot of it remains open.

        PRD: "If, after the closing lot has reached its terminal status, no lot of the
        parent event remains in `PENDING`, `OPEN`, `EXTENDED` or `SUSPENDED`, the event
        itself moves `LIVE → CLOSED`, which is terminal."

        Design: Difficulty/non_linear_state_machine/listing_axes_move_independently_and_title_axis_reloops
        """
        scenario = _no_sale_lot_on_a_cleared_asset()

        assert read_event(scenario.event_id)["event_status"] == "CLOSED"

    def test_the_relist_loops_the_title_axis_without_reverting_the_finding(self):
        """The seller's reset takes the marketplace axis back to `DISCLOSURE_READY` and
        drops the title axis to `PENDING` for a fresh search, yet the officer's verified
        `CLEAR` condition survives on the record.

        PRD: "It takes an asset whose `listing_status` is `UNSOLD` or `RELIST_PENDING`
        back to `DISCLOSURE_READY`, increments `relist_count` by 1, resets
        `second_chance_eligible` to false, and resets `title_clearance_status` to
        `PENDING` so a fresh title search can run — the title axis loops with the
        marketplace axis rather than remaining pinned to a stale finding."

        Design: Difficulty/non_linear_state_machine/listing_axes_move_independently_and_title_axis_reloops
        """
        scenario = _no_sale_lot_on_a_cleared_asset()

        relisted = _relist(scenario)

        assert relisted["listing_status"] == "DISCLOSURE_READY"
        assert relisted["title_clearance_status"] == "PENDING"
        assert relisted["title_condition"] == "CLEAR"
        assert relisted["relist_count"] == 1
        assert relisted["second_chance_eligible"] is False
