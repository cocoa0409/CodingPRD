"""Opening lots, the mobile bidding gates, the increment floor and retraction."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_bid,
    close_lot,
    create_bid_payload,
    create_lot,
    create_open_lot,
    make_bidder_headers,
    open_lot,
    place_bid,
    read_auction_item,
    read_bid,
    read_event,
    set_clock,
    setup_live_channel_lots,
    setup_open_lot_scenario,
    setup_proxy_leader_scenario,
    setup_published_event,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


def test_bid_effective_max_is_max_of_amount_and_proxy(api):
    """PRD §3.5: "Each bid stores a computed `effective_max_cents` equal to
    whichever is larger of its `amount_cents` and its `proxy_max_cents`; that
    is the sort key used to pick a leader."
    PRD §3.5: "Under the `PROXY_SETTLED` interpretation — the one the system
    itself uses for `current_leading_amount_cents`, for the increment floor
    above, and for the price frozen at close — a lone leader with no runner-up
    is valued at that leader's own `amount_cents`."

    Design: Corner/entities/bid_effective_max_is_computed_from_amount_and_proxy
    """
    env = setup_open_lot_scenario(bidder_count=1)
    guest = env["bidders"][0]

    response = api.place_bid(
        env["lot"]["id"],
        create_bid_payload(guest["id"], 10_000, proxy_max_cents=20_000),
        make_bidder_headers(guest["id"]),
    )
    bid = validate_success(response, 201)

    assert_bid(bid)
    assert bid["effective_max_cents"] == 20_000, (
        f"max(10000, 20000) is 20000, got {bid['effective_max_cents']}"
    )
    assert bid["status"] == "ACTIVE"
    assert read_auction_item(env["lot"]["id"])["current_leading_amount_cents"] == 10_000, (
        "A lone leader is valued at its own placed amount, not its ceiling"
    )


def test_bid_without_card_on_file_is_refused(api):
    """PRD §3.5: "Two gates apply before a bid is accepted: the acting guest
    must have `payment_method_on_file` set to true, else `ERR_NO_PAYMENT_METHOD`
    (HTTP 402); and the target lot must be in `listing_status` of `OPEN` with
    the clock inside its window, else `ERR_ITEM_NOT_OPEN`."

    Design: Corner/validations/bid_without_card_on_file_returns_no_payment_method
    """
    env = setup_published_event(bidder_count=1, payment_methods_on_file=False)
    lot = create_open_lot(env["event"]["id"])
    env["lot"] = lot
    guest = env["bidders"][0]

    response = api.place_bid(
        lot["id"],
        create_bid_payload(guest["id"], 10_000),
        make_bidder_headers(guest["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NO_PAYMENT_METHOD.value, 402)
    assert read_auction_item(env["lot"]["id"])["current_leading_amount_cents"] == 0, (
        "A refused bid leaves the leading amount at zero"
    )


def test_bidder_cannot_bid_for_another_guest(api):
    """PRD §2.1: "Concretely, a guest placing a bid, opening a table hold,
    releasing a hold, buying a ticket order, updating their own stored payment
    method, or paying their own invoice must be acting on their own record —
    for a payment, the check is against the `bidder_id` of the invoice being
    paid."
    PRD §2.1: "A violation of any of these ownership checks yields
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/bidder_cannot_place_a_bid_for_another_bidder
    """
    env = setup_open_lot_scenario(bidder_count=2)
    guest_a, guest_b = env["bidders"]

    response = api.place_bid(
        env["lot"]["id"],
        create_bid_payload(guest_a["id"], 12_000),
        make_bidder_headers(guest_b["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert read_auction_item(env["lot"]["id"])["current_leading_amount_cents"] == 0


def test_opening_a_lot_outside_its_window_is_refused(api):
    """PRD §3.5: "The clock must lie inside the lot's half-open window, at or
    after `open_at_utc` and strictly before `close_at_utc`, else
    `ERR_LOT_WINDOW_CLOSED`."

    Design: Corner/validations/opening_a_lot_outside_its_window_is_refused
    """
    env = setup_published_event(bidder_count=0)
    lot = create_lot(env["event"]["id"])
    set_clock("2026-08-01T00:00:00Z")

    response = api.open_auction_item(lot["id"], TEST_USERS["auction_manager_headers"])

    validate_error(response, ApiErrorId.ERR_LOT_WINDOW_CLOSED.value, 409)
    assert read_auction_item(lot["id"])["listing_status"] == "DRAFT", (
        "A refused open leaves the lot in DRAFT"
    )
    assert read_event(env["event"]["id"])["open_lot_count"] == 0


def test_retract_bid_on_awarded_lot_is_locked_out(api):
    """PRD §3.5: "Retraction is an auction-manager action taking a bid
    `ACTIVE → RETRACTED`; it requires the bid to be `ACTIVE` and its lot to
    still be in `listing_status` of `OPEN`, else `ERR_ITEM_NOT_OPEN`."
    PRD §3.5: "If at least one is, the lot goes `OPEN → AWARDED`:
    `hammer_price_cents` is frozen to the proxy-settled valuation described
    above, `winning_bid_id` is set to the leading bid's id, that leading bid
    moves `ACTIVE → WON` while every other `ACTIVE` bid on the lot moves
    `ACTIVE → LOST` (each bid advancing its own `version`), and the settlement
    dimension moves `UNSETTLED → INVOICED` in the same request."

    Design: Corner/state_machines/retract_bid_on_awarded_lot_is_locked_out
    """
    env = setup_open_lot_scenario(bidder_count=1)
    guest = env["bidders"][0]
    bid = place_bid(env["lot"]["id"], guest["id"], 12_500)
    close_lot(env["lot"]["id"])

    response = api.retract_bid(bid["id"], TEST_USERS["auction_manager_headers"])

    # The bid is no longer ACTIVE *and* its lot is no longer OPEN; §2.5 orders
    # the generic state check ahead of the bidding-window check, so either
    # rejection is faithful to the contract.
    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ITEM_NOT_OPEN.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    assert read_bid(bid["id"])["status"] == "WON", (
        "The winning bid stays WON after a refused retraction"
    )


class TestIncrementFloor:
    """PRD §3.5's inclusive bid floor over the proxy-settled leading amount."""

    def test_bid_one_cent_below_increment_floor_is_refused(self, api):
        """PRD §3.5: "Otherwise it must be at least the lot's current
        `current_leading_amount_cents` plus its `min_increment_cents`."
        PRD §3.5: "Both comparisons are inclusive, so a bid landing exactly on
        the floor is accepted; anything below it is refused with
        `ERR_BID_TOO_LOW` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/bid_exactly_at_increment_floor_is_accepted
        """
        env = setup_proxy_leader_scenario()
        guest_b = env["bidders"][1]
        assert env["lot"]["current_leading_amount_cents"] == 12_500

        response = api.place_bid(
            env["lot"]["id"],
            create_bid_payload(guest_b["id"], 12_999),
            make_bidder_headers(guest_b["id"]),
        )

        validate_error(response, ApiErrorId.ERR_BID_TOO_LOW.value, 422)

    def test_bid_exactly_at_increment_floor_is_accepted(self, api):
        """PRD §3.5: "Both comparisons are inclusive, so a bid landing exactly
        on the floor is accepted; anything below it is refused with
        `ERR_BID_TOO_LOW` (HTTP 422)."
        PRD §3.5: "When a runner-up exists, the proxy agent lifts the leader
        only as far as one minimum increment above the runner-up's own
        `effective_max_cents`, but never past the leader's own ceiling: the
        valuation is whichever is smaller of the leader's `effective_max_cents`
        and the runner-up's `effective_max_cents` plus the lot's
        `min_increment_cents`."

        Design: Difficulty/boundary_precision_check/bid_exactly_at_increment_floor_is_accepted
        """
        env = setup_proxy_leader_scenario()
        guest_b = env["bidders"][1]

        response = api.place_bid(
            env["lot"]["id"],
            create_bid_payload(guest_b["id"], 13_000),
            make_bidder_headers(guest_b["id"]),
        )
        bid = validate_success(response, 201)

        assert bid["status"] == "ACTIVE", (
            f"A bid exactly on the 13000 floor is accepted, got {bid['status']}"
        )
        assert read_auction_item(env["lot"]["id"])["current_leading_amount_cents"] == 13_500, (
            "The 20000-ceiling leader is lifted to one increment above the new "
            "13000 runner-up"
        )


