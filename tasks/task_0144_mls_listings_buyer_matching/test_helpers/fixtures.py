"""Composite setup helpers — multi-step preambles tests can reuse.

The MLS pipeline has a long chain of state preconditions: agents
onboarded by MlsAdmin → ListingAgent creates Listing → ListingAgent
mounts Lockbox → BuyerAgent creates Buyer → BuyerAgent submits Offer →
ListingAgent accepts → Contingencies attached → satisfied/waived →
ListingAgent closes. Most interesting test claims need the system
several steps into that chain.

IDENTITY THREADING — PRD §2.1:

- ListingAgent / BuyerAgent are ENTITY-BACKED. Every Listing-side call
  whose success depends on owning the targeted Listing MUST mint
  headers via make_listing_agent_headers(listing_agent["id"]); every
  Buyer-side call whose success depends on owning the targeted Buyer
  MUST mint headers via make_buyer_agent_headers(buyer_agent["id"]).
  The shared fallback headers in TEST_USERS are SAFE only for
  ERR_AUTH_INVALID / ERR_NOT_FOUND / ERR_FORBIDDEN_NOT_OWNER negative
  tests.

- MlsAdmin is OPAQUE. Shared TEST_USERS["mls_admin_headers"] is
  canonical for every admin call (POST /agents, PATCH /agents/{id},
  POST /_clock/advance, POST /_sweep/run).

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_advance_payload,
    counter_offer_payload,
    create_agent_payload,
    create_buyer_payload,
    create_contingency_payload,
    create_listing_payload,
    create_lockbox_payload,
    iso_at,
    iso_in_future,
    rebound_offer_payload,
    request_showing_payload,
    submit_offer_payload,
)
from .test_users import (
    TEST_USERS,
    make_buyer_agent_headers,
    make_listing_agent_headers,
)


# ===========================================================================
# Tier 1: Agent creation — PRD §3.1
# ===========================================================================
def create_listing_agent(
    *,
    brokerage_split_pct: Optional[float] = None,
    full_name: Optional[str] = None,
    brokerage_name: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /agents with agent_role=LISTING_AGENT.

    Authorized role per PRD §4 is MlsAdmin. The returned Agent.id is
    the value to thread into make_listing_agent_headers for any
    listing-side ownership-gated call.
    """
    resp = api_client.create_agent(
        create_agent_payload(
            agent_role="LISTING_AGENT",
            full_name=full_name,
            brokerage_name=brokerage_name,
            brokerage_split_pct=brokerage_split_pct,
        ),
        TEST_USERS["mls_admin_headers"],
    )
    return get_success_data(resp)


