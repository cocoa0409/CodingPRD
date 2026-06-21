"""Listing creation, lifecycle, access control, and pagination.

Each test translates exactly one design-index instance (queue A difficulty or
queue B corner). Docstrings cite verbatim PRD prose and end with the Design tag.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    assert_account, assert_listing,
    create_account_payload, create_listing_payload,
    TEST_USERS, make_seller_headers, make_buyer_headers,
    register_seller, register_buyer, register_seller_buyer,
    set_clock, create_draft_listing, create_and_publish_listing,
    place_bid, setup_published_auction, setup_published_buy_now,
    setup_suspended_seller, buy_now_order,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ── Account creation ────────────────────────────────────────────────

def test_create_account_returns_defaults(api):
    """PRD §3.1: "A freshly registered account starts ACTIVE with a fee_balance_cents
    of zero, a feedback_score of zero, and standing of GOOD."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    res = api.create_account(
        create_account_payload(roles=["SELLER", "BUYER"], email="defaults@x.com"), ANON)
    acct = validate_success(res, 201)
    assert_account(acct)
    assert acct["fee_balance_cents"] == 0
    assert acct["feedback_score"] == 0
    assert acct["standing"] == "GOOD"
    assert acct["status"] == "ACTIVE"
    assert acct["version"] == 1


def test_create_account_missing_roles_rejected(api):
    """PRD §3.1: "The roles list must be non-empty and may contain SELLER, BUYER, or both."
    PRD §2.10: "Generic field-shape validation — required fields present, enums in range,
    integers meeting their stated constraints — comes last (ERR_INVALID_REQUEST)."

    Design: Corner/entities/create_account_missing_roles_returns_invalid_request
    """
    payload = {"email": "noroles@x.com", "display_name": "NoRoles"}
    res = api.create_account(payload, ANON)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ── Listing reads / creation ────────────────────────────────────────

def test_get_nonexistent_listing_not_found(api):
    """PRD §2.6: "the server validates them left to right and rejects the first identifier
    that does not correspond to an existing resource with ERR_NOT_FOUND."

    Design: Corner/entities/get_listing_nonexistent_returns_not_found
    """
    res = api.get_listing(NON_EXISTENT_UUID, ANON)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_listing_created_in_draft_with_computed_fields_uninitialized(api):
    """PRD §3.2: "A Seller creates a listing in DRAFT status by supplying the
    seller_account_id (which must be their own account and must hold the SELLER role),
    a title, and a format."
    PRD §3.2: "A listing also tracks a computed highest_bid_id pointer to the current
    winning bid (null until the first bid), a computed bid_count of distinct accepted bids
    (starting at zero), a computed winner_account_id, and a computed sold_price_cents that
    remains null until the listing sells."

    Design: Corner/entities/listing_computed_fields_ignored_on_create
    """
    seller = register_seller()
    res = api.create_listing(
        create_listing_payload(seller["id"], format="AUCTION",
                               start_price_cents=10000,
                               scheduled_end_at="2026-07-01T00:00:00Z"),
        make_seller_headers(seller["id"]))
    listing = validate_success(res, 201)
    assert_listing(listing)
    assert listing["status"] == "DRAFT"
    assert listing["bid_count"] == 0
    assert listing["winner_account_id"] is None


def test_listing_default_accepts_offers_false(api):
    """PRD §3.2: "A seller may also set accepts_offers to true (it defaults to false) to
    allow best-offer negotiation, which is permitted only on BUY_NOW and HYBRID listings."

    Design: Corner/entities/listing_default_accepts_offers_false
    """
    seller = register_seller()
    res = api.create_listing(
        create_listing_payload(seller["id"], format="BUY_NOW", buy_now_price_cents=9000),
        make_seller_headers(seller["id"]))
    listing = validate_success(res, 201)
    assert listing["accepts_offers"] is False


# ── Listing state machine ───────────────────────────────────────────

