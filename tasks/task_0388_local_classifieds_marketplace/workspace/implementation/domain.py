"""Shared domain logic: calculations, counters, cascades, state transitions.

Every behavior traces to a PRD §3 sentence (cited inline).
"""
from datetime import timedelta

import constants as C
from db import store


# ---------------------------------------------------------------------------
# Mutation helpers (audit/concurrency triple — PRD §2.4)
# ---------------------------------------------------------------------------

def touch(rec):
    """Bump version by 1 and refresh updated_at to the current clock.
    Used on every mutation of an entity that carries the version triple."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = store.now()


# ---------------------------------------------------------------------------
# compute_trust_score (PRD §3.1 / §1.3)
# ---------------------------------------------------------------------------

def completed_sale_count(member_id):
    """Count of COMPLETED meetups where member is buyer_id or seller_id (§3.1)."""
    n = 0
    for m in store.meetups.values():
        if m["status"] == "COMPLETED" and (
            m["buyer_id"] == member_id or m["seller_id"] == member_id
        ):
            n += 1
    return n


def compute_trust_score(member):
    """trust_score = clamp(base + verify_bonus + completion_bonus - flag_penalty).
    Fixed evaluation order; integer points; clamped to [0, 100] (§3.1)."""
    base = C.BASE_TRUST
    verification_bonus = C.VERIFY_BONUS if member.get("phone_verified") else 0
    flag_penalty = member.get("upheld_flag_count", 0) * C.UPHELD_PENALTY
    completion_bonus = (
        min(completed_sale_count(member["id"]), C.COMPLETION_CAP) * C.COMPLETION_BONUS
    )
    raw = base + verification_bonus + completion_bonus - flag_penalty
    return max(C.TRUST_FLOOR, min(C.TRUST_CEIL, raw))


def recompute_trust_score(member):
    member["trust_score"] = compute_trust_score(member)


# ---------------------------------------------------------------------------
# Offer / open_offer_count helpers (PRD §3.5 conserved ledger)
# ---------------------------------------------------------------------------

def _dec_open_offer_count(listing):
    if listing["open_offer_count"] > 0:
        listing["open_offer_count"] -= 1


# ---------------------------------------------------------------------------
# Conversation close cascade
# ---------------------------------------------------------------------------

def _close_open_conversations(listing_id):
    """All OPEN conversations on a listing -> CLOSED (§3.7)."""
    for conv in store.conversations.values():
        if conv["listing_id"] == listing_id and conv["status"] == "OPEN":
            conv["status"] = "CLOSED"
            touch(conv)


def _expire_open_offers(listing_id):
    """All PROPOSED/COUNTERED offers on a listing -> EXPIRED (transitive cascade,
    §3.7). Each decrements the listing's open_offer_count and clears expires_at."""
    listing = store.listings[listing_id]
    for offer in store.offers.values():
        if offer["listing_id"] == listing_id and offer["status"] in C.OFFER_OPEN_STATES:
            offer["status"] = "EXPIRED"
            offer["expires_at"] = None
            _dec_open_offer_count(listing)
            touch(offer)


def _cancel_open_meetups(listing_id):
    """Any PROPOSED/CONFIRMED meetup on a listing -> CANCELLED (§3.7 removal
    cascade)."""
    for meetup in store.meetups.values():
        if meetup["listing_id"] == listing_id and meetup["status"] in ("PROPOSED", "CONFIRMED"):
            meetup["status"] = "CANCELLED"
            touch(meetup)


# ---------------------------------------------------------------------------
# Listing removal cascade (PRD §3.7)
# ---------------------------------------------------------------------------

def remove_listing(listing):
    """Move a listing to terminal REMOVED with the dimension-specific cascade.

    From ACTIVE: decrement seller.active_listing_count; freeze sale dimension at
      its current value; clear accepted_offer_id; close OPEN conversations;
      expire PROPOSED/COUNTERED offers; cancel PROPOSED/CONFIRMED meetups.
    From EXPIRED: active_listing_count unchanged (already decremented at expiry);
      close OPEN conversations.
    From DRAFT: active_listing_count unchanged (never counted).
    All bump listing.version (§3.7).
    """
    prev = listing["publication_status"]
    if prev == "ACTIVE":
        seller = store.members.get(listing["seller_id"])
        if seller is not None and seller["active_listing_count"] > 0:
            seller["active_listing_count"] -= 1
        listing["accepted_offer_id"] = None
        _close_open_conversations(listing["id"])
        _expire_open_offers(listing["id"])
        _cancel_open_meetups(listing["id"])
    elif prev == "EXPIRED":
        _close_open_conversations(listing["id"])
    # DRAFT: nothing extra.
    listing["publication_status"] = "REMOVED"
    touch(listing)


