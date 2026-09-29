"""Pairs of failures that arrive together on the same request, where the global
ladder of §2.9 decides which one the caller is told about."""

from test_helpers import (
    CLOCK_EVENT_OPEN,
    CLOCK_SETUP,
    COUNTY_PRIMARY,
    add_lot,
    api_client,
    close_lot,
    create_event,
    create_exclusion,
    disclosed_asset,
    funded_bidder,
    lift_exclusion,
    list_bids,
    list_exclusions,
    list_holds,
    make_bidder_headers,
    open_event,
    place_bid_payload,
    read_bidder,
    read_event,
    read_lot,
    register_bidder,
    scheduled_lot,
    set_clock,
    validate_error,
    verify_bidder,
)

EXCLUSION_EFFECTIVE_AT = "2026-09-10T00:00:00Z"
BID_AFTER_CLOSE_AT = "2026-09-15T18:30:00Z"


def _excluded_bidder_after_the_window_closed():
    """A live Alameda lot whose bid window shut at 18:00, and a funded bidder
    carrying an Alameda-scoped sanctions exclusion that is already in force."""
    scenario = scheduled_lot(
        street_address="9 Seaview Ter",
        estimated_value_cents=29000000,
        event_title="Alameda Compliance Session",
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
    )
    bidder = funded_bidder(
        2000000, legal_name="Seaview Acquisitions LLC", email="bid@seaviewacq.example"
    )
    scenario.bidders = [bidder]

    set_clock(EXCLUSION_EFFECTIVE_AT)
    exclusion = create_exclusion(
        bidder["id"],
        "SANCTIONS_LIST",
        EXCLUSION_EFFECTIVE_AT,
        county_code=COUNTY_PRIMARY,
        notes="county affiliate screening hit",
    )

    set_clock(CLOCK_EVENT_OPEN)
    scenario.event = open_event(scenario.event_id)
    set_clock(BID_AFTER_CLOSE_AT)
    return scenario, bidder, exclusion


