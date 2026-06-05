"""Offer submit/get/list, counter, accept, reject, withdraw + counters lookups."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import body, get_or_404, require_int, require_str
from middleware import authenticate
from response import ok, created, ok_list, parse_pagination, paginate
from serializers import serialize_offer, serialize_counter
from services.entities import make_offer, make_counter
from services.negotiation import offer_projection
from services.state import touch, accept_offer_cascade

bp = Blueprint("offers", __name__)

LIVE = ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED")
VALID_CONTINGENCIES = {"INSPECTION", "APPRAISAL", "FINANCING"}


@bp.post("/listings/<lid>/offers")
def submit_offer(lid):
    role, uid = authenticate({"BuyerAgent"})
    listing = get_or_404(db.listings, lid)
    data = body()
    buyer_id = require_str(data, "buyer_id")
    buyer_agent_id = require_str(data, "buyer_agent_id")
    initial_price = require_int(data, "initial_price_cents")
    earnest = require_int(data, "earnest_money_cents")
    requested = data.get("requested_contingencies", [])
    if requested is None:
        requested = []
    if not isinstance(requested, list) or any(c not in VALID_CONTINGENCIES for c in requested):
        raise err("ERR_VALIDATION", "invalid requested_contingencies")

    # FK existence
    buyer = get_or_404(db.buyers, buyer_id)
    agent = get_or_404(db.agents, buyer_agent_id)

    # ownership: acting agent == buyer_agent_id (buy side)
    if uid != buyer_agent_id:
        raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")

    # segregation: buyer_agent_id must not be the listing's listing_agent_id
    if buyer_agent_id == listing["listing_agent_id"]:
        raise err("ERR_DUAL_AGENCY_FORBIDDEN", "Agent cannot represent both sides")

    # state: listing must be ACTIVE to receive offers
    if listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing not ACTIVE")

    # suspended agent cannot submit
    if agent["status"] == "SUSPENDED":
        raise err("ERR_AGENT_SUSPENDED", "Agent is suspended")

    # budget guard
    if initial_price > buyer["max_budget_cents"]:
        raise err("ERR_OVER_BUDGET", "initial_price_cents exceeds buyer budget")

    # amount sanity
    if initial_price <= 0 or earnest < 0 or earnest > initial_price:
        raise err("ERR_INVALID_AMOUNT", "Invalid price or earnest money")

    rec = make_offer(lid, buyer_id, buyer_agent_id, initial_price, earnest, requested)
    return created(serialize_offer(rec))


@bp.get("/offers/<oid>")
def get_offer(oid):
    rec = get_or_404(db.offers, oid)
    return ok(serialize_offer(rec))


@bp.get("/listings/<lid>/offers")
def list_listing_offers(lid):
    get_or_404(db.listings, lid)
    limit, offset = parse_pagination()
    rows = [o for o in db.offers.values() if o["listing_id"] == lid]
    rows = _apply_offer_filters(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_offer(o) for o in page], total, limit, offset)


@bp.get("/offers")
def list_offers():
    limit, offset = parse_pagination()
    rows = list(db.offers.values())
    listing_id = request.args.get("listing_id")
    if listing_id:
        rows = [o for o in rows if o["listing_id"] == listing_id]
    rows = _apply_offer_filters(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_offer(o) for o in page], total, limit, offset)


def _apply_offer_filters(rows):
    buyer_agent_id = request.args.get("buyer_agent_id")
    buyer_id = request.args.get("buyer_id")
    status = request.args.get("status")
    if buyer_agent_id:
        rows = [o for o in rows if o["buyer_agent_id"] == buyer_agent_id]
    if buyer_id:
        rows = [o for o in rows if o["buyer_id"] == buyer_id]
    if status:
        rows = [o for o in rows if o["status"] == status]
    return rows


# --- Counter ---
@bp.post("/offers/<oid>/counter")
def counter_offer(oid):
    role, uid = authenticate({"ListingAgent", "BuyerAgent"})
    offer = get_or_404(db.offers, oid)
    listing = db.listings.get(offer["listing_id"])
    data = body()
    counter_price = require_int(data, "counter_price_cents")
    actor_agent_id = require_str(data, "actor_agent_id")
    get_or_404(db.agents, actor_agent_id)

    proj = offer_projection(offer)
    current_party = proj["current_party"]

    # Determine acting side from role. Seller side = ListingAgent, Buyer side = BuyerAgent.
    # Ownership (priority 4) -> state/INVALID_STATE (6) -> turn/NOT_YOUR_TURN (7).
    # A counter is "state-valid" whenever the offer is in a live negotiating state
    # {OPEN, SELLER_COUNTERED, BUYER_COUNTERED} and the listing is ACTIVE; whether it
    # is actually the acting side's move is then decided by current_party (turn gate).
    if role == "ListingAgent":
        if uid != listing["listing_agent_id"]:
            raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
        acting_party = "SELLER"
    else:  # BuyerAgent
        if uid != offer["buyer_agent_id"]:
            raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")
        acting_party = "BUYER"

    if listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing not ACTIVE")
    if offer["status"] not in ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED"):
        raise err("ERR_INVALID_STATE", "Offer not in a counter-able state")
    if current_party != acting_party:
        raise err("ERR_NOT_YOUR_TURN", "Not your turn")

    # suspended agent cannot counter
    actor = db.agents.get(actor_agent_id)
    if actor and actor["status"] == "SUSPENDED":
        raise err("ERR_AGENT_SUSPENDED", "Agent is suspended")

    if counter_price <= 0:
        raise err("ERR_INVALID_AMOUNT", "counter_price_cents must be positive")

    round_index = proj["round_count"] + 1
    rec = make_counter(oid, round_index, acting_party, counter_price, actor_agent_id)

    # flip offer status
    offer["status"] = "SELLER_COUNTERED" if acting_party == "SELLER" else "BUYER_COUNTERED"
    touch(offer)
    return created(serialize_counter(rec))


@bp.get("/offers/<oid>/counters")
def list_offer_counters(oid):
    get_or_404(db.offers, oid)
    limit, offset = parse_pagination()
    rows = [c for c in db.counter_rounds.values() if c["offer_id"] == oid]
    rows.sort(key=lambda c: c["round_index"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serialize_counter(c) for c in page], total, limit, offset)


@bp.get("/counters/<cid>")
def get_counter(cid):
    rec = get_or_404(db.counter_rounds, cid)
    return ok(serialize_counter(rec))


@bp.get("/counters")
def list_counters():
    limit, offset = parse_pagination()
    rows = list(db.counter_rounds.values())
    offer_id = request.args.get("offer_id")
    actor_agent_id = request.args.get("actor_agent_id")
    by_party = request.args.get("by_party")
    if offer_id:
        rows = [c for c in rows if c["offer_id"] == offer_id]
    if actor_agent_id:
        rows = [c for c in rows if c["actor_agent_id"] == actor_agent_id]
    if by_party:
        rows = [c for c in rows if c["by_party"] == by_party]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_counter(c) for c in page], total, limit, offset)


# --- Accept ---
@bp.post("/offers/<oid>/accept")
def accept_offer(oid):
    role, uid = authenticate({"ListingAgent", "BuyerAgent"})
    offer = get_or_404(db.offers, oid)
    listing = db.listings.get(offer["listing_id"])
    data = body()
    proj = offer_projection(offer)
    current_party = proj["current_party"]
    status = offer["status"]

    # Acceptance is governed by whose turn it is (current_party), matching the
    # negotiation turn semantics (PRD §3.6 / §2.10):
    #   OPEN, BUYER_COUNTERED -> current_party SELLER -> listing agent accepts
    #   SELLER_COUNTERED      -> current_party BUYER  -> buyer agent accepts
    # Ownership (priority 4) -> state/INVALID_STATE (6) -> turn/NOT_YOUR_TURN (7).
    acting_party = "SELLER" if role == "ListingAgent" else "BUYER"

    # Ownership check for the acting side.
    if acting_party == "SELLER":
        if uid != listing["listing_agent_id"]:
            raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    else:
        if uid != offer["buyer_agent_id"]:
            raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")

    # State: offer must be in a live negotiating state and listing ACTIVE.
    if status not in ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED"):
        raise err("ERR_INVALID_STATE", "Offer cannot be accepted from this state")
    if listing["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing not ACTIVE")

    # Turn: the accepting side must be the side whose turn it is.
    if current_party != acting_party:
        raise err("ERR_NOT_YOUR_TURN", "Not your turn")

    expected = require_int(data, "expected_listing_version")
    if expected != listing["version"]:
        raise err("ERR_STALE_VERSION", "expected_listing_version mismatch")

    accept_offer_cascade(listing, offer)
    return ok(serialize_offer(offer))


# --- Reject ---
@bp.post("/offers/<oid>/reject")
def reject_offer(oid):
    role, uid = authenticate({"ListingAgent", "BuyerAgent"})
    offer = get_or_404(db.offers, oid)
    listing = db.listings.get(offer["listing_id"])
    status = offer["status"]

    # OPEN -> listing agent; SELLER_COUNTERED -> buyer agent; BUYER_COUNTERED -> listing agent
    if status == "OPEN":
        if role != "ListingAgent":
            raise err("ERR_FORBIDDEN_ROLE", "Reject from OPEN is seller-side")
        if uid != listing["listing_agent_id"]:
            raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    elif status == "SELLER_COUNTERED":
        if role != "BuyerAgent":
            raise err("ERR_FORBIDDEN_ROLE", "Reject from SELLER_COUNTERED is buyer-side")
        if uid != offer["buyer_agent_id"]:
            raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")
    elif status == "BUYER_COUNTERED":
        if role != "ListingAgent":
            raise err("ERR_FORBIDDEN_ROLE", "Reject from BUYER_COUNTERED is seller-side")
        if uid != listing["listing_agent_id"]:
            raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    else:
        raise err("ERR_INVALID_STATE", "Offer cannot be rejected from this state")

    offer["status"] = "REJECTED"
    touch(offer)
    return ok(serialize_offer(offer))


# --- Withdraw ---
@bp.post("/offers/<oid>/withdraw")
def withdraw_offer(oid):
    role, uid = authenticate({"BuyerAgent"})
    offer = get_or_404(db.offers, oid)
    if uid != offer["buyer_agent_id"]:
        raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")
    if offer["status"] not in LIVE:
        raise err("ERR_INVALID_STATE", "Offer cannot be withdrawn from this state")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    return ok(serialize_offer(offer))