# ---------------------------------------------------------------------------
# Listing expiry (PRD §3.3 / §3.9)
# ---------------------------------------------------------------------------

def expire_listing(listing):
    """ACTIVE -> EXPIRED. Decrement seller.active_listing_count; expire open
    offers; conversations stay OPEN (§3.3). Bumps listing.version."""
    seller = store.members.get(listing["seller_id"])
    if seller is not None and seller["active_listing_count"] > 0:
        seller["active_listing_count"] -= 1
    listing["publication_status"] = "EXPIRED"
    _expire_open_offers(listing["id"])
    touch(listing)


# ---------------------------------------------------------------------------
# Member suspend / ban cascades (PRD §3.7)
# ---------------------------------------------------------------------------

def cascade_suspend(member):
    """Suspend removes the member's ACTIVE listings (each with full removal
    cascade) (§3.7)."""
    for listing in list(store.listings.values()):
        if listing["seller_id"] == member["id"] and listing["publication_status"] == "ACTIVE":
            remove_listing(listing)


def cascade_ban(member):
    """Ban removes the member's DRAFT/ACTIVE/EXPIRED listings (each with full
    removal cascade) (§3.7)."""
    for listing in list(store.listings.values()):
        if listing["seller_id"] == member["id"] and listing["publication_status"] in (
            "DRAFT", "ACTIVE", "EXPIRED"
        ):
            remove_listing(listing)


# ---------------------------------------------------------------------------
# Reservation compensation (meetup cancel / no-show — PRD §3.6)
# ---------------------------------------------------------------------------

def revert_reservation(listing, accepted_offer_id):
    """RESERVED -> AVAILABLE compensation: clear accepted_offer_id and move the
    ACCEPTED offer to WITHDRAWN. open_offer_count unchanged (the accepted offer
    was already out of the open set) (§3.5/§3.6)."""
    listing["sale_status"] = "AVAILABLE"
    listing["accepted_offer_id"] = None
    offer = store.offers.get(accepted_offer_id)
    if offer is not None and offer["status"] == "ACCEPTED":
        offer["status"] = "WITHDRAWN"
        touch(offer)
    touch(listing)


# ---------------------------------------------------------------------------
# Alert fan-out (PRD §3.8)
# ---------------------------------------------------------------------------

def alert_fan_out(listing):
    """On publish (DRAFT->ACTIVE): for every SavedSearch whose category_slug
    matches AND (keyword null OR case-insensitive substring of title) AND
    (max_price_cents == 0 OR listing.ask_price_cents <= max_price_cents), create
    one Alert and increment that saved search's alert_count (§3.8)."""
    title_lower = listing["title"].lower()
    for ss in store.saved_searches.values():
        if ss["category_slug"] != listing["category_slug"]:
            continue
        keyword = ss.get("keyword")
        if keyword is not None and keyword.lower() not in title_lower:
            continue
        cap = ss.get("max_price_cents", 0)
        if cap != 0 and listing["ask_price_cents"] > cap:
            continue
        alert_id = store.new_id()
        store.alerts[alert_id] = {
            "id": alert_id,
            "saved_search_id": ss["id"],
            "listing_id": listing["id"],
            "matched_at": store.now(),
            "created_at": store.now(),
            "_seq": store.next_seq(),
        }
        ss["alert_count"] += 1
        touch(ss)


# ---------------------------------------------------------------------------
# Expiry sweeps (PRD §3.9)
# ---------------------------------------------------------------------------

def run_sweeps():
    """On /_clock/advance: expire ACTIVE listings whose expires_at <= clock
    (carrying open-offer cascade), then expire PROPOSED/COUNTERED offers whose
    expires_at <= clock (§3.9)."""
    now = store.now()
    # Listings first (their cascade may expire offers).
    for listing in list(store.listings.values()):
        if (
            listing["publication_status"] == "ACTIVE"
            and listing.get("expires_at") is not None
            and now >= listing["expires_at"]
        ):
            expire_listing(listing)
    # Then any remaining open offers past their own expiry.
    for offer in list(store.offers.values()):
        if (
            offer["status"] in C.OFFER_OPEN_STATES
            and offer.get("expires_at") is not None
            and now >= offer["expires_at"]
        ):
            listing = store.listings.get(offer["listing_id"])
            offer["status"] = "EXPIRED"
            offer["expires_at"] = None
            if listing is not None:
                _dec_open_offer_count(listing)
            touch(offer)


# ---------------------------------------------------------------------------
# TTL helpers
# ---------------------------------------------------------------------------

def listing_ttl_end():
    return store.now() + timedelta(days=C.LISTING_TTL_DAYS)


def offer_ttl_end():
    return store.now() + timedelta(hours=C.OFFER_TTL_HOURS)