class TestClosedLotBeatsMissingCard:
    """PRD §2.5's ordering when a bid violates both the window and card gates."""

    def _setup(self):
        env = setup_published_event(
            bidder_count=2, payment_methods_on_file=[True, False]
        )
        env["lot"] = open_lot(create_lot(env["event"]["id"])["id"])
        place_bid(env["lot"]["id"], env["bidders"][0]["id"], 12_500)
        env["lot"] = close_lot(env["lot"]["id"])
        return env

    def test_closed_lot_beats_missing_card_on_bid(self, api):
        """PRD §2.5: "Bidding-window state on bid placement and bid retraction,
        else `ERR_ITEM_NOT_OPEN`."
        PRD §2.5: "A stored payment method on the acting guest for bidding and
        paddle-raising, else `ERR_NO_PAYMENT_METHOD`."
        PRD §2.5: "Checks are applied in the following strict order, and the
        first failure decides the response."

        Design: Difficulty/priority_pair_validation_conflict/closed_lot_beats_missing_card_on_bid
        """
        env = self._setup()
        cardless = env["bidders"][1]

        response = api.place_bid(
            env["lot"]["id"],
            create_bid_payload(cardless["id"], 99_999),
            make_bidder_headers(cardless["id"]),
        )

        validate_error(response, ApiErrorId.ERR_ITEM_NOT_OPEN.value, 409)

    def test_bid_rejected_on_awarded_lot_leaves_the_lot_untouched(self, api):
        """PRD §3.5: "The listing dimension runs `DRAFT → OPEN` and then forks
        to either `AWARDED` or `PASSED`, both terminal."
        PRD §3.5: "Two gates apply before a bid is accepted: the acting guest
        must have `payment_method_on_file` set to true, else
        `ERR_NO_PAYMENT_METHOD` (HTTP 402); and the target lot must be in
        `listing_status` of `OPEN` with the clock inside its window, else
        `ERR_ITEM_NOT_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/closed_lot_beats_missing_card_on_bid
        """
        env = self._setup()
        cardless = env["bidders"][1]
        hammer_before = read_auction_item(env["lot"]["id"])["hammer_price_cents"]

        api.place_bid(
            env["lot"]["id"],
            create_bid_payload(cardless["id"], 99_999),
            make_bidder_headers(cardless["id"]),
        )

        lot = read_auction_item(env["lot"]["id"])
        assert lot["listing_status"] == "AWARDED", (
            f"AWARDED is terminal on the listing axis, got {lot['listing_status']}"
        )
        assert lot["hammer_price_cents"] == hammer_before, (
            "A refused bid cannot move the frozen hammer price"
        )
        rows, _ = _bids_for_bidder(api, cardless["id"])
        assert rows == [], "A refused bid creates no Bid row"


