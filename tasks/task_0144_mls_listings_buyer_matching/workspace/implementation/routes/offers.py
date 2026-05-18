"""/listings/{listing_id}/offers* endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from errors import (
    err_counter_expired,
    err_forbidden_not_owner,
    err_invalid_offer_fiscal,
    err_invalid_state,
    err_listing_already_under_contract,
    err_not_found,
    err_offer_expired,
    err_offer_not_submitted,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_buyer_side_ownership,
    enforce_listing_side_ownership,
    get_buyer_or_404,
    get_json,
    get_listing_or_404,
    get_offer_in_listing_or_404,
    parse_pagination,
    parse_required_iso,
    sort_by_created_at,
)
from services.serializers import counter as serialize_counter
from services.serializers import offer as serialize_offer
from services.state_machine import (
    accept_offer_cascade,
    bump_version,
    withdraw_open_counters_of_offer,
)
from utils import new_uuid


bp = Blueprint("offers", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# POST /listings/{id}/offers — create new offer (round 1) OR rebound (round N+1)
# ─────────────────────────────────────────────────────────────────────────────


@bp.post("/listings/<listing_id>/offers")
@require_auth(["BuyerAgent"])
def create_offer(listing_id):
    body = get_json()
    listing = get_listing_or_404(listing_id)

    buyer_id = body.get("buyer_id")
    if not isinstance(buyer_id, str):
        raise err_invalid_offer_fiscal("buyer_id is required.")
    buyer = get_buyer_or_404(buyer_id)
    enforce_buyer_side_ownership(buyer)

    offer_price = body.get("offer_price_cents")
    if not isinstance(offer_price, int) or isinstance(offer_price, bool) or offer_price <= 0:
        raise err_invalid_offer_fiscal("offer_price_cents must be a positive integer.")
    earnest = body.get("earnest_money_cents")
    if not isinstance(earnest, int) or isinstance(earnest, bool) or earnest < 0:
        raise err_invalid_offer_fiscal(
            "earnest_money_cents must be a non-negative integer."
        )
    concessions = body.get("estimated_seller_concessions_cents", 0)
    if not isinstance(concessions, int) or isinstance(concessions, bool) or concessions < 0:
        raise err_invalid_offer_fiscal(
            "estimated_seller_concessions_cents must be a non-negative integer."
        )
    if earnest > offer_price:
        raise err_invalid_offer_fiscal(
            "earnest_money_cents must be <= offer_price_cents."
        )
    if concessions > offer_price:
        raise err_invalid_offer_fiscal(
            "estimated_seller_concessions_cents must be <= offer_price_cents."
        )

    expires_at = parse_required_iso(
        body, "expires_at", err_invalid_offer_fiscal("expires_at is required.")
    )
    now = store.now()
    if expires_at <= now:
        raise err_offer_expired("expires_at must be strictly in the future.")

    parent_counter_id = body.get("parent_counter_id")
    round_no = 1
    if parent_counter_id is not None:
        # Rebound path validation (also reachable through the dedicated /rebound endpoint).
        if not isinstance(parent_counter_id, str):
            raise err_invalid_state("parent_counter_id must be a string.")
        ctr = store.counters.get(parent_counter_id)
        if ctr is None:
            raise err_not_found("Counter not found.")
        parent_offer = store.offers.get(ctr["offer_id"])
        if parent_offer is None or parent_offer["listing_id"] != listing_id:
            raise err_not_found("Counter does not belong to this listing.")
        if ctr["status"] != "OPEN":
            raise err_invalid_state("Counter must be OPEN to rebound.")
        if now >= ctr["counter_expires_at"]:
            raise err_counter_expired()
        if parent_offer["status"] != "COUNTERED":
            raise err_invalid_state("Parent offer must be COUNTERED to rebound.")
        round_no = parent_offer["round_no"] + 1
        # Mark counter REBOUND.
        ctr["status"] = "REBOUND"

    offer = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "offer_price_cents": offer_price,
        "earnest_money_cents": earnest,
        "estimated_seller_concessions_cents": concessions,
        "round_no": round_no,
        "parent_counter_id": parent_counter_id,
        "status": "SUBMITTED",
        "expires_at": expires_at,
        "provisional_net_to_seller_cents": None,
    }
    store.offers[offer["id"]] = offer
    return success(serialize_offer(offer), 201)


# ─────────────────────────────────────────────────────────────────────────────
# GET /listings/{id}/offers
# ─────────────────────────────────────────────────────────────────────────────


@bp.get("/listings/<listing_id>/offers")
@require_auth(["ListingAgent", "MlsAdmin"])
def list_offers(listing_id):
    listing = get_listing_or_404(listing_id)
    if g.role == "ListingAgent":
        enforce_listing_side_ownership(listing)
    status = request.args.get("status")
    limit, offset = parse_pagination()
    rows = [o for o in store.offers.values() if o["listing_id"] == listing_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([serialize_offer(o) for o in page], limit, offset, total, 200)


# ─────────────────────────────────────────────────────────────────────────────
# POST .../accept
# ─────────────────────────────────────────────────────────────────────────────


@bp.post("/listings/<listing_id>/offers/<offer_id>/accept")
@require_auth(["ListingAgent"])
def accept_offer(listing_id, offer_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        offer = get_offer_in_listing_or_404(listing_id, offer_id)

        # Priority order (PRD §3.6):
        # General rule: any act on an offer that is no longer SUBMITTED
        # yields ERR_OFFER_NOT_SUBMITTED. The more specific
        # ERR_LISTING_ALREADY_UNDER_CONTRACT applies when the listing
        # has just transitioned to UNDER_CONTRACT via acceptance of a
        # SIBLING offer — i.e., this offer is NOT the listing's
        # accepted_offer_id. The accept-the-same-offer-twice case keeps
        # the generic ERR_OFFER_NOT_SUBMITTED.
        if (
            listing["status"] == "UNDER_CONTRACT"
            and listing.get("accepted_offer_id") != offer["id"]
        ):
            raise err_listing_already_under_contract()
        if offer["status"] != "SUBMITTED":
            raise err_offer_not_submitted()
        if listing["status"] != "ACTIVE":
            raise err_invalid_state(
                f"Listing must be ACTIVE to accept an offer (is {listing['status']})."
            )
        now = store.now()
        if offer["expires_at"] <= now:
            raise err_offer_expired()

        accept_offer_cascade(listing, offer, now)
    return success(serialize_offer(offer), 200)


# ─────────────────────────────────────────────────────────────────────────────
# POST .../reject
# ─────────────────────────────────────────────────────────────────────────────


@bp.post("/listings/<listing_id>/offers/<offer_id>/reject")
@require_auth(["ListingAgent"])
def reject_offer(listing_id, offer_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        offer = get_offer_in_listing_or_404(listing_id, offer_id)
        if offer["status"] != "SUBMITTED":
            raise err_offer_not_submitted()
        now = store.now()
        offer["status"] = "REJECTED"
        bump_version(offer, now)
        withdraw_open_counters_of_offer(offer["id"], now)
    return success(serialize_offer(offer), 200)


# ─────────────────────────────────────────────────────────────────────────────
# POST .../withdraw
# ─────────────────────────────────────────────────────────────────────────────


@bp.post("/listings/<listing_id>/offers/<offer_id>/withdraw")
@require_auth(["BuyerAgent"])
def withdraw_offer(listing_id, offer_id):
    with store.lock:
        listing = get_listing_or_404(listing_id)
        offer = get_offer_in_listing_or_404(listing_id, offer_id)
        buyer = store.buyers.get(offer["buyer_id"])
        if buyer is None:
            raise err_not_found("Buyer not found.")
        enforce_buyer_side_ownership(buyer)
        if offer["status"] != "SUBMITTED":
            raise err_offer_not_submitted()
        now = store.now()
        offer["status"] = "WITHDRAWN"
        bump_version(offer, now)
        withdraw_open_counters_of_offer(offer["id"], now)
    return success(serialize_offer(offer), 200)


# ─────────────────────────────────────────────────────────────────────────────
# POST .../counter
# ─────────────────────────────────────────────────────────────────────────────


@bp.post("/listings/<listing_id>/offers/<offer_id>/counter")
@require_auth(["ListingAgent"])
def counter_offer(listing_id, offer_id):
    body = get_json()
    with store.lock:
        listing = get_listing_or_404(listing_id)
        enforce_listing_side_ownership(listing)
        offer = get_offer_in_listing_or_404(listing_id, offer_id)
        if offer["status"] != "SUBMITTED":
            raise err_offer_not_submitted()
        if listing["status"] != "ACTIVE":
            raise err_invalid_state("Listing must be ACTIVE to counter.")
        now = store.now()
        if offer["expires_at"] <= now:
            raise err_offer_expired()

        cp = body.get("counter_price_cents")
        cc = body.get("counter_concessions_cents")
        if not isinstance(cp, int) or isinstance(cp, bool) or cp <= 0:
            raise err_invalid_state("counter_price_cents must be a positive integer.")
        if not isinstance(cc, int) or isinstance(cc, bool) or cc < 0:
            raise err_invalid_state(
                "counter_concessions_cents must be a non-negative integer."
            )
        cea = parse_required_iso(
            body, "counter_expires_at",
            err_invalid_state("counter_expires_at is required."),
        )
        if cea <= now:
            raise err_invalid_state("counter_expires_at must be in the future.")

        counter = {
            "id": new_uuid(),
            "created_at": now,
            "offer_id": offer["id"],
            "counter_price_cents": cp,
            "counter_concessions_cents": cc,
            "counter_expires_at": cea,
            "status": "OPEN",
        }
        store.counters[counter["id"]] = counter
        offer["status"] = "COUNTERED"
        bump_version(offer, now)
    return success(serialize_counter(counter), 201)


# ─────────────────────────────────────────────────────────────────────────────
# POST .../rebound
# ─────────────────────────────────────────────────────────────────────────────


@bp.post("/listings/<listing_id>/offers/<offer_id>/rebound")
@require_auth(["BuyerAgent"])
def rebound_offer(listing_id, offer_id):
    body = get_json()
    with store.lock:
        listing = get_listing_or_404(listing_id)
        parent_offer = get_offer_in_listing_or_404(listing_id, offer_id)
        buyer = store.buyers.get(parent_offer["buyer_id"])
        if buyer is None:
            raise err_not_found("Buyer not found.")
        enforce_buyer_side_ownership(buyer)

        if parent_offer["status"] != "COUNTERED":
            raise err_invalid_state(
                "Parent offer must be in COUNTERED status to rebound."
            )

        now = store.now()
        # Find the OPEN counter on this offer.
        open_counters = [
            c for c in store.counters.values()
            if c["offer_id"] == parent_offer["id"] and c["status"] == "OPEN"
        ]
        if not open_counters:
            # PRD §3.6: a rebound past the counter deadline is rejected
            # with ERR_COUNTER_EXPIRED — also applies when sweep has
            # already transitioned the counter from OPEN to EXPIRED.
            offer_counters = [
                c for c in store.counters.values()
                if c["offer_id"] == parent_offer["id"]
            ]
            offer_counters.sort(key=lambda c: c["created_at"])
            if offer_counters and offer_counters[-1]["status"] in ("EXPIRED",):
                raise err_counter_expired()
            if offer_counters and now >= offer_counters[-1]["counter_expires_at"]:
                raise err_counter_expired()
            raise err_invalid_state("No OPEN counter exists on this offer to rebound.")
        ctr = open_counters[0]
        if now >= ctr["counter_expires_at"]:
            raise err_counter_expired()

        # Validate the new offer fiscal fields.
        offer_price = body.get("offer_price_cents")
        if not isinstance(offer_price, int) or isinstance(offer_price, bool) or offer_price <= 0:
            raise err_invalid_offer_fiscal(
                "offer_price_cents must be a positive integer."
            )
        earnest = body.get("earnest_money_cents")
        if not isinstance(earnest, int) or isinstance(earnest, bool) or earnest < 0:
            raise err_invalid_offer_fiscal(
                "earnest_money_cents must be a non-negative integer."
            )
        concessions = body.get("estimated_seller_concessions_cents", 0)
        if not isinstance(concessions, int) or isinstance(concessions, bool) or concessions < 0:
            raise err_invalid_offer_fiscal(
                "estimated_seller_concessions_cents must be a non-negative integer."
            )
        if earnest > offer_price:
            raise err_invalid_offer_fiscal(
                "earnest_money_cents must be <= offer_price_cents."
            )
        if concessions > offer_price:
            raise err_invalid_offer_fiscal(
                "estimated_seller_concessions_cents must be <= offer_price_cents."
            )
        expires_at = parse_required_iso(
            body, "expires_at",
            err_invalid_offer_fiscal("expires_at is required."),
        )
        if expires_at <= now:
            raise err_offer_expired("expires_at must be strictly in the future.")

        # Mark the counter REBOUND, create new Offer at round_no + 1.
        ctr["status"] = "REBOUND"
        new_offer = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "listing_id": listing_id,
            "buyer_id": parent_offer["buyer_id"],
            "offer_price_cents": offer_price,
            "earnest_money_cents": earnest,
            "estimated_seller_concessions_cents": concessions,
            "round_no": parent_offer["round_no"] + 1,
            "parent_counter_id": ctr["id"],
            "status": "SUBMITTED",
            "expires_at": expires_at,
            "provisional_net_to_seller_cents": None,
        }
        store.offers[new_offer["id"]] = new_offer
    return success(serialize_offer(new_offer), 201)
