"""Composite setup helpers.

These encapsulate the multi-step API sequences that test claims require so the
tests focus on assertions. All setup calls use get_success_data() (lenient) so
that a broken precondition surfaces a clear "Setup step failed" message.

Identity threading: Seller/Buyer/Member are entity-backed roles, so every
ownership-gated call uses make_<role>_headers(member_id) with the real Member id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_seller_headers,
    make_buyer_headers,
    make_member_headers,
    make_moderator_headers,
    make_admin_headers,
)
from . import factories as F


ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
MOD = TEST_USERS["moderator_headers"]


# --- Primitive builders ------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock without running sweeps (PRD §3.9)."""
    return get_success_data(_api.clock_set({"to_iso8601": to_iso8601}, headers=ADMIN))


def advance_clock(to_iso8601: str):
    """Advance the clock and run expiry sweeps (PRD §3.9)."""
    return get_success_data(_api.clock_advance({"to_iso8601": to_iso8601}, headers=ADMIN))


def create_category(slug="furniture", name="Furniture", **overrides):
    payload = F.create_category_payload(slug=slug, name=name, **overrides)
    return get_success_data(_api.create_category(payload, headers=ADMIN))


def create_safe_trade_spot(**overrides):
    payload = F.create_safe_trade_spot_payload(**overrides)
    return get_success_data(_api.create_safe_trade_spot(payload, headers=ADMIN))


def create_member(email=None, display_name="M", role_kind=None):
    kwargs = {"display_name": display_name}
    if email is not None:
        kwargs["email"] = email
    if role_kind is not None:
        kwargs["role_kind"] = role_kind
    payload = F.create_member_payload(**kwargs)
    return get_success_data(_api.create_member(payload, headers=ANON))


def verify_member(member_id):
    """Run request + confirm verification; member ends phone_verified=true."""
    req = get_success_data(_api.request_verification(member_id, headers=make_member_headers(member_id)))
    code = req["verification_code"]
    return get_success_data(
        _api.confirm_verification(member_id, {"verification_code": code},
                                  headers=make_member_headers(member_id))
    )


def create_listing(seller_id, **overrides):
    payload = F.create_listing_payload(seller_id, **overrides)
    return get_success_data(_api.create_listing(payload, headers=make_seller_headers(seller_id)))


def publish_listing(listing_id, seller_id):
    return get_success_data(_api.publish_listing(listing_id, headers=make_seller_headers(seller_id)))


def create_conversation(listing_id, buyer_id):
    payload = F.create_conversation_payload(listing_id, buyer_id)
    return get_success_data(_api.create_conversation(payload, headers=make_buyer_headers(buyer_id)))


def create_offer(conversation_id, buyer_id, amount_cents=9000):
    payload = F.create_offer_payload(conversation_id, amount_cents=amount_cents)
    return get_success_data(_api.create_offer(payload, headers=make_buyer_headers(buyer_id)))


# --- Tier 1/2: hierarchies ---------------------------------------------------

def setup_published_listing(ask_price_cents=10000, min_acceptable_price_cents=5000,
                            category_slug="furniture", category_overrides=None,
                            title="Oak Desk", verify_seller=False, set_clock_to=None):
    """Category + Seller + one ACTIVE (published) listing.

    Returns dict: {seller, listing, listing_version}.
    """
    if set_clock_to:
        set_clock(set_clock_to)
    create_category(slug=category_slug, name=category_slug.title(),
                    **(category_overrides or {}))
    seller = create_member(role_kind="SELLER", display_name="S")
    if verify_seller:
        seller = verify_member(seller["id"])
    listing = create_listing(seller["id"], category_slug=category_slug, title=title,
                             ask_price_cents=ask_price_cents,
                             min_acceptable_price_cents=min_acceptable_price_cents)
    listing = publish_listing(listing["id"], seller["id"])
    return {"seller": seller, "listing": listing, "listing_version": listing["version"]}