def _bids_for_bidder(api, bidder_id):
    return validate_paginated(
        api.list_bids(TEST_USERS["auction_manager_headers"], params={"bidder_id": bidder_id})
    )


class TestLiveChannelWindows:
    """PRD §3.5's half-open stage-channel conflict check."""

    def test_overlapping_live_channel_window_is_refused(self, api):
        """PRD §3.5: "Finally, when the lot has a non-null `live_lot_sequence`,
        no other lot of the same event sharing that same sequence number and
        currently in `OPEN` may have a window overlapping this lot's window;
        overlap is computed on half-open intervals, so a lot starting at exactly
        the instant another ends does not conflict, while any true overlap is
        refused with `ERR_LOT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/live_channel_windows_are_half_open_adjacency_allowed
        """
        env = setup_live_channel_lots()

        response = api.open_auction_item(
            env["lot_c"]["id"], TEST_USERS["auction_manager_headers"]
        )

        validate_error(response, ApiErrorId.ERR_LOT_WINDOW_CONFLICT.value, 409)
        assert read_auction_item(env["lot_c"]["id"])["listing_status"] == "DRAFT", (
            "The straddling lot stays in DRAFT"
        )

    def test_adjacent_live_channel_window_opens_cleanly(self, api):
        """PRD §3.5: "Finally, when the lot has a non-null `live_lot_sequence`,
        no other lot of the same event sharing that same sequence number and
        currently in `OPEN` may have a window overlapping this lot's window;
        overlap is computed on half-open intervals, so a lot starting at exactly
        the instant another ends does not conflict, while any true overlap is
        refused with `ERR_LOT_WINDOW_CONFLICT`."
        PRD §3.5: "Opening increases the event's `open_lot_count` by one and
        advances the lot's `version`."

        Design: Difficulty/resource_temporal_overlap/live_channel_windows_are_half_open_adjacency_allowed
        """
        env = setup_live_channel_lots()
        set_clock("2026-07-05T20:00:00Z")

        response = api.open_auction_item(
            env["lot_b"]["id"], TEST_USERS["auction_manager_headers"]
        )
        lot_b = validate_success(response, 200)

        assert lot_b["listing_status"] == "OPEN", (
            "A lot starting exactly when the incumbent ends does not conflict, got "
            f"{lot_b['listing_status']}"
        )
        assert read_event(env["event"]["id"])["open_lot_count"] == 2, (
            "Both the incumbent and the adjacent lot are open"
        )
