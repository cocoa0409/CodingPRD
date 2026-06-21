"""Listing endpoints (PRD §3.2, §3.3, §3.7)."""
from flask import Blueprint, request

import constants as C
from db import store
from domain import (
    touch, alert_fan_out, listing_ttl_end, expire_listing, remove_listing,
)
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import listing_out, offer_out, flag_out, conversation_out, alert_out
import validate as V

bp = Blueprint("listings", __name__)


def _find_listing(listing_id):
    l = store.listings.get(listing_id)
    if l is None:
        raise err("ERR_NOT_FOUND", "Listing not found.")
    return l


def _check_floor_relationship(min_floor, ask):
    # floor must be >= 1 and <= ask (§3.2).
    if min_floor < 1 or min_floor > ask:
        raise err("ERR_FLOOR_ABOVE_ASK", "Floor must be between 1 and the ask price.")


def _check_category_cap(category, ask):
    # ask must not exceed a non-zero category cap (§3.2).
    cap = category["max_price_cents"]
    if cap != 0 and ask > cap:
        raise err("ERR_PRICE_EXCEEDS_CATEGORY_CAP", "Ask exceeds category price cap.")


@bp.route("/listings", methods=["POST"])
def create_listing():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER})
    body = get_json_body()

    seller_id = V.require_str(body, "seller_id")
    category_slug = V.require_str(body, "category_slug")
    title = V.require_str(body, "title", max_len=120)
    description = V.require_str(body, "description", allow_empty=True)
    ask = V.require_int(body, "ask_price_cents", minimum=1)
    min_floor = V.require_int(body, "min_acceptable_price_cents", minimum=1)

    # Ownership: the acting seller must be the seller_id (§2.1).
    if user_id != seller_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting seller is not the listing owner.")

    # Existence of FKs, left to right (§2.5).
    seller = store.members.get(seller_id)
    if seller is None:
        raise err("ERR_NOT_FOUND", "Seller not found.")
    category = store.categories.get(category_slug)
    if category is None:
        raise err("ERR_NOT_FOUND", "Category not found.")

    # Category cap (§3.2) then floor relationship (§3.2).
    _check_category_cap(category, ask)
    _check_floor_relationship(min_floor, ask)

    now = store.now()
    lid = store.new_id()
    rec = {
        "id": lid,
        "seller_id": seller_id,
        "category_slug": category_slug,
        "title": title,
        "description": description,
        "ask_price_cents": ask,
        "min_acceptable_price_cents": min_floor,
        "publication_status": "DRAFT",
        "sale_status": "AVAILABLE",
        "expires_at": None,
        "renewal_count": 0,
        "open_offer_count": 0,
        "active_flag_count": 0,
        "accepted_offer_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.listings[lid] = rec
    return object_response(listing_out(rec, role, user_id), 201)


@bp.route("/listings", methods=["GET"])
def list_listings():
    _, role = auth_context(require_auth=False)
    viewer_id = request.headers.get("X-User-ID")
    limit, offset = parse_pagination(request.args)
    recs = list(store.listings.values())

    seller_id = request.args.get("seller_id")
    if seller_id is not None:
        recs = [l for l in recs if l["seller_id"] == seller_id]
    category_slug = request.args.get("category_slug")
    if category_slug is not None:
        recs = [l for l in recs if l["category_slug"] == category_slug]
    pub = request.args.get("publication_status")
    if pub is not None:
        recs = [l for l in recs if l["publication_status"] == pub]
    sale = request.args.get("sale_status")
    if sale is not None:
        recs = [l for l in recs if l["sale_status"] == sale]
    accepted = request.args.get("accepted_offer_id")
    if accepted is not None:
        recs = [l for l in recs if l["accepted_offer_id"] == accepted]
    if "max_price_cents" in request.args:
        try:
            cap = int(request.args.get("max_price_cents"))
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "max_price_cents must be an integer.")
        recs = [l for l in recs if l["ask_price_cents"] <= cap]
    keyword = request.args.get("keyword")
    if keyword is not None:
        kw = keyword.lower()
        recs = [l for l in recs if kw in l["title"].lower()]

    return paginate_and_respond(
        recs, limit, offset, lambda r: listing_out(r, role, viewer_id)
    )


@bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    _, role = auth_context(require_auth=False)
    viewer_id = request.headers.get("X-User-ID")
    l = _find_listing(listing_id)
    return object_response(listing_out(l, role, viewer_id))


@bp.route("/listings/<listing_id>", methods=["PATCH"])
def edit_listing(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER})
    l = _find_listing(listing_id)
    if user_id != l["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting seller is not the listing owner.")
    body = get_json_body()

    new_title = V.optional_str(body, "title", default=None, max_len=120, allow_empty=False)
    new_desc = V.optional_str(body, "description", default=None, allow_empty=True)
    new_ask = V.optional_int(body, "ask_price_cents", minimum=1, default=None)
    new_floor = V.optional_int(body, "min_acceptable_price_cents", minimum=1, default=None)

    ask = new_ask if new_ask is not None else l["ask_price_cents"]
    floor = new_floor if new_floor is not None else l["min_acceptable_price_cents"]

    # Re-check category cap and floor relationship (§3.2).
    category = store.categories.get(l["category_slug"])
    if category is not None:
        _check_category_cap(category, ask)
    _check_floor_relationship(floor, ask)

    if new_title is not None:
        l["title"] = new_title
    if new_desc is not None:
        l["description"] = new_desc
    if new_ask is not None:
        l["ask_price_cents"] = new_ask
    if new_floor is not None:
        l["min_acceptable_price_cents"] = new_floor
    touch(l)
    return object_response(listing_out(l, role, user_id))


@bp.route("/listings/<listing_id>/publish", methods=["POST"])
def publish_listing(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER})
    l = _find_listing(listing_id)
    if user_id != l["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting seller is not the listing owner.")
    # State (§2.8 priority 5): must be DRAFT.
    if l["publication_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Listing is not DRAFT.")
    seller = store.members.get(l["seller_id"])
    # Member standing (priority 7).
    if seller is None or seller["status"] != "ACTIVE":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Seller is not ACTIVE.")
    category = store.categories.get(l["category_slug"])
    # Phone-verification gating (priority 9).
    if category is not None and category["requires_phone_verified_seller"] and not seller["phone_verified"]:
        raise err("ERR_SELLER_NOT_PHONE_VERIFIED", "Seller is not phone-verified.")
    # Active-listing cap (priority 14).
    if seller["active_listing_count"] >= C.MAX_ACTIVE_LISTINGS:
        raise err("ERR_ACTIVE_LISTING_LIMIT", "Seller active-listing limit reached.")
    # Category price cap (priority 16).
    if category is not None:
        _check_category_cap(category, l["ask_price_cents"])

    l["publication_status"] = "ACTIVE"
    l["expires_at"] = listing_ttl_end()
    seller["active_listing_count"] += 1
    touch(l)
    # Alert fan-out (§3.8).
    alert_fan_out(l)
    return object_response(listing_out(l, role, user_id))


