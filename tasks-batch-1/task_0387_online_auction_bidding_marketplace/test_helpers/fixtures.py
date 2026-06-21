"""Composite setup helpers for multi-step test prerequisites.

Each helper builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the server (empty DB) before every test. Helpers
use get_success_data() (lenient) so a broken setup produces a clear "Setup step failed"
error rather than a confusing assertion failure.

Identity threading: the Buyer and Seller roles are entity-backed, so any ownership-gated
call uses make_seller_headers(seller_id) / make_buyer_headers(buyer_id) with the real
Account.id — never the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload, create_listing_payload, create_bid_payload,
    buy_now_payload, create_offer_payload, counter_offer_payload,
    pay_order_payload, create_dispute_payload, resolve_dispute_payload,
    clock_payload,
)
from .test_users import (
    TEST_USERS, make_seller_headers, make_buyer_headers, make_admin_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Default clock anchor used across temporal setups.
CLOCK_BASE = "2026-06-01T00:00:00Z"


# ─── Tier 0: primitives ──────────────────────────────────────────────

def register_account(roles, email=None, display_name="Acct"):
    """Register an Account with the given roles list. Returns the Account dict."""
    payload = create_account_payload(roles=roles, display_name=display_name)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_account(payload, ANON))


def register_seller(**kw):
    return register_account(["SELLER"], **kw)


def register_buyer(**kw):
    return register_account(["BUYER"], **kw)


def register_seller_buyer(**kw):
    return register_account(["SELLER", "BUYER"], **kw)


def set_clock(iso):
    return api_client.clock_set(clock_payload(iso), ADMIN)


def advance_clock(iso):
    return api_client.clock_advance(clock_payload(iso), ADMIN)


# ─── Tier 1: listing creation / publication ──────────────────────────

def create_draft_listing(seller_id, format="BUY_NOW", **overrides):
    """Create a DRAFT listing owned by seller_id. Returns the Listing dict."""
    payload = create_listing_payload(seller_id, format=format, **overrides)
    return get_success_data(
        api_client.create_listing(payload, make_seller_headers(seller_id))
    )


def create_and_publish_listing(seller_id, format="BUY_NOW", **overrides):
    """Create + publish a listing. Returns the published (ACTIVE) Listing dict."""
    listing = create_draft_listing(seller_id, format=format, **overrides)
    published = get_success_data(
        api_client.publish_listing(listing["id"], make_seller_headers(seller_id))
    )
    return published


def setup_published_buy_now(buy_now_price_cents=30000, accepts_offers=None,
                            clock=CLOCK_BASE):
    """Seller + Buyer registered, clock set, a published BUY_NOW listing.
    Returns (seller, buyer, listing)."""
    seller = register_seller()
    buyer = register_buyer()
    if clock is not None:
        set_clock(clock)
    overrides = {"buy_now_price_cents": buy_now_price_cents}
    if accepts_offers is not None:
        overrides["accepts_offers"] = accepts_offers
    listing = create_and_publish_listing(seller["id"], format="BUY_NOW", **overrides)
    return seller, buyer, listing


def setup_published_auction(start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z",
                            reserve_price_cents=None, clock=CLOCK_BASE, format="AUCTION"):
    """Seller registered, clock set, a published AUCTION/HYBRID listing.
    Returns (seller, listing)."""
    seller = register_seller()
    if clock is not None:
        set_clock(clock)
    overrides = {"start_price_cents": start_price_cents, "scheduled_end_at": scheduled_end_at}
    if reserve_price_cents is not None:
        overrides["reserve_price_cents"] = reserve_price_cents
    listing = create_and_publish_listing(seller["id"], format=format, **overrides)
    return seller, listing


# ─── Tier 2: bids ────────────────────────────────────────────────────

def place_bid(listing_id, bidder_id, max_proxy_cents):
    """Place a single proxy bid. Returns the Bid dict."""
    return get_success_data(api_client.create_bid(
        listing_id, create_bid_payload(bidder_id, max_proxy_cents),
        make_buyer_headers(bidder_id),
    ))


# ─── Tier 3: buy-now -> order -> (pay / ship / deliver) ──────────────

def buy_now_order(listing_id, buyer_id, shipping_cents=None):
    """Execute buy-now and return the created Order dict."""
    payload = buy_now_payload(buyer_id)
    if shipping_cents is not None:
        payload["shipping_cents"] = shipping_cents
    return get_success_data(api_client.buy_now(
        listing_id, payload, make_buyer_headers(buyer_id),
    ))


def pay_order(order, buyer_id):
    """Pay an order using its current version. Returns the updated Order dict."""
    return get_success_data(api_client.pay_order(
        order["id"], pay_order_payload(order["version"]),
        make_buyer_headers(buyer_id),
    ))


def ship_order(order_id, seller_id):
    return get_success_data(api_client.ship_order(order_id, make_seller_headers(seller_id)))


def deliver_order(order_id, buyer_id):
    return get_success_data(api_client.deliver_order(order_id, make_buyer_headers(buyer_id)))


def setup_bought_order(buy_now_price_cents=30000, shipping_cents=0, clock=CLOCK_BASE):
    """Published BUY_NOW listing -> buy-now -> Order (UNPAID).
    Returns (seller, buyer, listing, order)."""
    seller, buyer, listing = setup_published_buy_now(
        buy_now_price_cents=buy_now_price_cents, clock=clock)
    order = buy_now_order(listing["id"], buyer["id"], shipping_cents=shipping_cents)
    return seller, buyer, listing, order


def setup_paid_order(buy_now_price_cents=20000, shipping_cents=0, clock=CLOCK_BASE):
    """...through PAID. Returns (seller, buyer, listing, order_after_pay)."""
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=buy_now_price_cents, shipping_cents=shipping_cents, clock=clock)
    order = pay_order(order, buyer["id"])
    return seller, buyer, listing, order


def setup_shipped_order(buy_now_price_cents=20000, shipping_cents=0, clock=CLOCK_BASE):
    """...through SHIPPED. Returns (seller, buyer, listing, order_after_ship)."""
    seller, buyer, listing, order = setup_paid_order(
        buy_now_price_cents=buy_now_price_cents, shipping_cents=shipping_cents, clock=clock)
    order = ship_order(order["id"], seller["id"])
    return seller, buyer, listing, order


def setup_delivered_order(buy_now_price_cents=20000, shipping_cents=0,
                          clock=CLOCK_BASE, deliver_at=None):
    """...through DELIVERED. Optionally advance the clock to deliver_at before delivery.
    Returns (seller, buyer, listing, order_after_deliver)."""
    seller, buyer, listing, order = setup_shipped_order(
        buy_now_price_cents=buy_now_price_cents, shipping_cents=shipping_cents, clock=clock)
    if deliver_at is not None:
        advance_clock(deliver_at)
    order = deliver_order(order["id"], buyer["id"])
    return seller, buyer, listing, order


# ─── Tier 4: invoice lookup, suspended seller ────────────────────────

def get_invoice_for_order(order_id):
    """Fetch the SellerFeeInvoice for an order (admin computed read).
    Returns the SellerFeeInvoice dict."""
    return get_success_data(api_client.get_order_invoice(order_id, ADMIN))


def setup_suspended_seller(buy_now_price_cents=30000, clock=CLOCK_BASE):
    """A seller who has sold one BUY_NOW item large enough that the resulting
    INVOICED fee pushes fee_balance_cents above the suspension threshold.
    The order is left UNPAID so the invoice stays INVOICED.
    Returns (seller, buyer, sold_listing, order, second_draft_listing)."""
    seller, buyer, listing, order = setup_bought_order(
        buy_now_price_cents=buy_now_price_cents, shipping_cents=0, clock=clock)
    second = create_draft_listing(seller["id"], format="BUY_NOW", buy_now_price_cents=5000)
    return seller, buyer, listing, order, second


# ─── Tier 5: offers ──────────────────────────────────────────────────

def setup_offer_listing(buy_now_price_cents=50000, clock=CLOCK_BASE):
    """Published BUY_NOW listing with accepts_offers=true, plus a buyer.
    Returns (seller, buyer, listing)."""
    seller, buyer, listing = setup_published_buy_now(
        buy_now_price_cents=buy_now_price_cents, accepts_offers=True, clock=clock)
    return seller, buyer, listing


def submit_offer(listing_id, buyer_id, amount_cents):
    return get_success_data(api_client.create_offer(
        listing_id, create_offer_payload(buyer_id, amount_cents),
        make_buyer_headers(buyer_id),
    ))


def counter_offer(offer_id, actor_id, actor_role, amount_cents, expected_version):
    """Counter an offer as actor (Buyer or Seller). Returns the updated Offer dict."""
    headers = (make_seller_headers(actor_id) if actor_role == "SELLER"
               else make_buyer_headers(actor_id))
    return get_success_data(api_client.counter_offer(
        offer_id, counter_offer_payload(amount_cents, expected_version), headers,
    ))


# ─── Tier 6: disputes ────────────────────────────────────────────────

def open_dispute(order_id, buyer_id, reason="NOT_AS_DESCRIBED", requested_amount_cents=10000):
    return get_success_data(api_client.create_dispute(
        order_id, create_dispute_payload(buyer_id, reason, requested_amount_cents),
        make_buyer_headers(buyer_id),
    ))


def setup_escalated_dispute(buy_now_price_cents=30000, requested_amount_cents=10000,
                            reason="NOT_AS_DESCRIBED", clock=CLOCK_BASE,
                            escalate_at="2026-06-05T00:00:00Z"):
    """Paid order -> open dispute -> advance past the 72h response window -> escalate.
    Returns (seller, buyer, listing, order, dispute)."""
    seller, buyer, listing, order = setup_paid_order(
        buy_now_price_cents=buy_now_price_cents, shipping_cents=0, clock=clock)
    dispute = open_dispute(order["id"], buyer["id"],
                           reason=reason, requested_amount_cents=requested_amount_cents)
    advance_clock(escalate_at)
    dispute = get_success_data(
        api_client.escalate_dispute(dispute["id"], make_buyer_headers(buyer["id"])))
    return seller, buyer, listing, order, dispute