def setup_listing_with_open_offer(ask_price_cents=10000, min_acceptable_price_cents=5000,
                                  amount_cents=9000, category_slug="furniture",
                                  category_overrides=None, set_clock_to=None,
                                  verify_seller=False):
    """Published listing + Buyer + OPEN offer.

    Returns dict: {seller, buyer, listing, conversation, offer, listing_version}.
    """
    base = setup_published_listing(ask_price_cents=ask_price_cents,
                                   min_acceptable_price_cents=min_acceptable_price_cents,
                                   category_slug=category_slug,
                                   category_overrides=category_overrides,
                                   set_clock_to=set_clock_to,
                                   verify_seller=verify_seller)
    buyer = create_member(role_kind="BUYER", display_name="B")
    conv = create_conversation(base["listing"]["id"], buyer["id"])
    offer = create_offer(conv["id"], buyer["id"], amount_cents=amount_cents)
    base.update({"buyer": buyer, "conversation": conv, "offer": offer})
    return base


def setup_reserved_listing(ask_price_cents=10000, min_acceptable_price_cents=5000,
                           amount_cents=9000, category_slug="furniture",
                           category_overrides=None, set_clock_to=None,
                           verify_seller=False):
    """Published listing with one accepted offer -> listing RESERVED.

    Returns dict: {seller, buyer, listing, conversation, offer, offer_version,
    listing_version_after_accept}. The offer's post-accept version is captured
    for meetup creation's expected_offer_version.
    """
    base = setup_listing_with_open_offer(ask_price_cents=ask_price_cents,
                                         min_acceptable_price_cents=min_acceptable_price_cents,
                                         amount_cents=amount_cents,
                                         category_slug=category_slug,
                                         category_overrides=category_overrides,
                                         set_clock_to=set_clock_to,
                                         verify_seller=verify_seller)
    seller_id = base["seller"]["id"]
    accepted = get_success_data(
        _api.accept_offer(base["offer"]["id"],
                          {"expected_listing_version": base["listing_version"]},
                          headers=make_seller_headers(seller_id))
    )
    base["offer"] = accepted
    base["offer_version"] = accepted["version"]
    return base


def setup_meetup_proposed(start_at="2026-06-02T14:00:00Z", end_at="2026-06-02T15:00:00Z",
                          spot_overrides=None, ask_price_cents=10000,
                          min_acceptable_price_cents=5000, amount_cents=9000,
                          category_slug="furniture", category_overrides=None,
                          set_clock_to="2026-06-01T08:00:00Z"):
    """Reserved listing + SafeTradeSpot + a PROPOSED meetup against the offer.

    Returns dict including {spot, meetup} added to the reserved-listing dict.
    """
    spot = create_safe_trade_spot(**(spot_overrides or {}))
    base = setup_reserved_listing(ask_price_cents=ask_price_cents,
                                  min_acceptable_price_cents=min_acceptable_price_cents,
                                  amount_cents=amount_cents,
                                  category_slug=category_slug,
                                  category_overrides=category_overrides,
                                  set_clock_to=set_clock_to)
    buyer_id = base["buyer"]["id"]
    meetup = get_success_data(
        _api.create_meetup(
            F.create_meetup_payload(base["offer"]["id"], spot["id"],
                                    base["offer_version"], start_at=start_at, end_at=end_at),
            headers=make_buyer_headers(buyer_id),
        )
    )
    base.update({"spot": spot, "meetup": meetup})
    return base


def setup_meetup_confirmed(**overrides):
    """Reserved listing + CONFIRMED meetup. Confirmed by the seller (counterparty
    to the buyer who proposed). Returns the same dict with confirmed meetup."""
    base = setup_meetup_proposed(**overrides)
    seller_id = base["seller"]["id"]
    confirmed = get_success_data(
        _api.confirm_meetup(base["meetup"]["id"], headers=make_seller_headers(seller_id))
    )
    base["meetup"] = confirmed
    return base


# --- Tier 3: negotiation walking --------------------------------------------