@bp.route("/listings/<listing_id>/renew", methods=["POST"])
def renew_listing(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER})
    l = _find_listing(listing_id)
    if user_id != l["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting seller is not the listing owner.")
    pub = l["publication_status"]
    # State: renew defined from EXPIRED or ACTIVE (§3.3).
    if pub not in ("EXPIRED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Listing cannot be renewed from current state.")
    if l["sale_status"] == "SOLD":
        raise err("ERR_INVALID_STATE", "Sold listing cannot be renewed.")
    seller = store.members.get(l["seller_id"])

    if pub == "EXPIRED":
        # Member standing (priority 7).
        if seller is None or seller["status"] != "ACTIVE":
            raise err("ERR_MEMBER_NOT_ACTIVE", "Seller is not ACTIVE.")
        # Active-listing cap (priority 14).
        if seller["active_listing_count"] >= C.MAX_ACTIVE_LISTINGS:
            raise err("ERR_ACTIVE_LISTING_LIMIT", "Seller active-listing limit reached.")
        # Renewal cap (priority 15).
        if l["renewal_count"] >= C.MAX_RENEWALS:
            raise err("ERR_MAX_RENEWALS_REACHED", "Renewal cap reached.")
        l["publication_status"] = "ACTIVE"
        l["expires_at"] = listing_ttl_end()
        l["renewal_count"] += 1
        seller["active_listing_count"] += 1
    else:  # ACTIVE in-place extension
        if seller is None or seller["status"] != "ACTIVE":
            raise err("ERR_MEMBER_NOT_ACTIVE", "Seller is not ACTIVE.")
        if l["renewal_count"] >= C.MAX_RENEWALS:
            raise err("ERR_MAX_RENEWALS_REACHED", "Renewal cap reached.")
        l["expires_at"] = listing_ttl_end()
        l["renewal_count"] += 1
        # active_listing_count unchanged (already counted, §3.3).
    touch(l)
    return object_response(listing_out(l, role, user_id))


@bp.route("/listings/<listing_id>/expire", methods=["POST"])
def force_expire_listing(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_PLATFORM_ADMIN})
    l = _find_listing(listing_id)
    # Seller-actor ownership; PlatformAdmin is opaque (§2.1).
    if role == C.ROLE_SELLER and user_id != l["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting seller is not the listing owner.")
    # Expiry defined only from ACTIVE (§3.3).
    if l["publication_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Listing is not ACTIVE.")
    expire_listing(l)
    return object_response(listing_out(l, role, user_id))


@bp.route("/listings/<listing_id>/remove", methods=["POST"])
def remove_listing_endpoint(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_MODERATOR})
    l = _find_listing(listing_id)
    # Seller-actor ownership; Moderator is opaque (§2.1).
    if role == C.ROLE_SELLER and user_id != l["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting seller is not the listing owner.")
    # Remove defined from DRAFT/ACTIVE/EXPIRED (not REMOVED) (§3.7).
    if l["publication_status"] not in ("DRAFT", "ACTIVE", "EXPIRED"):
        raise err("ERR_INVALID_STATE", "Listing cannot be removed from current state.")
    remove_listing(l)
    return object_response(listing_out(l, role, user_id))


# --------------------- nested reads on listings ---------------------

@bp.route("/listings/<listing_id>/offers", methods=["GET"])
def list_listing_offers(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_listing(listing_id)
    limit, offset = parse_pagination(request.args)
    recs = [o for o in store.offers.values() if o["listing_id"] == listing_id]
    status = request.args.get("status")
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return paginate_and_respond(recs, limit, offset, offer_out)


@bp.route("/listings/<listing_id>/flags", methods=["GET"])
def list_listing_flags(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_listing(listing_id)
    limit, offset = parse_pagination(request.args)
    recs = [
        f for f in store.flags.values()
        if f["target_type"] == "LISTING" and f["target_listing_id"] == listing_id
    ]
    status = request.args.get("status")
    if status is not None:
        recs = [f for f in recs if f["status"] == status]
    return paginate_and_respond(recs, limit, offset, flag_out)


@bp.route("/listings/<listing_id>/conversations", methods=["GET"])
def list_listing_conversations(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_listing(listing_id)
    limit, offset = parse_pagination(request.args)
    recs = [c for c in store.conversations.values() if c["listing_id"] == listing_id]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate_and_respond(recs, limit, offset, conversation_out)


@bp.route("/listings/<listing_id>/alerts", methods=["GET"])
def list_listing_alerts(listing_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_PLATFORM_ADMIN})
    _find_listing(listing_id)
    limit, offset = parse_pagination(request.args)
    recs = [a for a in store.alerts.values() if a["listing_id"] == listing_id]
    return paginate_and_respond(recs, limit, offset, alert_out)
