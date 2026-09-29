"""The ring: the opening floor, the strictly-positive increment and the leveraged cap."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_bid_payload,
    open_auction_with_catalogue,
    place_bid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPERATOR, SETTLEMENT

BID_WINDOW_INSTANT = "2026-08-10T16:00:00Z"


def _small_paddle_on_an_open_lot():
    """An OPEN event with one lot and a TIER_A paddle holding the 100,000-cent minimum."""
    return open_auction_with_catalogue(
        lot_overrides={"serial_number": "CAT-D8T-0001"},
        deposit_cents=100_000,
        deposit_hold_cents=100_000,
        open_clock=BID_WINDOW_INSTANT,
    )


def _full_paddle_on_an_open_lot(open_now: bool = True):
    """The same event with a paddle holding 1,500,000, so the cap is 15,000,000."""
    return open_auction_with_catalogue(
        lot_overrides={"serial_number": "CAT-D8T-0001"},
        deposit_cents=1_500_000,
        deposit_hold_cents=1_500_000,
        open_now=open_now,
        open_clock=BID_WINDOW_INSTANT if open_now else None,
    )


class TestOpeningFloor:
    def test_the_first_bid_must_reach_ten_thousand_cents_exactly(self):
        """One cent below the floor is refused on an untouched lot, and the floor itself is
        admitted.

        PRD 3.6: "`amount_cents` must be strictly greater than the lot's current
        `high_bid_cents`, with a first bid on a lot additionally required to reach the opening
        floor of 10,000 cents, failing which the refusal is `ERR_BID_NOT_HIGHER`."
        PRD 3.6: "A bid is created in `ACTIVE` with `placed_at` taken from the logical clock,
        and the lot's `high_bid_cents` is recomputed immediately."

        Design: Difficulty/boundary_precision_check/opening_bid_at_minimum_accepted_while_equal_bid_is_refused
        """
        stage = _small_paddle_on_an_open_lot()
        lot, registration, bidder = stage["lot"], stage["registration"], stage["bidder"]
        assert lot["high_bid_cents"] == 0

        below = place_bid(registration, lot, 9_999, bidder)
        validate_error(below, ApiErrorId.ERR_BID_NOT_HIGHER, expected_status=422)
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"] == 0
        )

        opening = validate_success(
            api_client.create_bid(
                create_bid_payload(registration["id"], lot["id"], 10_000),
                stage["bidder_headers"],
            ),
            expected_status=201,
        )

        assert opening["status"] == "ACTIVE"
        assert opening["amount_cents"] == 10_000
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"]
            == 10_000
        )

    def test_the_increment_above_a_standing_bid_must_be_strictly_positive(self):
        """Repeating the standing high bid is refused, one cent above it is accepted, and the
        paddle's forecast cap is untouched by either.

        PRD 3.6: "A bid equal to the standing high bid is refused; the increment must be
        strictly positive."
        PRD 3.6: "Bids are append-only: their `status` moves to `WINNING` or `LOSING` by system
        action alone, and there is no endpoint that edits or deletes a bid."

        Design: Difficulty/boundary_precision_check/opening_bid_at_minimum_accepted_while_equal_bid_is_refused
        """
        stage = _small_paddle_on_an_open_lot()
        lot, registration, bidder = stage["lot"], stage["registration"], stage["bidder"]
        assert registration["bid_cap_cents"] == 1_000_000
        validate_success(
            place_bid(registration, lot, 10_000, bidder), expected_status=201
        )

        equal = place_bid(registration, lot, 10_000, bidder)
        validate_error(equal, ApiErrorId.ERR_BID_NOT_HIGHER, expected_status=422)

        higher = validate_success(
            place_bid(registration, lot, 10_001, bidder), expected_status=201
        )
        assert higher["amount_cents"] == 10_001

        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"]
            == 10_001
        )
        rows, meta = validate_paginated(
            api_client.list_bids(OPERATOR, params={"lot_id": lot["id"]})
        )
        assert meta["total_count"] == 2
        assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE"]
        assert (
            validate_success(
                api_client.get_bidder_registration(registration["id"], SETTLEMENT)
            )["bid_cap_cents"]
            == 1_000_000
        )


class TestLeveragedCeiling:
    def test_the_cap_admits_its_own_value_and_refuses_a_single_cent_more(self):
        """A 1,500,000-cent hold at leverage 10 with no credit line buys exactly 15,000,000,
        and the cent above it records nothing.

        PRD 3.6: "`amount_cents` must not exceed the paddle's live cap, failing which the
        refusal is `ERR_BID_CAP_EXCEEDED`".
        PRD 3.6: "Start from a headroom equal to `deposit_hold_cents` multiplied by
        `leverage_multiplier`; the approved credit line is deliberately **not** available on
        the ring."

        Design: Corner/errors/leveraged_bid_cap_admits_the_ceiling_and_refuses_one_cent_over
        """
        stage = _full_paddle_on_an_open_lot()
        lot, registration, bidder = stage["lot"], stage["registration"], stage["bidder"]

        over = place_bid(registration, lot, 15_000_001, bidder)
        validate_error(over, ApiErrorId.ERR_BID_CAP_EXCEEDED, expected_status=422)
        _, empty_meta = validate_paginated(
            api_client.list_bids(OPERATOR, params={"lot_id": lot["id"]})
        )
        assert empty_meta["total_count"] == 0

        at_ceiling = validate_success(
            place_bid(registration, lot, 15_000_000, bidder), expected_status=201
        )

        assert at_ceiling["status"] == "ACTIVE"
        assert at_ceiling["amount_cents"] == 15_000_000
        stored_registration = validate_success(
            api_client.get_bidder_registration(registration["id"], SETTLEMENT)
        )
        assert stored_registration["bid_cap_cents"] == 15_000_000
        assert stored_registration["leverage_multiplier"] == 10
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"]
            == 15_000_000
        )


class TestGuardOrdering:
    def test_a_closed_ring_answers_before_the_cap_is_ever_consulted(self):
        """A 99,000,000-cent bid breaks both the open-event guard and the 15,000,000-cent cap,
        and the event guard is the one that answers.

        PRD 3.6: "Four checks police a bid, and their relative order matters. The auction must
        be `OPEN`, failing which the bid is refused with `ERR_AUCTION_NOT_OPEN`."
        PRD 3.6: "Only then are the fiscal checks reached: `amount_cents` must not exceed the
        paddle's live cap, failing which the refusal is `ERR_BID_CAP_EXCEEDED`".

        Design: Difficulty/priority_pair_validation_conflict/bid_before_auction_opens_with_cap_exceeded_reports_auction_not_open
        """
        stage = _full_paddle_on_an_open_lot(open_now=False)
        auction, registration = stage["auction"], stage["registration"]
        assert registration["status"] == "APPROVED"
        assert registration["bid_cap_cents"] == 15_000_000

        response = place_bid(registration, stage["lot"], 99_000_000, stage["bidder"])

        validate_error(response, ApiErrorId.ERR_AUCTION_NOT_OPEN, expected_status=409)
        assert response.json()["data"]["error_id"] != "ERR_BID_CAP_EXCEEDED"
        assert (
            validate_success(api_client.get_auction(auction["id"], OPERATOR))["status"]
            == "SCHEDULED"
        )

    def test_opening_the_ring_lets_the_same_bid_through_to_the_cap_refusal(self):
        """Nothing was written while the event was scheduled, and once it is open the identical
        oversized bid reports the fiscal failure instead.

        PRD 3.6: "The registration must be `APPROVED` — a `REQUESTED`, `DECLINED`, `SUSPENDED`
        or `CANCELLED` registration cannot bid — failing which the refusal is
        `ERR_REGISTRATION_NOT_APPROVED`. Only then are the fiscal checks reached".
        PRD 3.4: "**Opening** the event moves the auction `SCHEDULED → OPEN`. It requires that
        the logical clock is at or before `window_end` — an event whose window has already
        elapsed can no longer be opened — and that `assigned_lot_count` is at least 1, since
        there is nothing to sell in an empty catalogue."

        Design: Difficulty/priority_pair_validation_conflict/bid_before_auction_opens_with_cap_exceeded_reports_auction_not_open
        """
        stage = _full_paddle_on_an_open_lot(open_now=False)
        auction, lot, registration = stage["auction"], stage["lot"], stage["registration"]
        validate_error(
            place_bid(registration, lot, 99_000_000, stage["bidder"]),
            ApiErrorId.ERR_AUCTION_NOT_OPEN,
            expected_status=409,
        )
        _, meta = validate_paginated(
            api_client.list_bids(
                OPERATOR, params={"registration_id": registration["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"] == 0
        )

        opened = validate_success(api_client.open_auction(auction["id"], OPERATOR))
        assert opened["status"] == "OPEN"

        response = place_bid(registration, lot, 99_000_000, stage["bidder"])

        validate_error(response, ApiErrorId.ERR_BID_CAP_EXCEEDED, expected_status=422)
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"] == 0
        )


class TestBidsAreAppendOnly:
    def test_a_bid_records_the_clock_and_exposes_no_mutable_bookkeeping(self):
        """The accepted bid carries an id, a status and the pinned `placed_at`, and no version
        or update stamp, and reading it back returns the same row.

        PRD 3.6: "A `Bidder` places a **bid** by naming its `registration_id`, the `lot_id`
        being bid on, and an `amount_cents` between 1 and 1,000,000,000. A bid is created in
        `ACTIVE` with `placed_at` taken from the logical clock, and the lot's `high_bid_cents`
        is recomputed immediately."
        PRD 3.6: "Bids are append-only: their `status` moves to `WINNING` or `LOSING` by system
        action alone, and there is no endpoint that edits or deletes a bid."

        Design: Corner/entities/bid_is_immutable_and_carries_no_version_field
        """
        stage = open_auction_with_catalogue(
            lot_overrides={"serial_number": "CAT-D8T-0001"},
            deposit_cents=2_000_000,
            deposit_hold_cents=1_500_000,
            open_clock=BID_WINDOW_INSTANT,
        )
        lot, registration = stage["lot"], stage["registration"]

        bid = validate_success(
            place_bid(registration, lot, 11_000_000, stage["bidder"]),
            expected_status=201,
        )

        assert bid["status"] == "ACTIVE"
        assert bid["placed_at"].startswith("2026-08-10T16:00:00")
        assert "version" not in bid
        assert "updated_at" not in bid

        stored = validate_success(api_client.get_bid(bid["id"], stage["bidder_headers"]))
        assert stored["id"] == bid["id"]
        assert stored["amount_cents"] == 11_000_000
        assert stored["placed_at"] == bid["placed_at"]
        assert "version" not in stored
        assert (
            validate_success(api_client.get_lot(lot["id"], OPERATOR))["high_bid_cents"]
            == 11_000_000
        )
