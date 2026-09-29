"""Auction bidding: window gates, safety rules, proxy resolution and anti-sniping."""

from test_helpers import (
    ADMIN,
    AUCTION_OPENING_BID_CENTS,
    AUCTION_WINDOW_END,
    AUCTION_WINDOW_START,
    CANONICAL_SELLER_TAX_ID,
    INSIDE_WINDOW_CLOCK,
    add_buyer,
    api_client,
    assert_bid,
    assert_instant,
    auction_listing_payload,
    bid_payload,
    bootstrap_marketplace,
    create_brand_policy,
    create_listing,
    make_buyer_headers,
    proxy_bid_payload,
    publish_listing,
    read_bid,
    read_buyer,
    read_listing,
    read_lot,
    set_clock,
    setup_approved_lot,
    setup_open_auction,
    total_count,
    validate_error,
    validate_success,
)

TWO_HUNDRED_UNIT_LINES = [
    {
        "sku": "APP-RET-0200",
        "unit_count": 200,
        "unit_retail_cents": 10_000,
        "declared_condition": "USED_GOOD",
    },
]

BID_INCREMENT_CENTS = 100_000


def test_window_and_proxy_floor_refusals_leave_the_listing_untouched():
    """A bid one second early, a bid at the closing instant and a proxy ceiling
    below the published floor are each refused without advancing the listing.

    PRD 3.4: "At band 12 the offering window must be open: the current logical
    clock must be at or after `window_start_at`, otherwise
    `ERR_LISTING_WINDOW_NOT_OPEN`, and strictly before `effective_close_at`,
    otherwise `ERR_LISTING_WINDOW_CLOSED`; this window test guards live bids,
    proxy bids and negotiation openings alike."
    PRD 3.4: "At band 16 the amount must clear the floor and the credit ceiling
    must not be breached: a live auction bid's `amount_cents` must be at least the
    listing's published `min_next_bid_cents`, with the comparison inclusive, or
    the bid is refused with `ERR_BID_BELOW_MINIMUM`; a proxy bid's
    `max_amount_cents` must likewise be at least `min_next_bid_cents`, or the
    submission is refused with `ERR_PROXY_MAX_BELOW_MINIMUM`; and the exposure
    rule of §3.2 must admit the new commitment."
    PRD 3.4: "Fifth, the listing republishes `min_next_bid_cents`: it equals
    `opening_bid_cents` while `current_high_bid_cents` is null, and otherwise
    equals `current_high_bid_cents` plus `bid_increment_cents`."

    Design: Corner/errors/bidding_window_and_proxy_minimum_errors_are_all_reachable
    """
    env = bootstrap_marketplace()
    built = setup_open_auction(env, lines=TWO_HUNDRED_UNIT_LINES)
    listing = built["listing"]
    buyer_id = env["buyer"]["id"]
    version_at_publication = listing["version"]

    set_clock("2026-08-04T23:59:59Z")
    too_early = api_client.place_bid(
        listing["id"], bid_payload(buyer_id, 1_000_000), env["buyer_headers"]
    )
    validate_error(too_early, "ERR_LISTING_WINDOW_NOT_OPEN", 422)

    set_clock(AUCTION_WINDOW_START)
    under_floor = api_client.place_proxy_bid(
        listing["id"],
        proxy_bid_payload(buyer_id, 999_999, version_at_publication),
        env["buyer_headers"],
    )
    validate_error(under_floor, "ERR_PROXY_MAX_BELOW_MINIMUM", 422)

    set_clock(AUCTION_WINDOW_END)
    too_late = api_client.place_bid(
        listing["id"], bid_payload(buyer_id, 1_100_000), env["buyer_headers"]
    )
    validate_error(too_late, "ERR_LISTING_WINDOW_CLOSED", 422)

    reread = read_listing(env, listing["id"])
    assert reread["bid_count"] == 0
    assert reread["current_high_bid_cents"] is None
    assert reread["min_next_bid_cents"] == AUCTION_OPENING_BID_CENTS
    assert reread["extension_count"] == 0
    assert reread["version"] == version_at_publication
    assert read_buyer(env)["outstanding_exposure_cents"] == 0