def create_buyer_agent(
    *,
    brokerage_split_pct: Optional[float] = None,
    full_name: Optional[str] = None,
    brokerage_name: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /agents with agent_role=BUYER_AGENT."""
    resp = api_client.create_agent(
        create_agent_payload(
            agent_role="BUYER_AGENT",
            full_name=full_name,
            brokerage_name=brokerage_name,
            brokerage_split_pct=brokerage_split_pct,
        ),
        TEST_USERS["mls_admin_headers"],
    )
    return get_success_data(resp)


def create_dual_agent(
    *,
    brokerage_split_pct: Optional[float] = None,
) -> Dict[str, Any]:
    resp = api_client.create_agent(
        create_agent_payload(
            agent_role="DUAL_AGENT",
            brokerage_split_pct=brokerage_split_pct,
        ),
        TEST_USERS["mls_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 1: Listing creation — PRD §3.2
# ===========================================================================
def create_listing(
    listing_agent: Dict[str, Any],
    *,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
    zip_code: str = "94110",
    bedrooms: int = 3,
    bathrooms: float = 2.0,
    features: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """POST /listings. PRD §3.2 requires `listing_agent_id` to equal
    X-User-ID, so the headers MUST be built from the listing agent's
    actual id."""
    payload = create_listing_payload(
        listing_agent_id=listing_agent["id"],
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
        zip_code=zip_code,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        features=features,
    )
    resp = api_client.create_listing(
        payload, make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


def create_buyer(
    buyer_agent: Dict[str, Any],
    *,
    max_price_cents: int = 60_000_000,
    min_price_cents: int = 40_000_000,
    min_bedrooms: int = 2,
    min_bathrooms: float = 1.0,
    desired_zips: Optional[List[str]] = None,
    desired_features: Optional[List[str]] = None,
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /buyers. PRD §3.3 requires `buyer_agent_id` to equal
    X-User-ID."""
    payload = create_buyer_payload(
        buyer_agent_id=buyer_agent["id"],
        full_name=full_name,
        max_price_cents=max_price_cents,
        min_price_cents=min_price_cents,
        min_bedrooms=min_bedrooms,
        min_bathrooms=min_bathrooms,
        desired_zips=desired_zips,
        desired_features=desired_features,
    )
    resp = api_client.create_buyer(
        payload, make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 2: Composite scenarios — listing + lockbox + buyer
# ===========================================================================
def create_listing_with_armed_lockbox(
    *,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
    listing_agent_split: float = 0.70,
    zip_code: str = "94110",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """ListingAgent + ACTIVE Listing + ARMED Lockbox. Returns
    (listing_agent, listing, lockbox)."""
    la = create_listing_agent(brokerage_split_pct=listing_agent_split)
    listing = create_listing(
        la,
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
        zip_code=zip_code,
    )
    lock_resp = api_client.create_lockbox(
        listing["id"], create_lockbox_payload(),
        make_listing_agent_headers(la["id"]),
    )
    lockbox = get_success_data(lock_resp)
    return la, listing, lockbox


def setup_listing_and_buyer(
    *,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
    listing_agent_split: float = 0.70,
    buyer_agent_split: float = 0.70,
    zip_code: str = "94110",
    bedrooms: int = 3,
    bathrooms: float = 2.0,
    features: Optional[List[str]] = None,
    max_price_cents: int = 60_000_000,
    min_price_cents: int = 40_000_000,
    min_bedrooms: int = 2,
    min_bathrooms: float = 1.0,
    desired_zips: Optional[List[str]] = None,
    desired_features: Optional[List[str]] = None,
) -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any],
    Dict[str, Any], Dict[str, Any],
]:
    """Build ListingAgent + Listing + Lockbox(ARMED) + BuyerAgent +
    Buyer.

    Returns (listing_agent, listing, lockbox, buyer_agent, buyer).
    """
    la = create_listing_agent(brokerage_split_pct=listing_agent_split)
    listing = create_listing(
        la,
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
        zip_code=zip_code,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        features=features,
    )
    lock_resp = api_client.create_lockbox(
        listing["id"], create_lockbox_payload(),
        make_listing_agent_headers(la["id"]),
    )
    lockbox = get_success_data(lock_resp)
    ba = create_buyer_agent(brokerage_split_pct=buyer_agent_split)
    buyer = create_buyer(
        ba,
        max_price_cents=max_price_cents,
        min_price_cents=min_price_cents,
        min_bedrooms=min_bedrooms,
        min_bathrooms=min_bathrooms,
        desired_zips=desired_zips,
        desired_features=desired_features,
    )
    return la, listing, lockbox, ba, buyer


# ===========================================================================
# Tier 3: Offer lifecycle helpers — PRD §3.6
# ===========================================================================
def submit_offer(
    listing: Dict[str, Any],
    buyer: Dict[str, Any],
    buyer_agent: Dict[str, Any],
    *,
    offer_price_cents: int = 50_000_000,
    earnest_money_cents: int = 1_000_000,
    estimated_seller_concessions_cents: Optional[int] = None,
    expires_at: Optional[str] = None,
    offset_seconds: int = 24 * 3600,
    parent_counter_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /listings/{id}/offers as BuyerAgent. PRD §3.3/§3.6: the
    BuyerAgent must own the Buyer, hence headers built from
    buyer_agent.id."""
    payload = submit_offer_payload(
        buyer_id=buyer["id"],
        offer_price_cents=offer_price_cents,
        earnest_money_cents=earnest_money_cents,
        estimated_seller_concessions_cents=estimated_seller_concessions_cents,
        expires_at=expires_at,
        offset_seconds=offset_seconds,
        parent_counter_id=parent_counter_id,
    )
    resp = api_client.submit_offer(
        listing["id"], payload,
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def accept_offer(
    listing: Dict[str, Any],
    offer: Dict[str, Any],
    listing_agent: Dict[str, Any],
) -> Dict[str, Any]:
    """POST /listings/{id}/offers/{id}/accept as ListingAgent owning
    the Listing."""
    resp = api_client.accept_offer(
        listing["id"], offer["id"],
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


def reject_offer(
    listing: Dict[str, Any],
    offer: Dict[str, Any],
    listing_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.reject_offer(
        listing["id"], offer["id"],
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


def withdraw_offer(
    listing: Dict[str, Any],
    offer: Dict[str, Any],
    buyer_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.withdraw_offer(
        listing["id"], offer["id"],
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def counter_offer(
    listing: Dict[str, Any],
    offer: Dict[str, Any],
    listing_agent: Dict[str, Any],
    *,
    counter_price_cents: int = 51_000_000,
    counter_concessions_cents: int = 0,
    counter_expires_at: Optional[str] = None,
    offset_seconds: int = 12 * 3600,
) -> Dict[str, Any]:
    payload = counter_offer_payload(
        counter_price_cents=counter_price_cents,
        counter_concessions_cents=counter_concessions_cents,
        counter_expires_at=counter_expires_at,
        offset_seconds=offset_seconds,
    )
    resp = api_client.counter_offer(
        listing["id"], offer["id"], payload,
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


def rebound_offer(
    listing: Dict[str, Any],
    offer: Dict[str, Any],
    buyer_agent: Dict[str, Any],
    *,
    offer_price_cents: int = 50_000_000,
    earnest_money_cents: int = 1_000_000,
    estimated_seller_concessions_cents: Optional[int] = None,
    expires_at: Optional[str] = None,
    offset_seconds: int = 12 * 3600,
) -> Dict[str, Any]:
    payload = rebound_offer_payload(
        offer_price_cents=offer_price_cents,
        earnest_money_cents=earnest_money_cents,
        estimated_seller_concessions_cents=estimated_seller_concessions_cents,
        expires_at=expires_at,
        offset_seconds=offset_seconds,
    )
    resp = api_client.rebound_offer(
        listing["id"], offer["id"], payload,
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Showing lifecycle — PRD §3.5
# ===========================================================================
def request_showing(
    listing: Dict[str, Any],
    buyer: Dict[str, Any],
    buyer_agent: Dict[str, Any],
    *,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    duration_minutes: int = 60,
    offset_seconds: int = 3600,
) -> Dict[str, Any]:
    payload = request_showing_payload(
        buyer_agent_id=buyer_agent["id"],
        buyer_id=buyer["id"],
        start_at=start_at,
        end_at=end_at,
        duration_minutes=duration_minutes,
        offset_seconds=offset_seconds,
    )
    resp = api_client.request_showing(
        listing["id"], payload,
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def approve_showing(
    listing: Dict[str, Any],
    showing: Dict[str, Any],
    listing_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.approve_showing(
        listing["id"], showing["id"],
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Contingency helpers — PRD §3.7
# ===========================================================================
def attach_contingency(
    listing: Dict[str, Any],
    offer: Dict[str, Any],
    buyer_agent: Dict[str, Any],
    *,
    kind: str = "INSPECTION",
    deadline_at: Optional[str] = None,
    offset_seconds: int = 7 * 24 * 3600,
) -> Dict[str, Any]:
    payload = create_contingency_payload(
        offer_id=offer["id"], kind=kind,
        deadline_at=deadline_at,
        offset_seconds=offset_seconds,
    )
    resp = api_client.create_contingency(
        listing["id"], payload,
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def satisfy_contingency(
    listing: Dict[str, Any],
    contingency: Dict[str, Any],
    buyer_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.satisfy_contingency(
        listing["id"], contingency["id"],
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def waive_contingency(
    listing: Dict[str, Any],
    contingency: Dict[str, Any],
    buyer_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.waive_contingency(
        listing["id"], contingency["id"],
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def fail_contingency(
    listing: Dict[str, Any],
    contingency: Dict[str, Any],
    buyer_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.fail_contingency(
        listing["id"], contingency["id"],
        make_buyer_agent_headers(buyer_agent["id"]),
    )
    return get_success_data(resp)


def close_listing(
    listing: Dict[str, Any],
    listing_agent: Dict[str, Any],
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """POST /listings/{id}/close. PRD §4 lists `version` as input; pass
    the current listing.version."""
    v = version if version is not None else listing["version"]
    resp = api_client.close_listing(
        listing["id"], {"version": v},
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


def withdraw_listing(
    listing: Dict[str, Any],
    listing_agent: Dict[str, Any],
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    v = version if version is not None else listing["version"]
    resp = api_client.withdraw_listing(
        listing["id"], {"version": v},
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: Lockbox lifecycle — PRD §3.5
# ===========================================================================
def disarm_lockbox(
    listing: Dict[str, Any],
    listing_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.disarm_lockbox(
        listing["id"],
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


def arm_lockbox(
    listing: Dict[str, Any],
    listing_agent: Dict[str, Any],
) -> Dict[str, Any]:
    resp = api_client.arm_lockbox(
        listing["id"],
        make_listing_agent_headers(listing_agent["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: Listing-under-contract — full preamble to contingent state
# ===========================================================================
def setup_listing_under_contract(
    *,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
    listing_agent_split: float = 0.70,
    buyer_agent_split: float = 0.70,
    offer_price_cents: Optional[int] = None,
    earnest_money_cents: int = 1_000_000,
    estimated_seller_concessions_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Drive: Listing(ACTIVE) + Lockbox(ARMED) + Buyer + Offer(SUBMITTED)
    → accept → Listing(UNDER_CONTRACT), Offer(ACCEPTED).

    Returns a dict {listing_agent, listing, lockbox, buyer_agent,
    buyer, offer, accepted_listing, accepted_offer}.
    """
    if offer_price_cents is None:
        offer_price_cents = list_price_cents
    la, listing, lockbox, ba, buyer = setup_listing_and_buyer(
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
        listing_agent_split=listing_agent_split,
        buyer_agent_split=buyer_agent_split,
    )
    offer = submit_offer(
        listing, buyer, ba,
        offer_price_cents=offer_price_cents,
        earnest_money_cents=earnest_money_cents,
        estimated_seller_concessions_cents=estimated_seller_concessions_cents,
    )
    accepted_offer = accept_offer(listing, offer, la)
    # Re-fetch the listing to capture UNDER_CONTRACT status and any
    # accepted_offer_id update.
    listing_after_resp = api_client.get_listing(
        listing["id"], TEST_USERS["mls_admin_headers"],
    )
    accepted_listing = get_success_data(listing_after_resp)
    return {
        "listing_agent": la,
        "buyer_agent": ba,
        "listing": listing,
        "lockbox": lockbox,
        "buyer": buyer,
        "offer": offer,
        "accepted_offer": accepted_offer,
        "accepted_listing": accepted_listing,
    }


# ===========================================================================
# Tier 5: Sold listing — drive UNDER_CONTRACT → SOLD
# ===========================================================================
def setup_sold_listing(
    *,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
    listing_agent_split: float = 0.70,
    buyer_agent_split: float = 0.70,
    contingency_kinds: Optional[List[str]] = None,
    waive_all: bool = True,
) -> Dict[str, Any]:
    """Build all the way through UNDER_CONTRACT → SOLD.

    If `contingency_kinds` is provided, attach those contingencies on
    the accepted offer and waive (default) or satisfy them before close.
    """
    state = setup_listing_under_contract(
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
        listing_agent_split=listing_agent_split,
        buyer_agent_split=buyer_agent_split,
    )
    contingencies: List[Dict[str, Any]] = []
    if contingency_kinds:
        for kind in contingency_kinds:
            c = attach_contingency(
                state["accepted_listing"], state["accepted_offer"],
                state["buyer_agent"], kind=kind,
            )
            if waive_all:
                c = waive_contingency(
                    state["accepted_listing"], c, state["buyer_agent"],
                )
            else:
                c = satisfy_contingency(
                    state["accepted_listing"], c, state["buyer_agent"],
                )
            contingencies.append(c)
    # Re-fetch listing to get current version before close.
    listing_resp = api_client.get_listing(
        state["accepted_listing"]["id"], TEST_USERS["mls_admin_headers"],
    )
    current_listing = get_success_data(listing_resp)
    sold = close_listing(
        current_listing, state["listing_agent"],
        version=current_listing["version"],
    )
    state["sold_listing"] = sold
    state["contingencies"] = contingencies
    return state


# ===========================================================================
# Tier 4: Counter / rebound chain — PRD §3.6
# ===========================================================================
def setup_offer_with_open_counter(
    *,
    offer_price_cents: int = 49_000_000,
    counter_price_cents: int = 51_000_000,
    counter_concessions_cents: int = 0,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
) -> Dict[str, Any]:
    """Build an Offer in COUNTERED state with an OPEN Counter row."""
    la, listing, lockbox, ba, buyer = setup_listing_and_buyer(
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
    )
    offer = submit_offer(
        listing, buyer, ba,
        offer_price_cents=offer_price_cents,
    )
    counter = counter_offer(
        listing, offer, la,
        counter_price_cents=counter_price_cents,
        counter_concessions_cents=counter_concessions_cents,
    )
    return {
        "listing_agent": la,
        "buyer_agent": ba,
        "listing": listing,
        "lockbox": lockbox,
        "buyer": buyer,
        "offer": offer,
        "counter": counter,
    }


def setup_multi_round_negotiation(
    *,
    list_price_cents: int = 50_000_000,
    co_op_pct: float = 0.025,
    total_commission_pct: float = 0.06,
    round1_offer_cents: int = 49_000_000,
    round1_counter_cents: int = 50_000_000,
    round1_counter_concessions: int = 200_000,
    round2_offer_cents: int = 50_000_000,
    round2_counter_cents: int = 50_500_000,
    round2_counter_concessions: int = 50_000,
    round3_offer_cents: int = 50_000_000,
) -> Dict[str, Any]:
    """Three-round chain.

    Offer1(SUBMITTED) → Counter1(OPEN)/Offer1=COUNTERED
       → Rebound → Offer2(SUBMITTED)/Counter1=REBOUND
       → Counter2(OPEN)/Offer2=COUNTERED
       → Rebound → Offer3(SUBMITTED)/Counter2=REBOUND.

    Returns dict with all three offers and both counters.
    """
    la, listing, lockbox, ba, buyer = setup_listing_and_buyer(
        list_price_cents=list_price_cents,
        co_op_pct=co_op_pct,
        total_commission_pct=total_commission_pct,
    )
    offer1 = submit_offer(
        listing, buyer, ba,
        offer_price_cents=round1_offer_cents,
        estimated_seller_concessions_cents=100_000,
    )
    counter1 = counter_offer(
        listing, offer1, la,
        counter_price_cents=round1_counter_cents,
        counter_concessions_cents=round1_counter_concessions,
    )
    offer2 = rebound_offer(
        listing, offer1, ba,
        offer_price_cents=round2_offer_cents,
        earnest_money_cents=1_000_000,
        estimated_seller_concessions_cents=100_000,
    )
    counter2 = counter_offer(
        listing, offer2, la,
        counter_price_cents=round2_counter_cents,
        counter_concessions_cents=round2_counter_concessions,
    )
    offer3 = rebound_offer(
        listing, offer2, ba,
        offer_price_cents=round3_offer_cents,
        earnest_money_cents=1_000_000,
        estimated_seller_concessions_cents=100_000,
    )
    return {
        "listing_agent": la,
        "buyer_agent": ba,
        "listing": listing,
        "lockbox": lockbox,
        "buyer": buyer,
        "offer1": offer1,
        "counter1": counter1,
        "offer2": offer2,
        "counter2": counter2,
        "offer3": offer3,
    }


# ===========================================================================
# Tier 4: Showing scheduling
# ===========================================================================
def setup_scheduled_showing(
    *,
    duration_minutes: int = 60,
    offset_seconds: int = 3600,
) -> Dict[str, Any]:
    """Listing(ACTIVE) + Lockbox(ARMED) + REQUESTED showing → approve →
    SCHEDULED showing. Returns dict with all entities including the
    approved showing (which carries access_code in the response)."""
    la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
    showing = request_showing(
        listing, buyer, ba,
        duration_minutes=duration_minutes,
        offset_seconds=offset_seconds,
    )
    approved = approve_showing(listing, showing, la)
    return {
        "listing_agent": la,
        "buyer_agent": ba,
        "listing": listing,
        "lockbox": lockbox,
        "buyer": buyer,
        "showing": showing,
        "scheduled_showing": approved,
    }


# ===========================================================================
# Tier 5: Clock / sweep — PRD §3.9
# ===========================================================================
def advance_clock(to_iso: str) -> Dict[str, Any]:
    """POST /_clock/advance to a given ISO 8601 instant."""
    resp = api_client.clock_advance(
        clock_advance_payload(to=to_iso),
        TEST_USERS["mls_admin_headers"],
    )
    return get_success_data(resp)


def run_sweep() -> Dict[str, Any]:
    """POST /_sweep/run."""
    resp = api_client.sweep_run(TEST_USERS["mls_admin_headers"])
    return get_success_data(resp)


def advance_clock_and_sweep(to_iso: str) -> Dict[str, Any]:
    advance_clock(to_iso)
    return run_sweep()


def days_from_now_iso(days: int, *, extra_seconds: int = 0) -> str:
    """Helper: ISO 8601 timestamp `days` ahead of wall-time-now, with an
    optional extra offset in seconds. Useful for 180-day listing
    expiration tests."""
    dt = datetime.now(tz=timezone.utc) + timedelta(
        days=days, seconds=extra_seconds,
    )
    return iso_at(dt)


def get_listing_state(listing_id: str) -> Dict[str, Any]:
    """GET /listings/{id} via opaque admin (read-only is unrestricted
    by ownership for admins)."""
    resp = api_client.get_listing(
        listing_id, TEST_USERS["mls_admin_headers"],
    )
    return get_success_data(resp)


def get_offer_state(listing_id: str, offer_id: str) -> Dict[str, Any]:
    """No single GET endpoint for one offer is in the PRD, but list +
    filter by id works."""
    resp = api_client.list_offers(
        listing_id, TEST_USERS["mls_admin_headers"],
    )
    data = get_success_data(resp)
    # Envelope unwrapping varies; the framework's get_success_data
    # already returns the data payload (list for /offers). Hunt by id.
    if isinstance(data, list):
        for row in data:
            if row.get("id") == offer_id:
                return row
    raise AssertionError(
        f"Offer {offer_id} not in /listings/{listing_id}/offers"
    )


def list_commission_splits(listing_id: str,
                           variant: Optional[str] = None,
                           ) -> List[Dict[str, Any]]:
    """GET /listings/{listing_id}/commission-splits as MlsAdmin."""
    params = {"variant": variant} if variant else None
    resp = api_client.list_commission_splits(
        listing_id, TEST_USERS["mls_admin_headers"], params=params,
    )
    data = get_success_data(resp)
    return data if isinstance(data, list) else []


__all__ = [
    # Agent creation
    "create_listing_agent",
    "create_buyer_agent",
    "create_dual_agent",
    # Listing / Buyer / Lockbox
    "create_listing",
    "create_buyer",
    "create_listing_with_armed_lockbox",
    "setup_listing_and_buyer",
    # Offer lifecycle
    "submit_offer",
    "accept_offer",
    "reject_offer",
    "withdraw_offer",
    "counter_offer",
    "rebound_offer",
    # Showing lifecycle
    "request_showing",
    "approve_showing",
    "setup_scheduled_showing",
    # Contingencies
    "attach_contingency",
    "satisfy_contingency",
    "waive_contingency",
    "fail_contingency",
    # Listing actions
    "close_listing",
    "withdraw_listing",
    # Lockbox
    "arm_lockbox",
    "disarm_lockbox",
    # Composite scenarios
    "setup_listing_under_contract",
    "setup_sold_listing",
    "setup_offer_with_open_counter",
    "setup_multi_round_negotiation",
    # Clock / sweep
    "advance_clock",
    "run_sweep",
    "advance_clock_and_sweep",
    "days_from_now_iso",
    # Read helpers
    "get_listing_state",
    "get_offer_state",
    "list_commission_splits",
]
