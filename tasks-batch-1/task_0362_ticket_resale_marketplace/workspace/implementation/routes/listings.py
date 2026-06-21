from flask import Blueprint, request

import db
import clock
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, calc, recompute, seat_ops

bp = Blueprint("listings", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "Buyer", "TrustSafety")
SELLING_STATES = ("ON_SALE", "LAST_MINUTE")


@bp.post("/listings")
def create_listing():
    body = validate.get_json_body()
    event_id = validate.require_string(body, "event_id")
    seller_id = validate.require_string(body, "seller_id")
    section_id = validate.require_string(body, "section_id")
    delivery_method = validate.require_enum(body, "delivery_method", {"MOBILE_TRANSFER", "BARCODE_PDF"})
    ask_price_cents = validate.require_int(body, "ask_price_cents", minimum=1)
    pricing_mode = validate.require_enum(body, "pricing_mode", {"FIXED", "DYNAMIC"})
    split_rule = validate.require_enum(body, "split_rule", {"ANY", "PAIRS", "WHOLE"},
                                       required=False, default="ANY")
    dynamic_floor_cents = validate.require_int(body, "dynamic_floor_cents", required=False, minimum=0)

    user_id, role = get_user_context()
    require_role(role, ("Seller",))

    # existence, left-to-right: event -> seller -> section
    event = lookup.get_event(event_id)
    seller = lookup.get_seller(seller_id)
    section = lookup.get_section(section_id)

    # ownership: seller's listing must belong to the acting seller
    require_ownership(role, user_id, seller_id)

    # referential: section's venue must be the event's venue
    if section["venue_id"] != event["venue_id"]:
        raise err(errors.ERR_REFERENTIAL_MISMATCH, "Section does not belong to the event's venue")

    # fiscal: dynamic floor validity, then price cap
    if pricing_mode == "DYNAMIC":
        if dynamic_floor_cents is None or dynamic_floor_cents > ask_price_cents:
            raise err(errors.ERR_DYNAMIC_FLOOR_INVALID,
                      "DYNAMIC listing requires dynamic_floor_cents <= ask_price_cents")

    cap = calc.price_cap(section["face_value_cents"], event["price_cap_multiplier"])
    if ask_price_cents > cap:
        raise err(errors.ERR_PRICE_CAP_EXCEEDED, "ask_price_cents exceeds price cap")
    if pricing_mode == "DYNAMIC" and dynamic_floor_cents is not None and dynamic_floor_cents > cap:
        raise err(errors.ERR_PRICE_CAP_EXCEEDED, "dynamic_floor_cents exceeds price cap")

    listing = {
        "event_id": event_id,
        "seller_id": seller_id,
        "section_id": section_id,
        "status": "DRAFT",
        "delivery_method": delivery_method,
        "ask_price_cents": ask_price_cents,
        "pricing_mode": pricing_mode,
        "dynamic_floor_cents": dynamic_floor_cents if pricing_mode == "DYNAMIC" else None,
        "effective_price_cents": 0,
        "total_seat_count": 0,
        "available_seat_count": 0,
        "held_seat_count": 0,
        "split_rule": split_rule,
    }
    db.stamp_create(listing)
    # initial effective price computed from ask/floor against cap
    listing["effective_price_cents"] = calc.effective_listing_price(listing, section, event)
    db.listings[listing["id"]] = listing
    return response.object_response(serialize.public(listing), 201)


@bp.get("/listings/<listing_id>")
def get_listing(listing_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    listing = lookup.get_listing(listing_id)
    # DYNAMIC mode: refresh effective_price_cents on read (read-time projection)
    if listing["pricing_mode"] == "DYNAMIC":
        recompute.refresh_dynamic_price(listing)
    return response.object_response(serialize.public(listing), 200)


@bp.get("/listings")
def list_listings():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    event_id = request.args.get("event_id")
    seller_id = request.args.get("seller_id")
    section_id = request.args.get("section_id")
    records = list(db.listings.values())
    if event_id is not None:
        records = [l for l in records if l["event_id"] == event_id]
    if seller_id is not None:
        records = [l for l in records if l["seller_id"] == seller_id]
    if section_id is not None:
        records = [l for l in records if l["section_id"] == section_id]
    # refresh dynamic prices as read-time projection
    for l in records:
        if l["pricing_mode"] == "DYNAMIC":
            recompute.refresh_dynamic_price(l)
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/listings/<listing_id>/activate")
def activate(listing_id):
    user_id, role = get_user_context()
    require_role(role, ("Seller",))
    listing = lookup.get_listing(listing_id)
    require_ownership(role, user_id, listing["seller_id"])

    event = db.events.get(listing["event_id"])
    seller = db.sellers.get(listing["seller_id"])

    # state: listing must be DRAFT (FROZEN handled as frozen guard)
    if listing["status"] == "FROZEN":
        raise err(errors.ERR_LISTING_FROZEN, "Listing is frozen")
    if listing["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Listing cannot activate from %s" % listing["status"])

    # cross-entity state: event must be selling
    if event["status"] not in SELLING_STATES:
        raise err(errors.ERR_EVENT_NOT_SELLING, "Event is not selling")

    # state: must have at least one seat
    if listing["total_seat_count"] < 1:
        raise err(errors.ERR_INVALID_STATE, "Listing has no seats")

    # safety: RESTRICTED seller cannot activate
    if seller["trust_tier"] == "RESTRICTED":
        raise err(errors.ERR_SELLER_RESTRICTED, "Restricted seller cannot activate listings")

    listing["status"] = "ACTIVE"
    db.touch(listing)
    section = db.sections.get(listing["section_id"])
    listing["effective_price_cents"] = calc.effective_listing_price(listing, section, event)
    recompute.recompute_event(event)
    return response.object_response(serialize.public(listing), 200)


@bp.post("/listings/<listing_id>/delist")
def delist(listing_id):
    user_id, role = get_user_context()
    require_role(role, ("Seller",))
    listing = lookup.get_listing(listing_id)
    require_ownership(role, user_id, listing["seller_id"])

    if listing["status"] not in ("DRAFT", "ACTIVE"):
        raise err(errors.ERR_INVALID_STATE, "Listing cannot be delisted from %s" % listing["status"])

    listing["status"] = "DELISTED"
    db.touch(listing)
    for seat in seat_ops.seats_for_listing(listing["id"]):
        if seat["status"] == "AVAILABLE":
            seat_ops.set_status(seat, "VOID")
    recompute.recompute_listing(listing)
    event = db.events.get(listing["event_id"])
    if event is not None:
        recompute.recompute_event(event)
    return response.object_response(serialize.public(listing), 200)