def test_an_affiliated_buyer_cannot_bid_on_its_own_sellers_lot():
    """A fully qualified buyer sharing the seller's tax_id is refused, while an
    unaffiliated buyer's identical bid takes the lead.

    PRD 3.4: "The **anti-shill control**: the bidding buyer's `tax_id` must differ
    from the `tax_id` of the lot's selling account, so a seller cannot inflate its
    own lot through an affiliated buyer registration; a match is
    `ERR_SHILL_BIDDING_PROHIBITED`, and this rule guards three operations —
    placing a live bid, placing a proxy bid, and opening a negotiation."
    PRD 3.2: "The first part covers live bidding commitments: over all of this
    buyer's bids whose `bid_status` is either `STANDING` or `WINNING`, sum each
    bid's `ceiling_cents` plus the buyer premium that ceiling would attract, where
    that premium is the ceiling multiplied by the premium rate its own amount
    selects from the tier table in §3.6, divided by 10,000 and rounded half up to
    a whole cent before being added into the sum."

    Design: Corner/validations/shill_bid_blocked_when_buyer_tax_id_matches_the_seller_tax_id
    """
    env = bootstrap_marketplace(
        buyer_overrides={
            "tax_id": CANONICAL_SELLER_TAX_ID,
            "legal_name": "Northline Trading Arm",
            "state_code": "OH",
            "contact_email": "arm@northline.example",
        }
    )
    unaffiliated = add_buyer(env)
    built = setup_open_auction(
        env, lines=TWO_HUNDRED_UNIT_LINES, clock=INSIDE_WINDOW_CLOCK
    )
    listing = built["listing"]
    affiliated_id = env["buyer"]["id"]

    refused = api_client.place_bid(
        listing["id"], bid_payload(affiliated_id, 1_000_000), env["buyer_headers"]
    )
    validate_error(refused, "ERR_SHILL_BIDDING_PROHIBITED", 422)
    assert env["buyer"]["qualification_status"] == "QUALIFIED"
    assert total_count(
        api_client.list_bids(ADMIN, {"listing_id": listing["id"], "buyer_id": affiliated_id})
    ) == 0
    assert read_buyer(env, affiliated_id)["outstanding_exposure_cents"] == 0

    accepted = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(unaffiliated["id"], 1_000_000),
            make_buyer_headers(unaffiliated["id"]),
        ),
        201,
    )
    assert_bid(accepted)
    assert accepted["bid_status"] == "WINNING"
    assert accepted["bid_type"] == "LIVE"
    assert accepted["ceiling_cents"] == 1_000_000

    reread = read_listing(env, listing["id"])
    assert reread["bid_count"] == 1
    assert reread["current_high_bid_cents"] == 1_000_000
    assert reread["current_high_bidder_id"] == unaffiliated["id"]
    assert read_buyer(env, unaffiliated["id"])["outstanding_exposure_cents"] == 1_140_000


