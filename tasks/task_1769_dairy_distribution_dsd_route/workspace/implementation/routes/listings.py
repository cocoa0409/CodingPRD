"""RouteSaleListing endpoints: create, publish (valuation snapshot), offer cycle,
withdraw, approve-transfer (territory ownership handoff)."""

from flask import Blueprint, request

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int,
    base_fields, paginate, err, touch, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_ROUTE_NOT_FOUND, ERR_LISTING_NOT_FOUND,
    ERR_DISTRIBUTOR_NOT_FOUND, ERR_OWNERSHIP_MISMATCH,
    ERR_ROUTE_NOT_ACTIVE, ERR_LISTING_NOT_ACTIONABLE,
    ERR_LISTING_NOT_OPEN_FOR_OFFER, ERR_LISTING_NOT_UNDER_CONTRACT,
    ERR_SELF_DEALING, ERR_ROUTE_HAS_OPEN_ORDERS,
)
from serializers import serialize_listing
from services import territory_value

bp = Blueprint("route_sale_listings", __name__)

NON_TERMINAL = {"DRAFT", "LISTED", "OFFER_PENDING", "UNDER_CONTRACT"}


def get_listing_or_404(listing_id):
    l = DB.route_sale_listings.get(listing_id)
    if l is None:
        raise err(ERR_LISTING_NOT_FOUND, "RouteSaleListing id not found")
    return l


def seller_check(user_id, listing):
    if listing["seller_distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller is not the listing's seller")


@bp.post("/dairy/route-sale-listings")
def create_listing():
    user_id, _role = require_role("DistributorOwner")
    body = get_json_body()
    check_unknown_fields(body, {"route_id", "asking_price_cents", "trailing_weeks"})
    require_fields(body, ["route_id", "asking_price_cents"])
    route = DB.routes.get(body["route_id"])
    if route is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    if route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Route must be owned by the caller")
    asking = opt_int(body, "asking_price_cents", ge=0)
    trailing = opt_int(body, "trailing_weeks", gt=0)
    if trailing is None:
        trailing = 12
    clash = any(
        l["route_id"] == route["id"] and l["status"] in NON_TERMINAL
        for l in DB.route_sale_listings.values()
    )
    if clash:
        raise err(ERR_INVALID_REQUEST,
                  "Route already sits on a non-terminal listing")
    l = base_fields()
    l.update({
        "route_id": route["id"],
        "seller_distributor_id": user_id,
        "asking_price_cents": asking,
        "trailing_weeks": trailing,
        "territory_value_cents": None,
        "buyer_distributor_id": None,
        "offer_price_cents": None,
        "status": "DRAFT",
    })
    DB.route_sale_listings[l["id"]] = l
    return success_object(serialize_listing(l), status=201)


@bp.get("/dairy/route-sale-listings/<listingId>")
def get_listing(listingId):
    require_any()
    return success_object(serialize_listing(get_listing_or_404(listingId)))


