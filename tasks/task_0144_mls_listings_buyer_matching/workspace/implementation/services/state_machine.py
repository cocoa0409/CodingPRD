"""State-machine transitions and cascade orchestration (scaffold §1.2)."""
from __future__ import annotations

from datetime import datetime

from db import store
from services.calculations import (
    compute_commission_split,
    provisional_net_to_seller,
)
from utils import new_uuid


# ─────────────────────────────────────────────────────────────────────────────
# Mutation helpers
# ─────────────────────────────────────────────────────────────────────────────


def bump_version(entity: dict, now: datetime) -> None:
    """Increment version + refresh updated_at (PRD §2.6)."""
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 0) + 1


# ─────────────────────────────────────────────────────────────────────────────
# Recomputers
# ─────────────────────────────────────────────────────────────────────────────


def recompute_showing_count(listing: dict, now: datetime) -> None:
    listing_id = listing["id"]
    count = sum(
        1
        for s in store.showings.values()
        if s["listing_id"] == listing_id and s["status"] in ("SCHEDULED", "COMPLETED")
    )
    listing["showing_count"] = count
    bump_version(listing, now)


# ─────────────────────────────────────────────────────────────────────────────
# CommissionSplit emission
# ─────────────────────────────────────────────────────────────────────────────


def emit_commission_split(listing: dict, offer: dict, variant: str, now: datetime) -> dict:
    listing_agent = store.agents[listing["listing_agent_id"]]
    buyer = store.buyers[offer["buyer_id"]]
    buyer_agent = store.agents[buyer["buyer_agent_id"]]

    parts = compute_commission_split(
        sale_price_cents=offer["offer_price_cents"],
        total_commission_pct=listing["total_commission_pct"],
        co_op_pct=listing["co_op_pct"],
        listing_agent_split=listing_agent["brokerage_split_pct"],
        buyer_agent_split=buyer_agent["brokerage_split_pct"],
    )
    cs = {
        "id": new_uuid(),
        "created_at": now,
        "listing_id": listing["id"],
        "offer_id": offer["id"],
        "sale_price_cents": offer["offer_price_cents"],
        "gross_commission_cents": parts["gross_commission_cents"],
        "listing_side_cents": parts["listing_side_cents"],
        "buyer_side_cents": parts["buyer_side_cents"],
        "listing_agent_cents": parts["listing_agent_cents"],
        "listing_brokerage_cents": parts["listing_brokerage_cents"],
        "buyer_agent_cents": parts["buyer_agent_cents"],
        "buyer_brokerage_cents": parts["buyer_brokerage_cents"],
        "variant": variant,
    }
    store.commission_splits[cs["id"]] = cs
    return cs


# ─────────────────────────────────────────────────────────────────────────────
# Cascade helpers
# ─────────────────────────────────────────────────────────────────────────────


def withdraw_open_counters_of_offer(offer_id: str, now: datetime) -> None:
    for c in store.counters.values():
        if c["offer_id"] == offer_id and c["status"] == "OPEN":
            c["status"] = "WITHDRAWN"
            c["updated_at_unused"] = now  # Counter has no updated_at; placeholder.


def reject_other_submitted_offers(listing_id: str, accepted_offer_id: str, now: datetime) -> None:
    for o in store.offers.values():
        if (
            o["listing_id"] == listing_id
            and o["status"] == "SUBMITTED"
            and o["id"] != accepted_offer_id
        ):
            o["status"] = "REJECTED"
            bump_version(o, now)
            withdraw_open_counters_of_offer(o["id"], now)


def cancel_open_showings_of_listing(listing_id: str, now: datetime) -> None:
    for s in store.showings.values():
        if s["listing_id"] == listing_id and s["status"] in ("REQUESTED", "SCHEDULED"):
            s["status"] = "CANCELLED"
            bump_version(s, now)


def disarm_lockbox_of_listing(listing_id: str, now: datetime) -> None:
    lb_id = store.lockbox_by_listing.get(listing_id)
    if not lb_id:
        return
    lb = store.lockboxes.get(lb_id)
    if lb and lb["status"] == "ARMED":
        lb["status"] = "DISARMED"
        bump_version(lb, now)


def retire_lockbox_of_listing(listing_id: str, now: datetime) -> None:
    lb_id = store.lockbox_by_listing.get(listing_id)
    if not lb_id:
        return
    lb = store.lockboxes.get(lb_id)
    if not lb:
        return
    if lb["status"] in ("ARMED", "DISARMED"):
        lb["status"] = "RETIRED"
        bump_version(lb, now)


