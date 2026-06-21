"""ResaleListing routes (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
    ERR_FAN_FLAGGED,
    ERR_FAN_NOT_VERIFIED,
    ERR_SELF_DEALING,
    ERR_RESALE_CAP_EXCEEDED,
    ERR_STALE_VERSION,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, require_int, sorted_by_creation
from services import calculations

bp = Blueprint("resale_listings", __name__)


@bp.post("/resale-listings")
def create_listing():
    require_auth(["Fan"])()
    body = get_json_body()
    ticket_id = require_str(body, "ticket_id")
    seller_fan_id = require_str(body, "seller_fan_id")
    list_price_cents = require_int(body, "list_price_cents")

    ticket = get_or_404(db.tickets, ticket_id, "Ticket")
    seller = get_or_404(db.fans, seller_fan_id, "Fan")

    if list_price_cents <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "list_price_cents must be > 0")

    # ownership: acting fan == seller; seller holds ticket
    if g.user_id != seller_fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the seller")
    if ticket.get("holder_fan_id") != seller_fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Seller does not hold this ticket")

    # state: HELD + VALID
    if ticket["holding_status"] != "HELD" or ticket["entry_status"] != "VALID":
        raise APIError(ERR_INVALID_STATE, 409, "Ticket not HELD/VALID")

    # priority 6: flag bar
    if seller["verification_status"] == "FLAGGED":
        raise APIError(ERR_FAN_FLAGGED, 403, "Fan is flagged")
    # priority 9: verified
    if seller["verification_status"] != "VERIFIED":
        raise APIError(ERR_FAN_NOT_VERIFIED, 422, "Fan is not verified")

    # priority 11: resale price cap
    event = db.events.get(ticket.get("event_id"))
    if event is not None:
        cap = calculations.resale_price_cap(event)
        if list_price_cents > cap:
            raise APIError(ERR_RESALE_CAP_EXCEEDED, 422, "Resale price cap exceeded")

    listing = db.stamp_common(
        {
            "ticket_id": ticket_id,
            "seller_fan_id": seller_fan_id,
            "list_price_cents": list_price_cents,
            "buyer_fan_id": None,
            "status": "OPEN",
        }
    )
    db.resale_listings[listing["id"]] = listing

    ticket["holding_status"] = "LISTED"
    db.bump(ticket)
    return ok_object(listing, 201)


@bp.post("/resale-listings/<lid>/buy")
def buy_listing(lid):
    require_auth(["Fan"])()
    listing = get_or_404(db.resale_listings, lid, "ResaleListing")
    body = get_json_body()
    buyer_fan_id = require_str(body, "buyer_fan_id")
    buyer = get_or_404(db.fans, buyer_fan_id, "Fan")

    # acting fan must be the named buyer
    if g.user_id != buyer_fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Acting fan is not the buyer")

    # state: listing OPEN
    if listing["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Listing not OPEN")

    # priority 6: flag bar (buyer)
    if buyer["verification_status"] == "FLAGGED":
        raise APIError(ERR_FAN_FLAGGED, 403, "Fan is flagged")
    # priority 9: verified (buyer)
    if buyer["verification_status"] != "VERIFIED":
        raise APIError(ERR_FAN_NOT_VERIFIED, 422, "Buyer is not verified")
    # priority 10: self-dealing
    if buyer_fan_id == listing["seller_fan_id"]:
        raise APIError(ERR_SELF_DEALING, 422, "buyer equals seller")

    # priority 17: OCC
    expected = body.get("expected_resalelisting_version")
    if expected is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing expected_resalelisting_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_resalelisting_version must be an integer")
    if expected != listing["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "Stale listing version")

    listing["status"] = "SOLD"
    listing["buyer_fan_id"] = buyer_fan_id
    db.bump(listing)

    ticket = db.tickets.get(listing["ticket_id"])
    if ticket is not None:
        ticket["holder_fan_id"] = buyer_fan_id
        ticket["holding_status"] = "HELD"
        db.bump(ticket)
    return ok_object(listing, 200)


@bp.post("/resale-listings/<lid>/cancel")
def cancel_listing(lid):
    require_auth(["Fan"])()
    listing = get_or_404(db.resale_listings, lid, "ResaleListing")

    if g.user_id != listing["seller_fan_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the seller")
    if listing["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Listing not OPEN")

    listing["status"] = "CANCELLED"
    db.bump(listing)
    ticket = db.tickets.get(listing["ticket_id"])
    if ticket is not None:
        ticket["holding_status"] = "HELD"
        db.bump(ticket)
    return ok_object(listing, 200)


@bp.get("/resale-listings/<lid>")
def get_listing(lid):
    require_auth(["Fan", "PromoterAdmin"])()
    listing = get_or_404(db.resale_listings, lid, "ResaleListing")
    return ok_object(listing, 200)


@bp.get("/resale-listings")
def list_listings():
    require_auth(["Anonymous", "Fan", "PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    ticket_id = request.args.get("ticket_id")
    seller_fan_id = request.args.get("seller_fan_id")
    buyer_fan_id = request.args.get("buyer_fan_id")
    status = request.args.get("status")
    items = list(db.resale_listings.values())
    if ticket_id is not None:
        items = [l for l in items if l.get("ticket_id") == ticket_id]
    if seller_fan_id is not None:
        items = [l for l in items if l.get("seller_fan_id") == seller_fan_id]
    if buyer_fan_id is not None:
        items = [l for l in items if l.get("buyer_fan_id") == buyer_fan_id]
    if status is not None:
        items = [l for l in items if l.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