def counter(offer_id, actor_member_id, actor_role, amount_cents):
    """One counter step by the given actor (role is 'Seller' or 'Buyer')."""
    headers = (make_seller_headers(actor_member_id) if actor_role == "Seller"
               else make_buyer_headers(actor_member_id))
    return get_success_data(_api.counter_offer(offer_id, {"amount_cents": amount_cents},
                                               headers=headers))


def setup_offer_at_round(target_round, ask_price_cents=10000,
                         min_acceptable_price_cents=1000, set_clock_to=None):
    """Build an offer driven to exactly `target_round` counter rounds.

    Buyer proposes (round 0, last_actor_side BUYER), then sides alternate
    counters S, B, S, ... each incrementing round_count by 1. Returns dict
    {seller, buyer, listing, conversation, offer} with offer at the target round.
    """
    assert 0 <= target_round <= 5
    base = setup_listing_with_open_offer(ask_price_cents=ask_price_cents,
                                         min_acceptable_price_cents=min_acceptable_price_cents,
                                         amount_cents=max(min_acceptable_price_cents, 4000),
                                         set_clock_to=set_clock_to)
    seller_id = base["seller"]["id"]
    buyer_id = base["buyer"]["id"]
    offer_id = base["offer"]["id"]
    # After propose, last_actor_side == BUYER, so the seller moves first.
    actors = ["Seller", "Buyer"]
    amount = max(min_acceptable_price_cents, 4000)
    last = None
    for i in range(target_round):
        role = actors[i % 2]
        actor_id = seller_id if role == "Seller" else buyer_id
        # Vary amount but keep buyer-side counters at/above floor.
        amount = max(min_acceptable_price_cents, 5000 + i * 100)
        last = counter(offer_id, actor_id, role, amount)
    base["offer"] = last if last is not None else base["offer"]
    return base


# --- Tier 4: active-listing accumulation -------------------------------------

def setup_seller_with_active_listings(n, ask_price_cents=10000,
                                      min_acceptable_price_cents=5000,
                                      category_slug="furniture"):
    """Seller with exactly n published (ACTIVE) listings, plus a leftover DRAFT.

    Returns dict {seller, active_listings: [...], draft_listing}.
    """
    create_category(slug=category_slug, name=category_slug.title())
    seller = create_member(role_kind="SELLER", display_name="S")
    active = []
    for i in range(n):
        lst = create_listing(seller["id"], category_slug=category_slug,
                             title=f"L{i + 1}", description="x",
                             ask_price_cents=ask_price_cents,
                             min_acceptable_price_cents=min_acceptable_price_cents)
        lst = publish_listing(lst["id"], seller["id"])
        active.append(lst)
    draft = create_listing(seller["id"], category_slug=category_slug,
                           title="Draft", description="x",
                           ask_price_cents=ask_price_cents,
                           min_acceptable_price_cents=min_acceptable_price_cents)
    return {"seller": seller, "active_listings": active, "draft_listing": draft}


# --- Tier 5: moderation accumulation -----------------------------------------

def raise_listing_flag(listing_id, reporter_id, reason="SPAM"):
    payload = F.create_flag_payload(reporter_id, "LISTING", reason=reason,
                                    target_listing_id=listing_id)
    return get_success_data(_api.create_flag(payload, headers=make_member_headers(reporter_id)))


def raise_member_flag(target_member_id, reporter_id, reason="SCAM"):
    payload = F.create_flag_payload(reporter_id, "MEMBER", reason=reason,
                                    target_member_id=target_member_id)
    return get_success_data(_api.create_flag(payload, headers=make_member_headers(reporter_id)))


def setup_member_with_upheld_flags(count, reason="SCAM"):
    """Create a member and accumulate `count` UPHELD member-flags against them.

    Returns dict {member, reporter, flags}. Reporter is a distinct member.
    """
    member = create_member(role_kind="BOTH", display_name="M")
    reporter = create_member(role_kind="BUYER", display_name="R")
    flags = []
    for _ in range(count):
        flag = raise_member_flag(member["id"], reporter["id"], reason=reason)
        get_success_data(_api.uphold_flag(flag["id"], headers=MOD))
        flags.append(flag)
    return {"member": member, "reporter": reporter, "flags": flags}