@bp.get("/dairy/route-sale-listings")
def list_listings():
    require_any()
    items = list(DB.route_sale_listings.values())
    for param, field in (("route_id", "route_id"),
                         ("seller_distributor_id", "seller_distributor_id"),
                         ("buyer_distributor_id", "buyer_distributor_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[field] == v]
    items.sort(key=lambda l: l["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_listing(l) for l in page], limit, offset, total)


@bp.post("/dairy/route-sale-listings/<listingId>/publish")
def publish_listing(listingId):
    user_id, _role = require_role("DistributorOwner")
    l = get_listing_or_404(listingId)
    seller_check(user_id, l)
    if l["status"] != "DRAFT":
        raise err(ERR_LISTING_NOT_ACTIONABLE, "Publish requires a DRAFT listing")
    route = DB.routes.get(l["route_id"])
    if route is None or route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route must be ACTIVE to publish")
    l["territory_value_cents"] = territory_value(l["route_id"], l["trailing_weeks"])
    l["status"] = "LISTED"
    touch(l)
    return success_object(serialize_listing(l))


@bp.post("/dairy/route-sale-listings/<listingId>/submit-offer")
def submit_offer(listingId):
    user_id, _role = require_role("DistributorOwner")
    l = get_listing_or_404(listingId)
    body = get_json_body()
    check_unknown_fields(body, {"buyer_distributor_id", "offer_price_cents"})
    require_fields(body, ["buyer_distributor_id", "offer_price_cents"])
    if body["buyer_distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH,
                  "buyer_distributor_id must equal the caller's X-User-ID")
    buyer = DB.distributors.get(body["buyer_distributor_id"])
    if buyer is None:
        raise err(ERR_DISTRIBUTOR_NOT_FOUND, "Buyer distributor id not found")
    offer = opt_int(body, "offer_price_cents", ge=0)
    if l["status"] != "LISTED":
        raise err(ERR_LISTING_NOT_OPEN_FOR_OFFER,
                  "Submit-offer requires a LISTED listing")
    route = DB.routes.get(l["route_id"])
    if route is None or route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Route must remain ACTIVE for offers")
    if buyer["id"] == l["seller_distributor_id"]:
        raise err(ERR_SELF_DEALING, "Buyer may not be the seller")
    l["status"] = "OFFER_PENDING"
    l["buyer_distributor_id"] = buyer["id"]
    l["offer_price_cents"] = offer
    touch(l)
    return success_object(serialize_listing(l))


@bp.post("/dairy/route-sale-listings/<listingId>/accept-offer")
def accept_offer(listingId):
    user_id, _role = require_role("DistributorOwner")
    l = get_listing_or_404(listingId)
    seller_check(user_id, l)
    if l["status"] != "OFFER_PENDING":
        raise err(ERR_LISTING_NOT_ACTIONABLE, "Accept requires an OFFER_PENDING listing")
    apply_changes(l, {"status": "UNDER_CONTRACT"})
    return success_object(serialize_listing(l))


@bp.post("/dairy/route-sale-listings/<listingId>/reject-offer")
def reject_offer(listingId):
    user_id, _role = require_role("DistributorOwner")
    l = get_listing_or_404(listingId)
    seller_check(user_id, l)
    if l["status"] != "OFFER_PENDING":
        raise err(ERR_LISTING_NOT_ACTIONABLE, "Reject requires an OFFER_PENDING listing")
    l["status"] = "LISTED"
    l["buyer_distributor_id"] = None
    l["offer_price_cents"] = None
    touch(l)
    return success_object(serialize_listing(l))


@bp.post("/dairy/route-sale-listings/<listingId>/withdraw")
def withdraw_listing(listingId):
    user_id, _role = require_role("DistributorOwner")
    l = get_listing_or_404(listingId)
    seller_check(user_id, l)
    if l["status"] not in ("LISTED", "OFFER_PENDING"):
        raise err(ERR_LISTING_NOT_ACTIONABLE,
                  "Withdraw requires a LISTED or OFFER_PENDING listing")
    l["status"] = "WITHDRAWN"
    l["buyer_distributor_id"] = None
    l["offer_price_cents"] = None
    touch(l)
    return success_object(serialize_listing(l))


@bp.post("/dairy/route-sale-listings/<listingId>/approve-transfer")
def approve_transfer(listingId):
    require_role("TerritoryManager")
    l = get_listing_or_404(listingId)
    if l["status"] != "UNDER_CONTRACT":
        raise err(ERR_LISTING_NOT_UNDER_CONTRACT,
                  "Approve-transfer requires an UNDER_CONTRACT listing")
    route = DB.routes.get(l["route_id"])
    route_store_ids = {
        s["id"] for s in DB.stores.values() if s["route_id"] == l["route_id"]
    }
    open_orders = any(
        o["store_id"] in route_store_ids
        and o["fulfillment_status"] in ("PLANNED", "CONFIRMED")
        for o in DB.orders.values()
    )
    if open_orders:
        raise err(ERR_ROUTE_HAS_OPEN_ORDERS,
                  "Route has orders in PLANNED or CONFIRMED")
    l["status"] = "CLOSED"
    touch(l)
    if route is not None:
        route["distributor_id"] = l["buyer_distributor_id"]
        touch(route)  # ownership handoff increments route.version
    return success_object(serialize_listing(l))