def test_cancel_active_listing_with_bids_rejected(api):
    """PRD §3.2: "Cancelling an ACTIVE listing is permitted only while its bid_count is
    zero — an auction that has already attracted a bid cannot be cancelled"
    PRD §3.2: "A transition requested from a state in which it is not defined is refused
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_listing_with_bids_returns_invalid_state
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-07-01T00:00:00Z")
    buyer = register_buyer()
    place_bid(listing["id"], buyer["id"], 12000)

    res = api.cancel_listing(listing["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["status"] == "ACTIVE"


def test_cancelled_listing_second_cancel_rejected(api):
    """PRD §3.2: "Cancelling a DRAFT listing simply moves it to CANCELLED."
    PRD §3.2: "A transition requested from a state in which it is not defined is refused
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_listing_cancelled_lockdown
    """
    seller = register_seller()
    listing = create_draft_listing(seller["id"], format="BUY_NOW", buy_now_price_cents=9000)
    cancelled = validate_success(
        api.cancel_listing(listing["id"], make_seller_headers(seller["id"])), 200)
    assert cancelled["status"] == "CANCELLED"

    res = api.cancel_listing(listing["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["status"] == "CANCELLED"


def test_hybrid_buy_now_blocked_after_first_bid(api):
    """PRD §3.6: "For a HYBRID the buy-now option is available only while bid_count is
    zero — it disappears after the first bid."
    PRD §3.2: "A transition requested from a state in which it is not defined is refused
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/hybrid_buy_now_blocked_after_first_bid
    """
    seller = register_seller()
    bidder = register_buyer()
    buyer = register_buyer()
    set_clock("2026-06-01T00:00:00Z")
    listing = create_and_publish_listing(
        seller["id"], format="HYBRID", start_price_cents=10000,
        buy_now_price_cents=30000, scheduled_end_at="2026-06-10T00:00:00Z")
    place_bid(listing["id"], bidder["id"], 12000)

    res = api.buy_now(listing["id"], {"buyer_account_id": buyer["id"], "shipping_cents": 0},
                      make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["status"] == "ACTIVE"


# ── Cross-entity gate: seller standing controls publish ─────────────

def test_publish_blocked_when_seller_suspended(api):
    """PRD §3.2: "the seller's account standing must be GOOD — that is, its
    fee_balance_cents must be at most the suspension threshold of 3000 cents. A seller
    whose standing is SUSPENDED is blocked from publishing with ERR_SELLER_SUSPENDED."
    PRD §2.8: "the standing is GOOD when fee_balance_cents is less than or equal to the
    suspension threshold of 3000 cents, and SUSPENDED when fee_balance_cents is strictly
    greater than 3000 cents."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_seller_account_good_standing
    """
    # First sale of 30000 raises an INVOICED fee of 3630 (> 3000) -> seller SUSPENDED.
    seller, buyer, sold_listing, order, second = setup_suspended_seller(
        buy_now_price_cents=30000)
    acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert acct["standing"] == "SUSPENDED", f"expected SUSPENDED, got {acct['standing']}"

    res = api.publish_listing(second["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_SELLER_SUSPENDED", expected_status=422)
    after = validate_success(api.get_listing(second["id"], ANON), 200)
    assert after["status"] == "DRAFT"


def test_publish_allowed_when_seller_standing_good(api):
    """PRD §3.2: "Publishing moves a listing from DRAFT to ACTIVE. The acting seller must
    own the listing, the seller's account status must be ACTIVE, and the seller's account
    standing must be GOOD — that is, its fee_balance_cents must be at most the suspension
    threshold of 3000 cents."

    Design: Difficulty/cross_entity_state_dependency/publish_requires_seller_account_good_standing
    """
    # A fresh seller has fee_balance_cents == 0 (<= 3000) -> GOOD -> publish succeeds.
    seller = register_seller()
    acct = validate_success(api.get_account(seller["id"], ANON), 200)
    assert acct["standing"] == "GOOD"
    listing = create_draft_listing(seller["id"], format="BUY_NOW", buy_now_price_cents=5000)

    published = validate_success(
        api.publish_listing(listing["id"], make_seller_headers(seller["id"])), 200)
    assert published["status"] == "ACTIVE"


# ── Access control ──────────────────────────────────────────────────

def test_closed_account_cannot_create_listing(api):
    """PRD §3.1: "Once an account is CLOSED it may still be read but may no longer perform
    any mutating action, and any attempt to do so is refused with ERR_ACCOUNT_CLOSED."

    Design: Corner/errors/closed_account_mutation_rejected
    """
    seller = register_seller()
    validate_success(api.close_account(seller["id"], ADMIN), 200)

    res = api.create_listing(
        create_listing_payload(seller["id"], format="BUY_NOW", buy_now_price_cents=9000),
        make_seller_headers(seller["id"]))
    validate_error(res, "ERR_ACCOUNT_CLOSED", expected_status=403)


def test_buyer_cannot_publish_listing(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/roles/buyer_cannot_publish_listing
    """
    seller = register_seller()
    buyer = register_buyer()
    listing = create_draft_listing(seller["id"], format="BUY_NOW", buy_now_price_cents=9000)

    res = api.publish_listing(listing["id"], make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_non_owner_seller_cannot_publish(api):
    """PRD §2.1: "When the role is permitted in general but the acting account is not the
    owner of the specific targeted resource, the request is rejected with ERR_NOT_OWNER."

    Design: Corner/roles/non_owner_seller_cannot_publish_others_listing
    """
    s1 = register_seller()
    s2 = register_seller()
    listing = create_draft_listing(s1["id"], format="BUY_NOW", buy_now_price_cents=9000)

    res = api.publish_listing(listing["id"], make_seller_headers(s2["id"]))
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "When a protected endpoint receives a request whose X-User-Role or
    X-User-ID header is missing or malformed, the request is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/roles/missing_auth_headers_unauthenticated
    """
    seller = register_seller()
    res = api.create_listing(
        create_listing_payload(seller["id"], format="BUY_NOW", buy_now_price_cents=9000),
        headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ── Pagination ──────────────────────────────────────────────────────

def test_list_listings_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_listings_pagination_envelope
    """
    seller = register_seller()
    create_draft_listing(seller["id"], format="BUY_NOW", buy_now_price_cents=9000)
    create_draft_listing(seller["id"], format="BUY_NOW", buy_now_price_cents=9000)

    res = api.list_listings(ANON, params={"seller_account_id": seller["id"],
                                          "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