def test_a_prohibited_state_blocks_only_the_lot_that_carries_the_policy():
    """The geographic restriction lives on the lot's brand policy: the Texas buyer
    is refused on the protected lot yet leads the unprotected one, and the Arizona
    buyer leads the protected lot.

    PRD 3.4: "The **geographic restriction**: the bidder's `state_code` must not
    appear in the lot's brand policy's `prohibited_buyer_state_codes`, or the
    attempt is `ERR_BUYER_STATE_PROHIBITED`; this rule guards four operations —
    placing a live bid, placing a proxy bid, opening a negotiation, and countering
    within a negotiation — and it is applied once more at auction close against the
    prospective winner."

    Design: Corner/validations/buyer_from_a_prohibited_state_cannot_bid_on_the_protected_lot
    """
    env = bootstrap_marketplace(buyer_overrides={"state_code": "TX"})
    arizona = add_buyer(env)
    policy = create_brand_policy(
        "GEOFENCE", ["MARKETPLACE_RESALE"], prohibited_buyer_state_codes=["TX"]
    )
    protected = setup_open_auction(
        env,
        lines=TWO_HUNDRED_UNIT_LINES,
        lot_overrides={"brand_policy_id": policy["id"], "title": "Geofenced returns"},
        clock=INSIDE_WINDOW_CLOCK,
    )
    unprotected = setup_open_auction(
        env, lines=TWO_HUNDRED_UNIT_LINES, lot_overrides={"title": "Unbranded returns"}
    )
    texas_id = env["buyer"]["id"]

    refused = api_client.place_bid(
        protected["listing"]["id"],
        bid_payload(texas_id, 1_000_000),
        env["buyer_headers"],
    )
    validate_error(refused, "ERR_BUYER_STATE_PROHIBITED", 422)

    elsewhere = validate_success(
        api_client.place_bid(
            unprotected["listing"]["id"],
            bid_payload(texas_id, 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    assert elsewhere["bid_status"] == "WINNING"

    admitted = validate_success(
        api_client.place_bid(
            protected["listing"]["id"],
            bid_payload(arizona["id"], 1_000_000),
            make_buyer_headers(arizona["id"]),
        ),
        201,
    )
    assert admitted["bid_status"] == "WINNING"

    protected_reread = read_listing(env, protected["listing"]["id"])
    assert protected_reread["bid_count"] == 1
    assert protected_reread["current_high_bidder_id"] == arizona["id"]
    assert read_buyer(env, texas_id)["outstanding_exposure_cents"] == 1_140_000


def test_closing_before_the_effective_close_is_refused():
    """An auction closed an hour early keeps its OPEN status, its winning bid and
    its listed lot, and no sale order appears.

    PRD 3.5: "The close is refused with `ERR_AUCTION_NOT_CLOSABLE` while the
    current logical clock is strictly before `effective_close_at` — including when
    the clock has passed `window_end_at` but an anti-sniping extension has moved
    the effective close beyond it."
    PRD 3.5: "Otherwise the outcome is a sale: the listing advances `OPEN →
    CLOSED_SOLD`, `hammer_price_cents` is pinned to the listing's
    `current_high_bid_cents`, the single bid whose `bid_status` was `WINNING`
    becomes `WON` while every other qualifying bid becomes `LOST`, the lot advances
    `LISTED → SOLD`, and exactly one sale order is created with `sale_source`
    `AUCTION_CLOSE`."

    Design: Corner/state_machines/closure_before_effective_close_is_rejected_as_not_closable
    """
    env = bootstrap_marketplace()
    built = setup_open_auction(
        env,
        lines=TWO_HUNDRED_UNIT_LINES,
        listing_overrides={"reserve_price_cents": 1_000_000},
        clock=INSIDE_WINDOW_CLOCK,
    )
    listing = built["listing"]
    bid = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(env["buyer"]["id"], 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )

    set_clock("2026-08-11T23:00:00Z")
    refused = api_client.close_listing(listing["id"], {}, env["closer_headers"])
    validate_error(refused, "ERR_AUCTION_NOT_CLOSABLE", 422)

    reread = read_listing(env, listing["id"])
    assert reread["listing_status"] == "OPEN"
    assert_instant(reread["effective_close_at"], AUCTION_WINDOW_END)
    assert read_bid(env, bid["id"])["bid_status"] == "WINNING"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "LISTED"
    assert total_count(
        api_client.list_sale_orders(ADMIN, {"listing_id": listing["id"]})
    ) == 0


def test_anti_sniping_extends_only_from_the_inclusive_snipe_boundary():
    """A bid with 121 seconds left grants nothing; a bid with exactly 120 seconds
    left pushes the effective close out by five minutes without touching the
    scheduled window end.

    PRD 3.4: "An extension is granted when four conditions hold together: the
    format is `AUCTION`; the seconds remaining are not negative; the seconds
    remaining are at most two minutes, with the boundary inclusive, so a bid
    landing exactly 120 seconds before the effective close does extend the auction
    while one landing 121 seconds before does not; and `extension_count` is
    strictly below three."
    PRD 3.4: "When granted, `effective_close_at` moves out by five minutes
    **measured from its own current value, not from the time of the bid**, and
    `extension_count` increases by one."
    PRD 3.4: "The scheduled `window_end_at` is never modified; only
    `effective_close_at` moves, which is why the listing exposes both."
    PRD 3.5: "The close is refused with `ERR_AUCTION_NOT_CLOSABLE` while the
    current logical clock is strictly before `effective_close_at` — including when
    the clock has passed `window_end_at` but an anti-sniping extension has moved
    the effective close beyond it."

    Design: Corner/calculations/anti_sniping_extension_fires_at_exactly_the_snipe_window_boundary
    """
    env = bootstrap_marketplace()
    second_buyer = add_buyer(env)
    built = setup_approved_lot(env, TWO_HUNDRED_UNIT_LINES)
    no_reserve = auction_listing_payload()
    del no_reserve["reserve_price_cents"]
    listing = publish_listing(
        env, create_listing(env, built["lot"]["id"], no_reserve)["id"]
    )

    set_clock("2026-08-11T23:57:59Z")
    early = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(env["buyer"]["id"], 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    outside_window = read_listing(env, listing["id"])
    assert outside_window["extension_count"] == 0
    assert_instant(outside_window["effective_close_at"], AUCTION_WINDOW_END)
    assert outside_window["current_high_bid_cents"] == 1_000_000
    assert outside_window["min_next_bid_cents"] == 1_100_000

    set_clock("2026-08-11T23:58:00Z")
    sniper = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(second_buyer["id"], 1_100_000),
            make_buyer_headers(second_buyer["id"]),
        ),
        201,
    )
    extended = read_listing(env, listing["id"])
    assert extended["extension_count"] == 1
    assert_instant(extended["effective_close_at"], "2026-08-12T00:05:00Z")
    assert_instant(extended["window_end_at"], AUCTION_WINDOW_END)
    assert extended["current_high_bid_cents"] == 1_100_000
    assert extended["min_next_bid_cents"] == 1_200_000
    assert extended["current_high_bidder_id"] == second_buyer["id"]
    assert extended["bid_count"] == 2
    assert read_bid(env, sniper["id"])["bid_status"] == "WINNING"
    assert read_bid(env, early["id"])["bid_status"] == "STANDING"

    set_clock(AUCTION_WINDOW_END)
    refused = api_client.close_listing(listing["id"], {}, env["closer_headers"])
    validate_error(refused, "ERR_AUCTION_NOT_CLOSABLE", 422)


def test_proxy_resolution_publishes_the_nested_minimum_of_three_inputs():
    """The published price is the smaller of the proxy ceiling and the challenger's
    amount plus one increment, so the ladder runs 1,000,000 to 1,100,000 to
    2,700,000 with a 2,800,000 floor.

    PRD 3.4: "With two or more candidates, `current_high_bidder_id` becomes the
    leader's `buyer_id` and `current_high_bid_cents` becomes the smaller of the
    leader's own `ceiling_cents` and the runner-up's `ceiling_cents` plus the
    listing's `bid_increment_cents` — the leader pays only enough to beat the
    runner-up by one increment, never its full ceiling."
    PRD 3.4: "With exactly one candidate, `current_high_bidder_id` becomes that
    candidate's `buyer_id`, and `current_high_bid_cents` becomes the greater of the
    listing's `opening_bid_cents` and — only when that sole candidate is a `LIVE`
    bid — its own `amount_cents`; a sole `PROXY` candidate produces a public price
    of exactly `opening_bid_cents`, which is what keeps a hidden ceiling hidden."
    PRD 3.4: "Fifth, the listing republishes `min_next_bid_cents`: it equals
    `opening_bid_cents` while `current_high_bid_cents` is null, and otherwise
    equals `current_high_bid_cents` plus `bid_increment_cents`."

    Design: Difficulty/combinatorial_formula/proxy_bid_public_price_from_nested_min_of_three_inputs
    """
    env = bootstrap_marketplace()
    challenger = env["buyer"]
    proxy_buyer = add_buyer(env)
    built = setup_open_auction(env, clock=INSIDE_WINDOW_CLOCK)
    listing = built["listing"]

    validate_success(
        api_client.place_bid(
            listing["id"], bid_payload(challenger["id"], 1_000_000), env["buyer_headers"]
        ),
        201,
    )
    after_first = read_listing(env, listing["id"])
    assert after_first["current_high_bid_cents"] == 1_000_000

    validate_success(
        api_client.place_proxy_bid(
            listing["id"],
            proxy_bid_payload(proxy_buyer["id"], 3_000_000, after_first["version"]),
            make_buyer_headers(proxy_buyer["id"]),
        ),
        201,
    )
    after_proxy = read_listing(env, listing["id"])
    assert after_proxy["current_high_bid_cents"] == 1_100_000
    assert after_proxy["current_high_bidder_id"] == proxy_buyer["id"]

    validate_success(
        api_client.place_bid(
            listing["id"], bid_payload(challenger["id"], 2_600_000), env["buyer_headers"]
        ),
        201,
    )

    final = read_listing(env, listing["id"])
    assert final["current_high_bid_cents"] == 2_700_000
    assert final["min_next_bid_cents"] == 2_800_000
    assert final["current_high_bidder_id"] == proxy_buyer["id"]


def test_the_outbid_proxy_keeps_its_ceiling_hidden_and_each_write_bumps_the_version():
    """The proxy row records the hidden ceiling alongside the resolved public
    price, the challenger's earlier bid is superseded, the boundary reserve is met
    and each of the two writes advances the listing version once.

    PRD 3.4: "A proxy bid payload names `buyer_id`, states a hidden
    `max_amount_cents` ceiling, and carries the `expected_listing_version` required
    by §2.7; the resulting `Bid` records `bid_type` as `PROXY`, sets
    `ceiling_cents` equal to `max_amount_cents`, and sets `amount_cents` to the
    resolved public price at the moment of placement rather than to the ceiling."
    PRD 3.4: "First, the pool is collapsed to one candidate per distinct
    `buyer_id`: when a buyer places a new bid, that buyer's earlier `STANDING` or
    `WINNING` bid on the same listing is set to `SUPERSEDED`, so the pool naturally
    holds at most one entry per buyer."
    PRD 3.4: "Fourth, statuses are settled: the leader's `bid_status` becomes
    `WINNING` and every other candidate's `bid_status` remains `STANDING`, and the
    leader's `meets_reserve` is snapshotted from the newly computed reserve test."
    PRD 3.4: "The comparison is inclusive at the reserve, so a high bid landing
    exactly on the reserve satisfies it while a high bid one cent short does not."
    PRD 2.4: "Concretely: every accepted live bid, proxy bid, publication and
    closure on a listing increments that `Listing`'s `version` by exactly 1, and
    every accepted counter-offer and acceptance on a negotiation increments that
    `Negotiation`'s `version` by exactly 1."

    Design: Difficulty/combinatorial_formula/proxy_bid_public_price_from_nested_min_of_three_inputs
    """
    env = bootstrap_marketplace()
    challenger = env["buyer"]
    proxy_buyer = add_buyer(env)
    built = setup_open_auction(env, clock=INSIDE_WINDOW_CLOCK)
    listing = built["listing"]

    first_bid = validate_success(
        api_client.place_bid(
            listing["id"], bid_payload(challenger["id"], 1_000_000), env["buyer_headers"]
        ),
        201,
    )
    version_before = read_listing(env, listing["id"])["version"]

    proxy = validate_success(
        api_client.place_proxy_bid(
            listing["id"],
            proxy_bid_payload(proxy_buyer["id"], 3_000_000, version_before),
            make_buyer_headers(proxy_buyer["id"]),
        ),
        201,
    )
    second_bid = validate_success(
        api_client.place_bid(
            listing["id"], bid_payload(challenger["id"], 2_600_000), env["buyer_headers"]
        ),
        201,
    )

    settled_proxy = read_bid(env, proxy["id"])
    assert settled_proxy["bid_type"] == "PROXY"
    assert settled_proxy["ceiling_cents"] == 3_000_000
    # PRD 3.4 fixes amount_cents at "the resolved public price at the moment of
    # placement": with the 1,000,000 live bid as runner-up that price was
    # min(3,000,000, 1,000,000 + 100,000) = 1,100,000.
    assert settled_proxy["amount_cents"] == 1_100_000
    assert settled_proxy["bid_status"] == "WINNING"
    assert settled_proxy["meets_reserve"] is True
    assert read_bid(env, first_bid["id"])["bid_status"] == "SUPERSEDED"
    assert read_bid(env, second_bid["id"])["bid_status"] == "STANDING"

    final = read_listing(env, listing["id"])
    # The nested minimum after the 2,600,000 challenge: min(3,000,000, 2,600,000 +
    # 100,000) = 2,700,000, which is exactly the reserve.
    assert final["current_high_bid_cents"] == 2_700_000
    assert final["current_high_bidder_id"] == proxy_buyer["id"]
    assert final["min_next_bid_cents"] == 2_800_000
    assert final["reserve_met"] is True
    # PRD 3.4: "The listing's `bid_count` counts this listing's bids whose
    # `bid_status` is `STANDING`, `WINNING`, `WON` or `LOST`."  The challenger's
    # first bid is SUPERSEDED, so only the proxy (WINNING) and the challenger's
    # second bid (STANDING) are counted.
    assert final["bid_count"] == 2
    assert final["extension_count"] == 0
    assert_instant(final["effective_close_at"], AUCTION_WINDOW_END)
    assert final["version"] == version_before + 2


def test_a_stale_listing_version_rejects_the_proxy_bid_and_the_replay_succeeds():
    """Another buyer's live bid invalidates the version the proxy bidder read, so
    the submission is refused with no side effects and the same body succeeds once
    the fresh version is echoed.

    PRD 2.7: "A proxy bid encodes a hidden ceiling relative to the auction state
    the buyer believed was current; if any other write has advanced that listing's
    `version` in the meantime — another buyer's live bid, another buyer's proxy
    bid, an anti-sniping extension, or the publication itself — the submission is
    rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412) and no `Bid` row is
    created, no exposure is recomputed and no extension is granted."
    PRD 3.4: "With two or more candidates, `current_high_bidder_id` becomes the
    leader's `buyer_id` and `current_high_bid_cents` becomes the smaller of the
    leader's own `ceiling_cents` and the runner-up's `ceiling_cents` plus the
    listing's `bid_increment_cents` — the leader pays only enough to beat the
    runner-up by one increment, never its full ceiling."
    PRD 3.4: "For a proxy bid the exposure is computed on the hidden ceiling, not
    on the public price the bid produces."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_listing_version_rejects_the_proxy_bid_then_the_fresh_version_succeeds
    """
    env = bootstrap_marketplace()
    proxy_buyer = add_buyer(env)
    built = setup_open_auction(
        env,
        lines=TWO_HUNDRED_UNIT_LINES,
        listing_overrides={
            "reserve_price_cents": 1_000_000,
            "window_end_at": "2026-08-20T00:00:00Z",
        },
        clock="2026-08-06T01:00:00Z",
    )
    listing = built["listing"]
    stale_version = listing["version"]

    live = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(env["buyer"]["id"], 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    after_live = read_listing(env, listing["id"])
    assert after_live["current_high_bid_cents"] == 1_000_000
    assert after_live["current_high_bidder_id"] == env["buyer"]["id"]
    assert after_live["bid_count"] == 1
    assert after_live["min_next_bid_cents"] == 1_100_000
    assert after_live["reserve_met"] is True

    stale = api_client.place_proxy_bid(
        listing["id"],
        proxy_bid_payload(proxy_buyer["id"], 3_000_000, stale_version),
        make_buyer_headers(proxy_buyer["id"]),
    )
    validate_error(stale, "ERR_STALE_LISTING_VERSION", 412)
    assert read_listing(env, listing["id"])["bid_count"] == 1
    assert total_count(api_client.list_bids(ADMIN, {"listing_id": listing["id"]})) == 1
    assert read_buyer(env, proxy_buyer["id"])["outstanding_exposure_cents"] == 0

    fresh_version = read_listing(env, listing["id"])["version"]
    assert fresh_version == stale_version + 1

    replay = validate_success(
        api_client.place_proxy_bid(
            listing["id"],
            proxy_bid_payload(proxy_buyer["id"], 3_000_000, fresh_version),
            make_buyer_headers(proxy_buyer["id"]),
        ),
        201,
    )
    assert replay["bid_type"] == "PROXY"
    assert replay["max_amount_cents"] == 3_000_000
    assert replay["bid_status"] == "WINNING"

    resolved = read_listing(env, listing["id"])
    assert resolved["current_high_bid_cents"] == 1_100_000
    assert resolved["current_high_bidder_id"] == proxy_buyer["id"]
    assert resolved["min_next_bid_cents"] == 1_200_000
    assert read_bid(env, live["id"])["bid_status"] == "STANDING"
    assert read_buyer(env, proxy_buyer["id"])["outstanding_exposure_cents"] == 3_300_000


def test_a_bid_on_a_closed_listing_reports_the_state_error_not_the_money_error():
    """The one-cent bid violates both the lifecycle rule and the published minimum,
    and only the lower-numbered state band may answer.

    PRD 2.5: "The response is never ambiguous: the platform evaluates checks in
    sixteen numbered bands and returns the error belonging to the
    **lowest-numbered band** that fails, stopping there."
    PRD 2.5: "**State of the target resource.** The entity being written is in a
    state from which the requested transition is legal: `ERR_LOT_STATE_INVALID`
    (409), `ERR_LISTING_STATE_INVALID` (409), `ERR_NEGOTIATION_STATE_INVALID` or
    `ERR_NOT_YOUR_TURN` (409), `ERR_ORDER_PAYMENT_STATE_INVALID` (409),
    `ERR_ORDER_LOGISTICS_STATE_INVALID` (409), `ERR_APPOINTMENT_STATE_INVALID`
    (409), `ERR_CLAIM_STATE_INVALID` (409) or
    `ERR_BUYER_QUALIFICATION_STATE_INVALID` (409), according to the entity in
    question."
    PRD 3.4: "Bidding is open only to a `Buyer` whose `qualification_status` is
    `QUALIFIED`, and only on a listing whose `listing_status` is `OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/closed_listing_state_error_wins_over_bid_below_minimum
    """
    env = bootstrap_marketplace()
    built = setup_open_auction(env, clock=INSIDE_WINDOW_CLOCK)
    listing = built["listing"]
    validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(env["buyer"]["id"], 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )
    before_close = read_listing(env, listing["id"])
    assert before_close["min_next_bid_cents"] == 1_100_000
    assert before_close["reserve_met"] is False

    set_clock(AUCTION_WINDOW_END)
    closed = validate_success(
        api_client.close_listing(listing["id"], {}, env["closer_headers"])
    )
    assert closed["listing_status"] == "CLOSED_NO_SALE"
    assert closed["reserve_met"] is False

    refused = api_client.place_bid(
        listing["id"], bid_payload(env["buyer"]["id"], 1), env["buyer_headers"]
    )
    error_id = validate_error(refused, "ERR_LISTING_STATE_INVALID", 409)["error_id"]
    assert error_id != "ERR_BID_BELOW_MINIMUM"


def test_the_refused_bid_leaves_the_no_sale_outcome_exactly_as_the_closure_left_it():
    """After the rejected one-cent bid the listing still shows one lost bid, the lot
    is waiting to be relisted and no sale order was ever created.

    PRD 3.5: "If the qualifying-bid pool is empty, or if `reserve_met` is false,
    the outcome is no sale: the listing advances `OPEN → CLOSED_NO_SALE`, every bid
    whose `bid_status` was `STANDING` or `WINNING` becomes `LOST`, no order is
    created, and the lot advances `LISTED → RELIST_PENDING` so it may be offered
    again."
    PRD 3.4: "The listing's `bid_count` counts this listing's bids whose
    `bid_status` is `STANDING`, `WINNING`, `WON` or `LOST`."

    Design: Difficulty/priority_pair_validation_conflict/closed_listing_state_error_wins_over_bid_below_minimum
    """
    env = bootstrap_marketplace()
    built = setup_open_auction(env, clock=INSIDE_WINDOW_CLOCK)
    listing = built["listing"]
    bid = validate_success(
        api_client.place_bid(
            listing["id"],
            bid_payload(env["buyer"]["id"], 1_000_000),
            env["buyer_headers"],
        ),
        201,
    )

    set_clock(AUCTION_WINDOW_END)
    validate_success(api_client.close_listing(listing["id"], {}, env["closer_headers"]))

    refused = api_client.place_bid(
        listing["id"], bid_payload(env["buyer"]["id"], 1), env["buyer_headers"]
    )
    validate_error(refused, "ERR_LISTING_STATE_INVALID", 409)

    reread = read_listing(env, listing["id"])
    assert reread["listing_status"] == "CLOSED_NO_SALE"
    assert reread["bid_count"] == 1
    assert read_bid(env, bid["id"])["bid_status"] == "LOST"
    assert read_lot(env, built["lot"]["id"])["lot_status"] == "RELIST_PENDING"
    assert total_count(
        api_client.list_sale_orders(ADMIN, {"listing_id": listing["id"]})
    ) == 0
