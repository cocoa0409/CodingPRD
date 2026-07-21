"""Bid-ask matching boundaries, referential precedence, active-listing gating,
and reprice optimistic-concurrency."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_sku, create_account, create_listing, create_bid, buy_listing,
    make_seller_headers, make_buyer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _listing_and_matching_bid(api, ask, bid_amount, listing_sku=None, bid_sku=None,
                              listing_size="10", bid_size="10"):
    """Build a BID_ASK listing and a standing bid, plus their verified owners.
    listing_sku/bid_sku default to the same fresh SKU when not provided."""
    sku_l = listing_sku or create_sku(api)
    sku_b = bid_sku or sku_l
    seller = create_account(api, full_name="Match Seller")
    buyer = create_account(api, full_name="Match Buyer")
    listing = create_listing(api, sku_l["id"], seller["id"], ask_price_cents=ask,
                             size=listing_size, pricing_mode="BID_ASK")
    bid = create_bid(api, sku_b["id"], buyer["id"], size=bid_size, amount_cents=bid_amount)
    return seller, buyer, listing, bid


# --------------------------------------------------------------------------- #
# Bid exactly equal to ask matches (Difficulty boundary)
# --------------------------------------------------------------------------- #
def test_match_bid_equal_to_ask_creates_bid_match_order(api):
    """PRD §3.5: "the bid's `amount_cents` must be at least the listing's
    `ask_price_cents`, failing which the match is rejected with
    `ERR_BID_BELOW_ASK`. A successful match sets the bid's status from `OPEN` to
    `MATCHED`, moves the listing to `MATCHED` and increments its `version`, and
    creates an `Order` with `source_type` of `BID_MATCH`, both its `listing_id`
    and `bid_id` set, and a `sale_price_cents` equal to the bid's `amount_cents`."

    Design: Difficulty/boundary_precision_check/match_bid_equal_to_ask_succeeds_boundary
    """
    seller, buyer, listing, bid = _listing_and_matching_bid(api, ask=20000, bid_amount=20000)
    resp = api.match_listing(listing["id"], {"bid_id": bid["id"],
                                             "expected_listing_version": listing["version"]},
                             make_seller_headers(seller["id"]))
    order = validate_success(resp, expected_status=201)
    assert order["source_type"] == "BID_MATCH"
    assert order["sale_price_cents"] == 20000


def test_match_bid_equal_to_ask_transitions_listing_and_bid(api):
    """PRD §3.5: "A successful match sets the bid's status from `OPEN` to
    `MATCHED`, moves the listing to `MATCHED` and increments its `version`".

    Design: Difficulty/boundary_precision_check/match_bid_equal_to_ask_succeeds_boundary
    """
    seller, buyer, listing, bid = _listing_and_matching_bid(api, ask=20000, bid_amount=20000)
    get_success_data(api.match_listing(listing["id"],
                                       {"bid_id": bid["id"],
                                        "expected_listing_version": listing["version"]},
                                       make_seller_headers(seller["id"])))
    assert get_success_data(api.get_listing(listing["id"], make_seller_headers(seller["id"])))["status"] == "MATCHED"
    assert get_success_data(api.get_bid(bid["id"], make_buyer_headers(buyer["id"])))["status"] == "MATCHED"


# --------------------------------------------------------------------------- #
# Referential (SKU mismatch) outranks fiscal (below ask) (Difficulty)
# --------------------------------------------------------------------------- #
def _mismatched_below_ask(api):
    sku_a = create_sku(api)
    sku_b = create_sku(api)
    # different sku AND below ask (10000 < 30000)
    return _listing_and_matching_bid(api, ask=30000, bid_amount=10000,
                                     listing_sku=sku_a, bid_sku=sku_b)


def test_match_sku_mismatch_reported_over_below_ask(api):
    """PRD §2.8: "then temporal-window checks, referential checks, quota
    constraints, and finally fiscal checks. In every case the earliest failing
    check in this ladder is the one reported."
    PRD §3.5: "The bid must reference the same SKU and size as the listing — a
    `bid_id` whose bid has a different `sku_id` or `size` than the listing is
    rejected with `ERR_SKU_MISMATCH`".

    Design: Difficulty/priority_pair_validation_conflict/match_referential_sku_mismatch_beats_fiscal_bid_below_ask
    """
    seller, buyer, listing, bid = _mismatched_below_ask(api)
    resp = api.match_listing(listing["id"], {"bid_id": bid["id"],
                                             "expected_listing_version": listing["version"]},
                             make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_SKU_MISMATCH.value)


def test_match_sku_mismatch_leaves_listing_and_bid_unchanged(api):
    """PRD §3.5: "A successful match sets the bid's status from `OPEN` to
    `MATCHED`, moves the listing to `MATCHED` and increments its `version`".
    (A rejected match performs none of these transitions, so both remain in
    their pre-match states.)

    Design: Difficulty/priority_pair_validation_conflict/match_referential_sku_mismatch_beats_fiscal_bid_below_ask
    """
    seller, buyer, listing, bid = _mismatched_below_ask(api)
    api.match_listing(listing["id"], {"bid_id": bid["id"],
                                      "expected_listing_version": listing["version"]},
                      make_seller_headers(seller["id"]))
    assert get_success_data(api.get_listing(listing["id"], make_seller_headers(seller["id"])))["status"] == "ACTIVE"
    assert get_success_data(api.get_bid(bid["id"], make_buyer_headers(buyer["id"])))["status"] == "OPEN"


# --------------------------------------------------------------------------- #
# Matching gated on the listing still being ACTIVE (Difficulty)
# --------------------------------------------------------------------------- #
def _already_matched_listing_and_open_bid(api):
    sku = create_sku(api)
    seller = create_account(api, full_name="Gate Seller")
    buyer1 = create_account(api, full_name="Gate Buyer 1")
    buyer2 = create_account(api, full_name="Gate Buyer 2")
    listing = create_listing(api, sku["id"], seller["id"], ask_price_cents=15000,
                             size="11", pricing_mode="BID_ASK")
    buy_listing(api, listing["id"], buyer1["id"])  # listing -> MATCHED
    bid = create_bid(api, sku["id"], buyer2["id"], size="11", amount_cents=15000)
    current = get_success_data(api.get_listing(listing["id"], make_seller_headers(seller["id"])))
    return seller, buyer2, listing, bid, current["version"]


def test_match_on_already_matched_listing_rejected(api):
    """PRD §3.5: "Repricing, buying, or matching a listing that is not `ACTIVE`
    is rejected with `ERR_LISTING_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/match_gated_on_listing_active
    """
    seller, buyer2, listing, bid, version = _already_matched_listing_and_open_bid(api)
    resp = api.match_listing(listing["id"], {"bid_id": bid["id"],
                                             "expected_listing_version": version},
                             make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_ACTIVE.value)


def test_match_on_already_matched_listing_leaves_bid_open(api):
    """PRD §3.5: "A successful match sets the bid's status from `OPEN` to
    `MATCHED`". (When the match is rejected because the listing is not `ACTIVE`,
    the bid never transitions and stays `OPEN`.)

    Design: Difficulty/cross_entity_state_dependency/match_gated_on_listing_active
    """
    seller, buyer2, listing, bid, version = _already_matched_listing_and_open_bid(api)
    api.match_listing(listing["id"], {"bid_id": bid["id"],
                                      "expected_listing_version": version},
                      make_seller_headers(seller["id"]))
    assert get_success_data(api.get_bid(bid["id"], make_buyer_headers(buyer2["id"])))["status"] == "OPEN"


# --------------------------------------------------------------------------- #
# Reprice optimistic concurrency (Corner)
# --------------------------------------------------------------------------- #
def test_reprice_with_stale_version_rejected(api):
    """PRD §2.6: "If `expected_listing_version` does not equal the listing's
    current `version`, the reprice is rejected with `ERR_STALE_VERSION` and HTTP
    status 412, because the listing has been superseded since the seller last
    observed it."

    Design: Corner/cross_cutting/reprice_with_stale_version_returns_conflict
    """
    sku = create_sku(api)
    seller = create_account(api, full_name="OCC Seller")
    listing = create_listing(api, sku["id"], seller["id"], ask_price_cents=30000)
    stale_version = listing["version"]
    # First reprice succeeds and advances the version.
    get_success_data(api.reprice_listing(listing["id"],
                                         {"new_ask_price_cents": 28000,
                                          "expected_listing_version": stale_version},
                                         make_seller_headers(seller["id"])))
    # Second reprice still carries the now-stale version.
    resp = api.reprice_listing(listing["id"],
                               {"new_ask_price_cents": 27000,
                                "expected_listing_version": stale_version},
                               make_seller_headers(seller["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