# ─────────────────────────────────────────────────────────────────────────────
# Major transitions
# ─────────────────────────────────────────────────────────────────────────────


def accept_offer_cascade(listing: dict, offer: dict, now: datetime) -> None:
    """Listing ACTIVE → UNDER_CONTRACT cascade (scaffold §1.2)."""
    # 1. Offer.status := ACCEPTED
    offer["status"] = "ACCEPTED"
    # 2. Listing.accepted_offer_id := offer.id ; Listing.status := UNDER_CONTRACT
    listing["status"] = "UNDER_CONTRACT"
    listing["accepted_offer_id"] = offer["id"]
    # 3. Other SUBMITTED offers → REJECTED ; their OPEN counters → WITHDRAWN
    reject_other_submitted_offers(listing["id"], offer["id"], now)
    # 4. Compute provisional net to seller on the offer
    offer["provisional_net_to_seller_cents"] = provisional_net_to_seller(offer, listing)
    # 5. Emit PROVISIONAL CommissionSplit
    emit_commission_split(listing, offer, "PROVISIONAL", now)
    # 6. Bump versions on the directly mutated rows
    bump_version(offer, now)
    bump_version(listing, now)


def close_listing_cascade(listing: dict, now: datetime) -> None:
    """Listing UNDER_CONTRACT → SOLD cascade (scaffold §1.2)."""
    accepted_id = listing.get("accepted_offer_id")
    accepted_offer = store.offers.get(accepted_id) if accepted_id else None

    listing["status"] = "SOLD"
    bump_version(listing, now)

    if accepted_offer is not None:
        buyer = store.buyers.get(accepted_offer["buyer_id"])
        if buyer is not None:
            buyer["status"] = "SOLD"
            bump_version(buyer, now)
        # Emit FINAL CommissionSplit
        emit_commission_split(listing, accepted_offer, "FINAL", now)

    # Cancel open showings
    cancel_open_showings_of_listing(listing["id"], now)

    # Retire lockbox (ARMED → RETIRED directly per scaffold)
    retire_lockbox_of_listing(listing["id"], now)


def withdraw_listing_cascade(listing: dict, now: datetime) -> None:
    """Listing ACTIVE → WITHDRAWN cascade."""
    listing["status"] = "WITHDRAWN"
    bump_version(listing, now)
    cancel_open_showings_of_listing(listing["id"], now)
    disarm_lockbox_of_listing(listing["id"], now)


def expire_listing_cascade(listing: dict, now: datetime) -> None:
    """Listing ACTIVE → EXPIRED cascade (driven by sweep)."""
    listing["status"] = "EXPIRED"
    bump_version(listing, now)
    cancel_open_showings_of_listing(listing["id"], now)
    # All SUBMITTED Offers → EXPIRED ; their OPEN counters → WITHDRAWN
    for o in store.offers.values():
        if o["listing_id"] == listing["id"] and o["status"] == "SUBMITTED":
            o["status"] = "EXPIRED"
            bump_version(o, now)
            withdraw_open_counters_of_offer(o["id"], now)
    # OPEN counters on any offer of this listing → EXPIRED  (per scaffold)
    for c in store.counters.values():
        offer = store.offers.get(c["offer_id"])
        if (
            c["status"] == "OPEN"
            and offer is not None
            and offer["listing_id"] == listing["id"]
        ):
            c["status"] = "EXPIRED"
    # Lockbox disarmed
    disarm_lockbox_of_listing(listing["id"], now)


def fail_contingency_cascade(
    contingency: dict,
    listing: dict,
    accepted_offer: dict,
    now: datetime,
) -> None:
    """Contingency PENDING → FAILED cascade (scaffold §1.2 / PRD §3.7).

    The triggering contingency is already FAILED before this is called.
    Cascade:
      - Accepted Offer.status := WITHDRAWN
      - All sibling PENDING contingencies on the same offer → FAILED
      - Listing.accepted_offer_id := null
      - Listing.status := ACTIVE
    """
    # Sibling PENDING contingencies on the same offer.
    for c in store.contingencies.values():
        if (
            c["offer_id"] == accepted_offer["id"]
            and c["status"] == "PENDING"
            and c["id"] != contingency["id"]
        ):
            c["status"] = "FAILED"
            bump_version(c, now)

    accepted_offer["status"] = "WITHDRAWN"
    bump_version(accepted_offer, now)

    listing["accepted_offer_id"] = None
    listing["status"] = "ACTIVE"
    bump_version(listing, now)