class TestExclusionOutranksClosedBidWindow:
    def test_excluded_bidder_is_told_about_the_exclusion_not_the_closed_window(self):
        """Two checks fail at once — the county-scoped exclusion on rung 36 and the
        shut bid window on rung 44 — and the earlier rung decides the response.

        PRD: "To make the API deterministic, every check the server performs occupies
        a fixed rung on a single global ladder, the ladder is walked in ascending order,
        and **the first failing check decides the response**; no later check can mask an
        earlier one, and no earlier check is skipped because a later one would also
        fail."

        Design: Difficulty/priority_pair_validation_conflict/county_scoped_exclusion_outranks_closed_bid_window
        """
        scenario, bidder, _exclusion = _excluded_bidder_after_the_window_closed()

        response = api_client.place_bid(
            scenario.lot_id,
            place_bid_payload(bidder["id"], 20000000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, "ERR_BIDDER_EXCLUDED", 403)

    def test_the_refusal_writes_nothing_and_leaves_registration_untouched(self):
        """A county-scoped exclusion blocks bidding in that county without suspending
        the bidder, and the rejected bid leaves no bid, no hold and no ledger movement.

        PRD: "A county-scoped exclusion, or a platform-wide one dated in the future,
        leaves `registration_status` untouched — it will still block bidding in the
        counties and at the times it covers, through the eligibility gate, but it is not
        a suspension."

        Design: Difficulty/priority_pair_validation_conflict/county_scoped_exclusion_outranks_closed_bid_window
        """
        scenario, bidder, _exclusion = _excluded_bidder_after_the_window_closed()
        validate_error(
            api_client.place_bid(
                scenario.lot_id,
                place_bid_payload(bidder["id"], 20000000),
                make_bidder_headers(bidder["id"]),
            ),
            "ERR_BIDDER_EXCLUDED",
            403,
        )

        refreshed = read_bidder(bidder["id"])
        assert refreshed["registration_status"] == "REGISTERED"
        assert refreshed["deposit_available_cents"] == 2000000
        assert list_bids(auction_lot_id=scenario.lot_id) == []
        assert list_holds(bidder_id=bidder["id"]) == []

        recorded = list_exclusions(bidder["id"])
        assert len(recorded) == 1
        assert recorded[0]["status"] == "ACTIVE"
        assert recorded[0]["county_code"] == COUNTY_PRIMARY

        lot = read_lot(scenario.lot_id)
        assert lot["lot_status"] == "OPEN"
        assert lot["current_high_bid_cents"] == 0

    def test_lifting_the_exclusion_uncovers_the_closed_window_failure(self):
        """With the exclusion lifted, the same request walks past rung 36 and is
        refused by the temporal rung that had been masked.

        PRD: "`ERR_BID_WINDOW_CLOSED` (409) — the logical clock is strictly before the
        lot's `bid_close_at`. Applies to `POST /auction-lots/{id}/bids`."

        Design: Difficulty/priority_pair_validation_conflict/county_scoped_exclusion_outranks_closed_bid_window
        """
        scenario, bidder, exclusion = _excluded_bidder_after_the_window_closed()
        lifted = lift_exclusion(exclusion["id"], notes="cleared on manual review")
        assert lifted["status"] == "LIFTED"

        response = api_client.place_bid(
            scenario.lot_id,
            place_bid_payload(bidder["id"], 20000000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, "ERR_BID_WINDOW_CLOSED", 409)
        assert list_bids(auction_lot_id=scenario.lot_id) == []


def _closed_lot_and_an_unfunded_bidder():
    """A live session holding two lots — one already closed with no sale, one still
    open — and a verified bidder who has funded nothing at all."""
    set_clock(CLOCK_SETUP)
    first = disclosed_asset(
        org_name="Westmark REO",
        seller_type="BANK",
        contact_email="reo@westmark.example",
        settlement_account_ref="ACH-WEST-11",
        street_address="14 Larkspur Ave",
        city="Oakland",
        estimated_value_cents=24000000,
    )
    second = disclosed_asset(
        seller=first.seller,
        street_address="16 Larkspur Ave",
        city="Oakland",
        estimated_value_cents=25000000,
    )
    event = create_event(
        title="Alameda REO Twin Lots",
        county_code=COUNTY_PRIMARY,
        starts_at="2026-09-15T17:00:00Z",
        ends_at="2026-09-15T19:00:00Z",
    )
    lot_a = add_lot(
        event["id"],
        first.listing_id,
        lot_number=1,
        lot_window_start_at="2026-09-15T17:00:00Z",
        lot_window_end_at="2026-09-15T17:30:00Z",
    )
    lot_b = add_lot(
        event["id"],
        second.listing_id,
        lot_number=2,
        lot_window_start_at="2026-09-15T17:00:00Z",
        lot_window_end_at="2026-09-15T19:00:00Z",
    )
    bidder = register_bidder(
        legal_name="Larkspur Buyers LLC",
        email="bid@larkspurbuyers.example",
        mailing_address="700 Broadway, Oakland CA",
    )
    verify_bidder(bidder["id"], "VERIFIED", "KYC-2020")

    set_clock(CLOCK_EVENT_OPEN)
    open_event(event["id"])
    set_clock("2026-09-15T17:35:00Z")
    lot_a = close_lot(lot_a["id"])
    return event, lot_a, lot_b, bidder


class TestClosedLotOutranksInsufficientDeposit:
    def test_the_state_rung_answers_with_409_rather_than_the_fiscal_402(self):
        """The bidder has no money and the lot has already closed; the state band sits
        far above the fiscal check, so the caller is told the lot is not open.

        PRD: "`ERR_LOT_NOT_OPEN` (409) — the lot's `lot_status` is either `OPEN` or
        `EXTENDED`. Applies to `POST /auction-lots/{id}/bids` and
        `POST /auction-lots/{id}/close`."

        Design: Difficulty/priority_pair_validation_conflict/closed_lot_state_error_outranks_insufficient_deposit
        """
        _event, lot_a, _lot_b, bidder = _closed_lot_and_an_unfunded_bidder()

        response = api_client.place_bid(
            lot_a["id"],
            place_bid_payload(bidder["id"], 20000000),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(response, "ERR_LOT_NOT_OPEN", 409)
        assert response.status_code != 402

    def test_the_fiscal_violation_really_was_present_and_unreported(self):
        """The bidder's available balance is zero against a required deposit of
        1000000, so the masked rung would genuinely have fired had it been reached.

        PRD: "`ERR_DEPOSIT_INSUFFICIENT` (402) — the bidder's `deposit_available_cents`
        is at least the lot's `required_deposit_cents`. This rung is skipped entirely when
        the bidder already holds a deposit hold on this lot whose `status` is `HELD` or
        `EXTENDED`. Applies to `POST /auction-lots/{id}/bids` and
        `POST /second-chance-offers/{id}/respond`."

        Design: Difficulty/priority_pair_validation_conflict/closed_lot_state_error_outranks_insufficient_deposit
        """
        _event, lot_a, _lot_b, bidder = _closed_lot_and_an_unfunded_bidder()

        assert read_bidder(bidder["id"])["deposit_available_cents"] == 0
        assert read_lot(lot_a["id"])["required_deposit_cents"] == 1000000

        validate_error(
            api_client.place_bid(
                lot_a["id"],
                place_bid_payload(bidder["id"], 20000000),
                make_bidder_headers(bidder["id"]),
            ),
            "ERR_LOT_NOT_OPEN",
            409,
        )

    def test_the_refusal_leaves_the_session_and_the_sibling_lot_alone(self):
        """The closed lot stays closed with no hammer price, the still-open sibling keeps
        the session live, and nothing was written for the rejected bid.

        PRD: "The ladder is grouped into bands: authentication, then existence, then
        ownership, then request shape, then entity state, then optimistic concurrency, then
        compliance and safety, then referential consistency, then temporal windows, then
        value constraints, and finally the fiscal check."

        Design: Difficulty/priority_pair_validation_conflict/closed_lot_state_error_outranks_insufficient_deposit
        """
        event, lot_a, lot_b, bidder = _closed_lot_and_an_unfunded_bidder()
        validate_error(
            api_client.place_bid(
                lot_a["id"],
                place_bid_payload(bidder["id"], 20000000),
                make_bidder_headers(bidder["id"]),
            ),
            "ERR_LOT_NOT_OPEN",
            409,
        )

        closed = read_lot(lot_a["id"])
        assert closed["lot_status"] == "CLOSED_NO_SALE"
        assert closed["current_high_bid_cents"] == 0
        assert read_event(event["id"])["event_status"] == "LIVE"
        assert read_lot(lot_b["id"])["lot_status"] == "OPEN"
        assert list_bids(auction_lot_id=lot_a["id"]) == []
        assert list_holds(bidder_id=bidder["id"]) == []
