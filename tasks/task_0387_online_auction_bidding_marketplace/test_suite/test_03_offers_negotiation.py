"""Best-offer negotiation: counter loop, acceptance cascade, expiry, validations, OCC.

Each test translates exactly one design-index instance. The offer_cyclic_counter_loop
difficulty instance receives at least two tests.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_seller_headers, make_buyer_headers,
    register_seller, register_buyer,
    set_clock, advance_clock,
    setup_offer_listing, submit_offer, counter_offer,
    create_and_publish_listing,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ════════════════════════════════════════════════════════════════════
# Difficulty: offer_cyclic_counter_loop (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_offer_counter_loop_round3_buyer_recounter(api):
    """PRD §3.5: "Each counter sets the offer's amount_cents to the new counter amount —
    which on a seller counter becomes the seller's asking amount — flips the last_actor to
    the party who just acted, increments round_no by one, and increments the offer's version
    by one."

    Design: Difficulty/non_linear_state_machine/offer_cyclic_counter_loop
    """
    seller, buyer, listing = setup_offer_listing(buy_now_price_cents=50000)
    offer = submit_offer(listing["id"], buyer["id"], 20000)   # round 1, BUYER
    offer = counter_offer(offer["id"], seller["id"], "SELLER", 40000, offer["version"])  # r2 SELLER
    offer = counter_offer(offer["id"], buyer["id"], "BUYER", 30000, offer["version"])    # r3 BUYER

    assert offer["status"] == "COUNTERED"
    assert offer["round_no"] == 3
    assert offer["last_actor"] == "BUYER"
    assert offer["amount_cents"] == 30000


def test_offer_first_counter_pending_to_countered(api):
    """PRD §3.5: "Either party may counter, which moves a PENDING offer to COUNTERED or
    keeps an already COUNTERED offer in COUNTERED. A seller may counter only when the
    last_actor is BUYER; a buyer may counter only when the last_actor is SELLER."

    Design: Difficulty/non_linear_state_machine/offer_cyclic_counter_loop
    """
    seller, buyer, listing = setup_offer_listing(buy_now_price_cents=50000)
    offer = submit_offer(listing["id"], buyer["id"], 20000)
    assert offer["status"] == "PENDING"
    assert offer["round_no"] == 1
    assert offer["last_actor"] == "BUYER"

    countered = counter_offer(offer["id"], seller["id"], "SELLER", 40000, offer["version"])
    assert countered["status"] == "COUNTERED"
    assert countered["round_no"] == 2
    assert countered["last_actor"] == "SELLER"
    assert countered["amount_cents"] == 40000


# ════════════════════════════════════════════════════════════════════
# Corner: offer_accept_declines_competing_offers_conditional_cascade
# ════════════════════════════════════════════════════════════════════

def test_offer_accept_declines_competing_offers(api):
    """PRD §3.6: "the accepted offer moves to ACCEPTED, an Order with source of OFFER_ACCEPT
    is created and cascades a seller fee invoice, and every other PENDING or COUNTERED offer
    on the same listing is moved to DECLINED."

    Design: Corner/state_machines/offer_accept_declines_competing_offers_conditional_cascade
    """
    seller, _, listing = setup_offer_listing(buy_now_price_cents=50000)
    b1 = register_buyer()
    b2 = register_buyer()
    off1 = submit_offer(listing["id"], b1["id"], 20000)
    off2 = submit_offer(listing["id"], b2["id"], 22000)

    validate_success(api.accept_offer(off1["id"], {"shipping_cents": 0},
                                      make_seller_headers(seller["id"])), 200)

    o1 = validate_success(api.get_offer(off1["id"], make_seller_headers(seller["id"])), 200)
    o2 = validate_success(api.get_offer(off2["id"], make_seller_headers(seller["id"])), 200)
    assert o1["status"] == "ACCEPTED"
    assert o2["status"] == "DECLINED"

    lst = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert lst["status"] == "SOLD"
    assert lst["sold_price_cents"] == 20000


# ════════════════════════════════════════════════════════════════════
# Corner: offer_expires_on_clock_advance
# ════════════════════════════════════════════════════════════════════

def test_offer_expires_on_clock_advance(api):
    """PRD §3.5: "a PENDING offer expires once the current clock reaches its created_at plus
    the offer time-to-live of 24 hours (86400 seconds)"

    Design: Corner/state_machines/offer_expires_on_clock_advance
    """
    seller, buyer, listing = setup_offer_listing(buy_now_price_cents=50000,
                                                 clock="2026-06-01T00:00:00Z")
    offer = submit_offer(listing["id"], buyer["id"], 20000)
    advance_clock("2026-06-02T01:00:00Z")   # 25h later, past 24h TTL

    after = validate_success(api.get_offer(offer["id"], make_buyer_headers(buyer["id"])), 200)
    assert after["status"] == "EXPIRED"


# ════════════════════════════════════════════════════════════════════
# Corner: offer_amount_at_or_above_buy_now_rejected
# ════════════════════════════════════════════════════════════════════

def test_offer_amount_at_buy_now_rejected(api):
    """PRD §3.5: "The offer amount must be at least 1 cent and strictly less than the
    listing's buy_now_price_cents, and the listing must in fact accept offers; an amount out
    of range, a listing that does not accept offers, or a counter against a listing that does
    not support offers is refused with ERR_OFFER_INVALID."

    Design: Corner/validations/offer_amount_at_or_above_buy_now_rejected
    """
    seller, buyer, listing = setup_offer_listing(buy_now_price_cents=50000)
    res = api.create_offer(listing["id"],
                           {"buyer_account_id": buyer["id"], "amount_cents": 50000},
                           make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_OFFER_INVALID", expected_status=422)


# ════════════════════════════════════════════════════════════════════
# Corner: offer_on_non_offer_listing_rejected
# ════════════════════════════════════════════════════════════════════

def test_offer_on_non_offer_listing_rejected(api):
    """PRD §3.5: "The offer amount must be at least 1 cent and strictly less than the
    listing's buy_now_price_cents, and the listing must in fact accept offers; an amount out
    of range, a listing that does not accept offers, or a counter against a listing that does
    not support offers is refused with ERR_OFFER_INVALID."

    Design: Corner/validations/offer_on_non_offer_listing_rejected
    """
    seller = register_seller()
    buyer = register_buyer()
    set_clock("2026-06-01T00:00:00Z")
    # accepts_offers defaults to false.
    listing = create_and_publish_listing(seller["id"], format="BUY_NOW",
                                         buy_now_price_cents=50000)
    res = api.create_offer(listing["id"],
                           {"buyer_account_id": buyer["id"], "amount_cents": 10000},
                           make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_OFFER_INVALID", expected_status=422)


# ════════════════════════════════════════════════════════════════════
# Corner: offer_round_limit_exceeded
# ════════════════════════════════════════════════════════════════════

def test_offer_round_limit_exceeded(api):
    """PRD §3.5: "The loop is bounded: once round_no reaches the cap of 5 rounds, a further
    counter is refused with ERR_OFFER_ROUND_LIMIT (a counter is rejected when round_no is 5
    or more)."

    Design: Corner/validations/offer_round_limit_exceeded
    """
    seller, buyer, listing = setup_offer_listing(buy_now_price_cents=50000)
    offer = submit_offer(listing["id"], buyer["id"], 10000)                       # r1 BUYER
    offer = counter_offer(offer["id"], seller["id"], "SELLER", 40000, offer["version"])  # r2
    offer = counter_offer(offer["id"], buyer["id"], "BUYER", 20000, offer["version"])    # r3
    offer = counter_offer(offer["id"], seller["id"], "SELLER", 35000, offer["version"])  # r4
    offer = counter_offer(offer["id"], buyer["id"], "BUYER", 25000, offer["version"])    # r5
    assert offer["round_no"] == 5

    # 5th counter -> round_no already 5 -> rejected.
    res = api.counter_offer(offer["id"],
                            {"amount_cents": 30000, "expected_offer_version": offer["version"]},
                            make_seller_headers(seller["id"]))
    validate_error(res, "ERR_OFFER_ROUND_LIMIT", expected_status=422)
    after = validate_success(api.get_offer(offer["id"], make_seller_headers(seller["id"])), 200)
    assert after["round_no"] == 5


# ════════════════════════════════════════════════════════════════════
# Corner: occ_offer_counter_stale_version
# ════════════════════════════════════════════════════════════════════

def test_offer_counter_stale_version_rejected(api):
    """PRD §2.9: "If a counterparty has already advanced the negotiation — legitimately
    moving the standing amount and bumping the offer's version — since the client last read
    the offer, the submitted expected_offer_version will no longer match the offer's current
    version, and the counter is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_offer_counter_stale_version
    """
    seller, buyer, listing = setup_offer_listing(buy_now_price_cents=50000)
    offer = submit_offer(listing["id"], buyer["id"], 10000)
    stale_version = offer["version"]
    # Seller counters first, advancing the offer version.
    counter_offer(offer["id"], seller["id"], "SELLER", 40000, stale_version)

    # Buyer counters with the now-stale version.
    res = api.counter_offer(offer["id"],
                            {"amount_cents": 20000, "expected_offer_version": stale_version},
                            make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
