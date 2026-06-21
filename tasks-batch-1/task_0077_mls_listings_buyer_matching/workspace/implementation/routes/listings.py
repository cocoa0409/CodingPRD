"""Listing lifecycle: create, get, list, activate, withdraw, close, net-sheet, ledger."""
from flask import Blueprint

from db import db
from errors import err
from helpers import body, get_or_404, require_int, require_number, require_str
from middleware import authenticate
from response import ok, created, ok_list, parse_pagination, paginate
from serializers import serialize_listing, serialize_ledger
from services.entities import make_listing
from services.money import net_to_seller
from services.negotiation import offer_projection
from services.state import (touch, listing_offers, listing_showings,
                            make_commission_ledger)

bp = Blueprint("listings", __name__)

TERMINAL = {"WITHDRAWN", "CLOSED"}


@bp.post("/listings")
def create_listing():
    role, uid = authenticate({"ListingAgent"})
    data = body()
    listing_agent_id = require_str(data, "listing_agent_id")
    address = require_str(data, "address")
    list_price = require_int(data, "list_price_cents")
    total_pct = require_number(data, "total_commission_pct", required=False, default=None)
    coop_pct = require_number(data, "coop_split_pct", required=False, default=None)

    # FK existence
    agent = get_or_404(db.agents, listing_agent_id)

    # ownership: acting agent must be the listing_agent_id
    if uid != listing_agent_id:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")

    # suspended agent cannot create listings
    if agent["status"] == "SUSPENDED":
        raise err("ERR_AGENT_SUSPENDED", "Agent is suspended")

    if list_price <= 0:
        raise err("ERR_VALIDATION", "list_price_cents must be positive")

    # commission defaults from brokerage
    brokerage = db.brokerages.get(agent["brokerage_id"])
    if total_pct is None:
        total_pct = brokerage["default_total_commission_pct"] if brokerage else None
    else:
        if not (0 < total_pct <= 0.10):
            raise err("ERR_VALIDATION", "total_commission_pct out of range")
    if coop_pct is None:
        coop_pct = brokerage["default_coop_split_pct"] if brokerage else None
    else:
        if not (0 <= coop_pct <= 1):
            raise err("ERR_VALIDATION", "coop_split_pct out of range")

    # address unique among non-terminal listings
    for l in db.listings.values():
        if l["address"] == address and l["status"] not in TERMINAL:
            raise err("ERR_DUPLICATE", "address already in use by a live listing")

    rec = make_listing(listing_agent_id, address, list_price, total_pct, coop_pct)
    return created(serialize_listing(rec))


@bp.get("/listings/<lid>")
def get_listing(lid):
    rec = get_or_404(db.listings, lid)
    return ok(serialize_listing(rec))


@bp.get("/listings")
def list_listings():
    limit, offset = parse_pagination()
    from flask import request
    rows = list(db.listings.values())
    laid = request.args.get("listing_agent_id")
    status = request.args.get("status")
    if laid:
        rows = [l for l in rows if l["listing_agent_id"] == laid]
    if status:
        rows = [l for l in rows if l["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_listing(l) for l in page], total, limit, offset)


@bp.post("/listings/<lid>/activate")
def activate_listing(lid):
    role, uid = authenticate({"ListingAgent"})
    listing = get_or_404(db.listings, lid)
    if uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    if listing["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Listing not in DRAFT")
    # require at least one INSTALLED lockbox
    has_installed = any(
        lb["listing_id"] == lid and lb["status"] == "INSTALLED"
        for lb in db.lockboxes.values()
    )
    if not has_installed:
        raise err("ERR_NO_LOCKBOX", "Listing has no installed lockbox")
    listing["status"] = "ACTIVE"
    touch(listing)
    return ok(serialize_listing(listing))


@bp.post("/listings/<lid>/withdraw")
def withdraw_listing(lid):
    role, uid = authenticate({"ListingAgent"})
    listing = get_or_404(db.listings, lid)
    if uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    if listing["status"] not in ("DRAFT", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Listing cannot be withdrawn from this state")

    if listing["status"] == "ACTIVE":
        for o in listing_offers(lid):
            if o["status"] in ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED"):
                o["status"] = "REJECTED"
                touch(o)
        for s in listing_showings(lid):
            if s["status"] in ("REQUESTED", "CONFIRMED"):
                s["status"] = "CANCELLED"
                touch(s)

    listing["status"] = "WITHDRAWN"
    touch(listing)
    return ok(serialize_listing(listing))


@bp.post("/listings/<lid>/close")
def close_listing(lid):
    role, uid = authenticate({"ListingAgent"})
    listing = get_or_404(db.listings, lid)
    data = body()
    if uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    if listing["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Listing not in PENDING")
    expected = require_int(data, "expected_listing_version")
    if expected != listing["version"]:
        raise err("ERR_STALE_VERSION", "expected_listing_version mismatch")

    accepted = db.offers.get(listing.get("accepted_offer_id"))
    listing["final_sale_price_cents"] = accepted["effective_price_cents"] if accepted else None
    listing["status"] = "CLOSED"

    # cancel residual showings
    for s in listing_showings(lid):
        if s["status"] in ("REQUESTED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)

    touch(listing)
    make_commission_ledger(listing)
    return ok(serialize_listing(listing))


@bp.get("/listings/<lid>/net-sheet")
def net_sheet(lid):
    role, uid = authenticate({"ListingAgent"})
    listing = get_or_404(db.listings, lid)
    if uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")

    basis = _provisional_basis(listing)
    if basis is None:
        return ok({
            "listing_id": lid,
            "basis_price_cents": None,
            "total_commission_cents": None,
            "net_to_seller_cents": None,
        })
    calc = net_to_seller(basis, listing["total_commission_pct"])
    return ok({
        "listing_id": lid,
        "basis_price_cents": basis,
        "total_commission_cents": calc["total_commission_cents"],
        "net_to_seller_cents": calc["net_to_seller_cents"],
    })


def _provisional_basis(listing):
    """Leading live offer's current_price_cents (highest, tie-break earliest created)."""
    offers = listing_offers(listing["id"])
    accepted = [o for o in offers if o["status"] == "ACCEPTED"]
    if accepted:
        # provisional variant uses the leading live offer; but an accepted offer
        # means UNDER_CONTRACT — use its current (effective) price as the basis.
        o = accepted[0]
        return offer_projection(o)["current_price_cents"]
    live = [o for o in offers if o["status"] in ("OPEN", "SELLER_COUNTERED", "BUYER_COUNTERED")]
    if not live:
        return None
    best = None
    best_price = None
    for o in live:
        price = offer_projection(o)["current_price_cents"]
        if best is None or price > best_price or (
            price == best_price and (o["created_at"], o["_seq"]) < (best["created_at"], best["_seq"])
        ):
            best = o
            best_price = price
    return best_price


@bp.get("/listings/<lid>/commission-ledger")
def get_commission_ledger(lid):
    get_or_404(db.listings, lid)
    limit, offset = parse_pagination()
    rows = [l for l in db.commission_ledgers.values() if l["listing_id"] == lid]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_ledger(l) for l in page], total, limit, offset)
