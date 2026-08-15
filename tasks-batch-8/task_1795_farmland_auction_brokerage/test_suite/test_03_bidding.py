"""Bidding: increments, scope shape, qualification, pipeline order, OCC (PRD §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_bid,
    assert_money,
    get_success_data,
    make_agent_headers,
    make_buyer_headers,
    place_bid_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def _open_online(**kwargs):
    """Default OPEN ONLINE auction on a WHOLE 100ac listing (min 700000)."""
    return fx.setup_open_auction(method="ONLINE", **kwargs)


# ────────────────────────── increment boundaries ─────────────────────

def test_bid_below_increment_boundary_rejected(api):
    """PRD §3.6: "When a current high exists, the new amount must be at least
    the current high plus a tiered increment determined by that high: $1,000
    when the high is below $100,000; $2,500 when it is at least $100,000 and
    below $500,000; $5,000 when it is at least $500,000 and below $1,000,000;
    and $10,000 when it is $1,000,000 or more. The exact boundary is accepted —
    an amount precisely equal to the high plus its increment stands — and
    anything less is rejected with `ERR_BID_BELOW_INCREMENT`."

    Design: Difficulty/boundary_precision_check/bid_increment_exact_boundary_accepted
    """
    env = _open_online()
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]]))
    # High 700000 sits in the 5000 tier; one cent under 705000 is rejected.
    res = fx.place_bid_fresh(b2, env["auction"]["id"], 704999.99, [env["tracts"][0]["id"]])
    validate_error(res, ApiErrorId.ERR_BID_BELOW_INCREMENT)


def test_bid_at_exact_increment_boundary_accepted_and_outbids(api):
    """PRD §3.6: "The exact boundary is accepted — an amount precisely equal to
    the high plus its increment stands — and anything less is rejected with
    `ERR_BID_BELOW_INCREMENT`."
    PRD §3.6: "On `LIVE` and `ONLINE` auctions, when a later bid with an
    identical single-tract scope and a higher amount is accepted, the previous
    `PLACED` high bid for that scope moves to `OUTBID`."

    Design: Difficulty/boundary_precision_check/bid_increment_exact_boundary_accepted
    """
    env = _open_online()
    agent_headers = make_agent_headers(env["agent"]["id"])
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    bid1 = get_success_data(
        fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]])
    )
    bid2 = get_success_data(
        fx.place_bid_fresh(b2, env["auction"]["id"], 705000, [env["tracts"][0]["id"]])
    )
    assert_bid(bid2)
    assert bid2["status"] == "PLACED", "exactly high + increment must stand"
    bid1_after = validate_success(api.get_bid(bid1["id"], agent_headers), 200)
    assert bid1_after["status"] == "OUTBID"


def test_increment_tier_crossing_500k(api):
    """PRD §3.6: "the new amount must be at least the current high plus a tiered
    increment determined by that high: $1,000 when the high is below $100,000;
    $2,500 when it is at least $100,000 and below $500,000; $5,000 when it is at
    least $500,000 and below $1,000,000; and $10,000 when it is $1,000,000 or
    more. The exact boundary is accepted — an amount precisely equal to the high
    plus its increment stands — and anything less is rejected with
    `ERR_BID_BELOW_INCREMENT`."

    Design: Corner/calculations/increment_tier_boundary_crossing_500k
    """
    env = _open_online(tract_specs=[{
        "tract_number": 1, "gross_acres": 100, "tillable_acres": 90,
        "soil_productivity_index": 80, "min_price": 400000,
    }])
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    t = [env["tracts"][0]["id"]]
    get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 499999.99, t))
    # High 499999.99 is in the 2500 tier: 499999.99 + 2500 is accepted exactly.
    bid2 = get_success_data(fx.place_bid_fresh(b2, env["auction"]["id"], 502499.99, t))
    assert bid2["status"] == "PLACED"
    # New high 502499.99 is at least 500000, so the 5000 tier applies.
    res = fx.place_bid_fresh(b1, env["auction"]["id"], 507499.98, t)
    validate_error(res, ApiErrorId.ERR_BID_BELOW_INCREMENT)


# ────────────────────────── combination bids ─────────────────────────

def test_combination_bid_premium_and_winner_selection(api):
    """PRD §3.6: "Combination bids on `COMBINATION` listings face a premium
    rule: the amount must be at least the greater of two figures — the sum of
    the current per-tract highs across the scope, taken only from bids whose
    scope is exactly that single tract (a tract with no such bid contributes
    zero), increased by five percent and rounded half-up to 2 decimal places;
    and the sum of the scope's `min_price` values. A combination bid under that
    bar is rejected with `ERR_BID_BELOW_MINIMUM`."
    PRD §3.7: "A successful award moves winning bids to `CONFIRMED_WINNER` and
    every other `PLACED` or `REVEALED` bid to `LOST`; tracts inside winning
    scopes move from `OFFERED` to `SOLD`, while `OFFERED` tracts outside every
    winning scope move to `UNSOLD`."

    Design: Corner/calculations/combination_bid_premium_selection_and_below_minimum_combo
    """
    env = fx.setup_open_auction(
        method="ONLINE",
        total_gross_acres=160,
        packaging_strategy="COMBINATION",
        reserve_price_total=1200000,
        tract_specs=[dict(s) for s in fx.COMBINATION_TRACT_SPECS],
        comparables="triple",
    )
    agent_headers = make_agent_headers(env["agent"]["id"])
    t1, t2 = env["tracts"][0]["id"], env["tracts"][1]["id"]
    b1 = fx.create_qualified_buyer()
    b3 = fx.create_qualified_buyer(full_name="Buyer Three", email="b3@x.com")

    bid1 = get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [t1]))
    # Premium bar: max(1.05 x 700000, 700000 + 350000) = 1050000; 739999 is under.
    low = fx.place_bid_fresh(b3, env["auction"]["id"], 739999, [t1, t2])
    validate_error(low, ApiErrorId.ERR_BID_BELOW_MINIMUM)
    bid3 = get_success_data(fx.place_bid_fresh(b3, env["auction"]["id"], 1400000, [t1, t2]))

    auction = fx.award_auction_at(env["agent"], env["auction"]["id"], fx.AUCTION_END)
    assert auction["status"] == "AWARDED"
    assert_money(auction["awarded_total"], 1400000, "awarded_total")
    bid1_after = validate_success(api.get_bid(bid1["id"], agent_headers), 200)
    bid3_after = validate_success(api.get_bid(bid3["id"], agent_headers), 200)
    assert bid1_after["status"] == "LOST"
    assert bid3_after["status"] == "CONFIRMED_WINNER"


# ────────────────────────── sealed-bid rules ─────────────────────────

def test_sealed_bid_below_minimum_and_second_bid_rejected(api):
    """PRD §3.6: "No increment check applies; the amount need only meet the sum
    of `min_price` across the scope, failing which the rejection is
    `ERR_BID_BELOW_MINIMUM`. Each buyer may place at most one bid per sealed
    auction — a second is `ERR_DUPLICATE_RECORD`."

    Design: Corner/cross_cutting/sealed_one_bid_per_buyer_and_below_minimum
    """
    env = fx.setup_open_auction(
        method="SEALED_BID",
        scheduled_start="2026-08-11T10:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z",
        open_at="2026-08-11T10:00:00Z",
    )
    b1 = fx.create_qualified_buyer()
    t = [env["tracts"][0]["id"]]
    low = fx.place_bid_fresh(b1, env["auction"]["id"], 699999, t)
    validate_error(low, ApiErrorId.ERR_BID_BELOW_MINIMUM)
    bid = get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, t))
    assert bid["status"] == "SEALED", "sealed-auction bids begin SEALED"
    dup = fx.place_bid_fresh(b1, env["auction"]["id"], 710000, t)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_RECORD)


# ────────────────────────── scope shape ──────────────────────────────

def test_bid_scope_shape_depends_on_packaging_strategy(api):
    """PRD §3.6: "It must be non-empty, every referenced tract must belong to
    the auction's listing, and every referenced tract must currently be
    `OFFERED`; beyond that, the listing's strategy shapes the scope — a `WHOLE`
    listing accepts only a scope covering all of its tracts, a `SPLIT` listing
    requires exactly one tract per bid, and a `COMBINATION` listing permits any
    subset, where a single-element scope is an individual tract bid and a longer
    scope is a combination bid. Every scope violation is
    `ERR_TRACT_SCOPE_INVALID`."

    Design: Corner/validations/bid_scope_shape_depends_on_packaging_strategy
    """
    env = fx.setup_open_auction(
        method="ONLINE",
        packaging_strategy="SPLIT",
        tract_specs=[
            {"tract_number": 1, "gross_acres": 60, "tillable_acres": 60,
             "soil_productivity_index": 80, "min_price": 300000},
            {"tract_number": 2, "gross_acres": 40, "tillable_acres": 40,
             "soil_productivity_index": 80, "min_price": 100000},
        ],
    )
    # A second listing's tract, foreign to this auction's listing.
    foreign = fx.create_draft_listing(
        env["agent"], env["seller"], title="LW", total_gross_acres=40,
        reserve_price_total=300000,
    )
    tw = fx.add_tract(env["agent"], foreign["id"], gross_acres=40, tillable_acres=40,
                      min_price=100000)
    b1 = fx.create_qualified_buyer()
    ts1, ts2 = env["tracts"][0]["id"], env["tracts"][1]["id"]

    two_tract = fx.place_bid_fresh(b1, env["auction"]["id"], 450000, [ts1, ts2])
    validate_error(two_tract, ApiErrorId.ERR_TRACT_SCOPE_INVALID)  # SPLIT: one tract only

    foreign_tract = fx.place_bid_fresh(b1, env["auction"]["id"], 350000, [tw["id"]])
    validate_error(foreign_tract, ApiErrorId.ERR_TRACT_SCOPE_INVALID)  # not in listing

    ok = get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 300000, [ts1]))
    assert ok["status"] == "PLACED", "single in-listing tract at exactly min_price"


# ────────────────────────── pipeline order ───────────────────────────

def test_bid_with_unknown_tract_returns_not_found(api):
    """PRD §2.8: "The server evaluates every request against a fixed validation
    pipeline, and the ordering is observable: a request that would fail two
    checks surfaces the earlier one."
    PRD §2.8: "**Existence** — path identifiers are resolved left to right, then
    body reference identifiers (`seller_id`, `listing_id`, `tract_id`,
    `auction_id`, `closing_id`, and each element of `tract_ids`) are resolved;
    the first missing identifier yields `ERR_NOT_FOUND`."

    Design: Corner/validations/existence_beats_state_and_fiscal_on_bid
    """
    env = _open_online()
    b1 = fx.create_qualified_buyer()
    # Amount 1 would fail every fiscal check; the unknown tract id wins first.
    res = fx.place_bid_fresh(b1, env["auction"]["id"], 1, [NON_EXISTENT_UUID])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_bid_on_closed_auction_state_beats_fiscal_and_qualification(api):
    """PRD §3.6: "Placement checks fire in a fixed order, so a request failing
    several of them surfaces the earliest: the auction must be `OPEN` or
    `EXTENDED`, else `ERR_AUCTION_NOT_OPEN`; the version check rejects stale
    views with `ERR_STALE_AUCTION_VERSION`; the bidder's `qualification_status`
    must be `QUALIFIED` with the logical clock strictly before
    `qualification_expires_at`, else `ERR_BUYER_NOT_QUALIFIED`; then scope, then
    sealed-bid uniqueness, then price economics, and finally proof of funds."

    Design: Difficulty/priority_pair_validation_conflict/bid_closed_auction_low_amount_state_beats_fiscal
    """
    env = _open_online()
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_buyer(full_name="Buyer Two", email="b2@x.com")  # stays UNVERIFIED
    get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]]))
    fx.set_clock(fx.AUCTION_END)  # close sweep: one bid standing -> CLOSED_PENDING_AWARD
    agent_headers = make_agent_headers(env["agent"]["id"])
    auction = fx.read_auction(env["auction"]["id"], agent_headers)
    assert auction["status"] == "CLOSED_PENDING_AWARD"
    res = fx.place_bid_fresh(b2, env["auction"]["id"], 100, [env["tracts"][0]["id"]])
    # Unqualified buyer AND below-minimum amount: the state gate fires first.
    validate_error(res, ApiErrorId.ERR_AUCTION_NOT_OPEN)


def test_bid_on_closed_auction_state_beats_fiscal_for_qualified_buyer(api):
    """PRD §3.6: "Placement checks fire in a fixed order, so a request failing
    several of them surfaces the earliest: the auction must be `OPEN` or
    `EXTENDED`, else `ERR_AUCTION_NOT_OPEN`; the version check rejects stale
    views with `ERR_STALE_AUCTION_VERSION`; the bidder's `qualification_status`
    must be `QUALIFIED` with the logical clock strictly before
    `qualification_expires_at`, else `ERR_BUYER_NOT_QUALIFIED`; then scope, then
    sealed-bid uniqueness, then price economics, and finally proof of funds."

    Design: Difficulty/priority_pair_validation_conflict/bid_closed_auction_low_amount_state_beats_fiscal
    """
    env = _open_online()
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    get_success_data(fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]]))
    fx.set_clock(fx.AUCTION_END)
    res = fx.place_bid_fresh(b2, env["auction"]["id"], 100, [env["tracts"][0]["id"]])
    # Qualified but far below any increment: still the state gate, not fiscal.
    validate_error(res, ApiErrorId.ERR_AUCTION_NOT_OPEN)


# ────────────────────────── buyer qualification gate ─────────────────

def test_bid_rejected_while_buyer_unverified(api):
    """PRD §3.6: "the bidder's `qualification_status` must be `QUALIFIED` with
    the logical clock strictly before `qualification_expires_at`, else
    `ERR_BUYER_NOT_QUALIFIED`"
    PRD §3.1: "A new buyer's `qualification_status` starts at `UNVERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/bid_gate_depends_on_buyer_qualification
    """
    env = _open_online()
    b1 = fx.create_buyer()  # UNVERIFIED
    res = fx.place_bid_fresh(b1, env["auction"]["id"], 700000, [env["tracts"][0]["id"]])
    validate_error(res, ApiErrorId.ERR_BUYER_NOT_QUALIFIED)


def test_bid_accepted_after_qualification_same_version(api):
    """PRD §3.6: "the bidder's `qualification_status` must be `QUALIFIED` with
    the logical clock strictly before `qualification_expires_at`, else
    `ERR_BUYER_NOT_QUALIFIED`"
    PRD §3.6: "And every accepted bid increments the auction's `version`, which
    is what makes the optimistic concurrency check meaningful."

    Design: Difficulty/cross_entity_state_dependency/bid_gate_depends_on_buyer_qualification
    """
    env = _open_online()
    b1 = fx.create_buyer()
    buyer_headers = make_buyer_headers(b1["id"])
    version = fx.auction_version(env["auction"]["id"], buyer_headers)
    payload = place_bid_payload(env["auction"]["id"], 700000, [env["tracts"][0]["id"]], version)
    validate_error(api.place_bid(payload, buyer_headers), ApiErrorId.ERR_BUYER_NOT_QUALIFIED)
    fx.qualify_buyer(b1["id"])
    # The rejected bid did not advance the auction version: the retry with the
    # same expected version is accepted.
    bid = get_success_data(api.place_bid(payload, buyer_headers))
    assert bid["status"] == "PLACED"


# ────────────────────────── OCC on auction version ───────────────────

def test_stale_auction_version_bid_rejected(api):
    """PRD §2.7: "Placing a bid requires the request to carry
    `expected_auction_version` holding the auction's `version` as the bidder
    last observed it. Every accepted bid increments `AuctionEvent.version`, so
    a bidder holding version N who submits `expected_auction_version` N after
    another accepted bid has moved the auction to N+1 is acting on a stale view
    of the current high bid; the request is rejected with
    `ERR_STALE_AUCTION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_auction_version_rejected
    """
    env = _open_online()
    b1 = fx.create_qualified_buyer()
    b2 = fx.create_qualified_buyer(full_name="Buyer Two", email="b2@x.com")
    buyer_headers = make_buyer_headers(b1["id"])
    stale_version = fx.auction_version(env["auction"]["id"], buyer_headers)
    t = [env["tracts"][0]["id"]]
    bid1 = get_success_data(
        api.place_bid(
            place_bid_payload(env["auction"]["id"], 700000, t, stale_version),
            buyer_headers,
        )
    )
    assert bid1["status"] == "PLACED"
    res = api.place_bid(
        place_bid_payload(env["auction"]["id"], 800000, t, stale_version),
        make_buyer_headers(b2["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_AUCTION_VERSION)
