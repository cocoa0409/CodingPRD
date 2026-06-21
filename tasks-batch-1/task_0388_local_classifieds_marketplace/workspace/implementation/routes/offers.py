"""Offer endpoints and the negotiation loop (PRD §3.5)."""
from flask import Blueprint, request

import constants as C
from db import store
from domain import touch, offer_ttl_end
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import offer_out, meetup_out
import validate as V

bp = Blueprint("offers", __name__)


def _find_offer(offer_id):
    o = store.offers.get(offer_id)
    if o is None:
        raise err("ERR_NOT_FOUND", "Offer not found.")
    return o


def _actor_side(offer, user_id):
    """Resolve which negotiation side the acting user is, by matching X-User-ID
    against the offer's buyer_id/seller_id. Non-participant -> NOT_RESOURCE_OWNER
    (§2.1: offer ownership compares X-User-ID to buyer_id or seller_id)."""
    if user_id == offer["buyer_id"]:
        return "BUYER"
    if user_id == offer["seller_id"]:
        return "SELLER"
    raise err("ERR_NOT_RESOURCE_OWNER", "Acting member is not a party to this offer.")


@bp.route("/offers", methods=["POST"])
def create_offer():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_BUYER})
    body = get_json_body()

    conversation_id = V.require_str(body, "conversation_id")
    amount = V.require_int(body, "amount_cents", minimum=1)

    # Existence (§2.5).
    conv = store.conversations.get(conversation_id)
    if conv is None:
        raise err("ERR_NOT_FOUND", "Conversation not found.")

    # Acting buyer must be the conversation's buyer (ownership, §2.1).
    if user_id != conv["buyer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting buyer is not the conversation buyer.")

    listing = store.listings.get(conv["listing_id"])
    if listing is None:
        raise err("ERR_NOT_FOUND", "Listing not found.")

    buyer = store.members.get(conv["buyer_id"])
    # Acting member standing (priority 7): not BANNED (§1.4).
    if buyer is not None and buyer["status"] == "BANNED":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Buyer is not active.")

    # Participant check (priority 17) — buyer is by construction a participant,
    # but enforce defensively.
    if user_id != conv["buyer_id"] and user_id != conv["seller_id"]:
        raise err("ERR_NOT_CONVERSATION_PARTICIPANT", "Not a conversation participant.")

    # Self-trade ban (priority 18).
    if conv["buyer_id"] == listing["seller_id"]:
        raise err("ERR_CANNOT_TRADE_OWN_LISTING", "Cannot trade on own listing.")

    now = store.now()
    oid = store.new_id()
    rec = {
        "id": oid,
        "conversation_id": conversation_id,
        "listing_id": conv["listing_id"],
        "buyer_id": conv["buyer_id"],
        "seller_id": conv["seller_id"],
        "amount_cents": amount,
        "last_actor_side": "BUYER",
        "round_count": 0,
        "status": "PROPOSED",
        "expires_at": offer_ttl_end(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.offers[oid] = rec

    # Floor auto-reject (§3.5, compute_min_floor_autoreject): buyer amount strictly
    # below the floor is created then immediately REJECTED; never net-enters the
    # open set (open_offer_count unchanged).
    if amount < listing["min_acceptable_price_cents"]:
        rec["status"] = "REJECTED"
        rec["expires_at"] = None
    else:
        # A fresh proposal adds 1 to the listing's open_offer_count (§3.5). This
        # denormalized-counter reconciliation is NOT a listing-version-incrementing
        # operation: PRD enumerates listing version bumps only at edit/reprice
        # (§3.2), publish/expiry/renewal (§3.3), acceptance (§3.5), and removal
        # (§3.7). The OCC narrative (§2.7) requires the listing version to advance
        # only on accept, so offer creation must leave it unchanged.
        listing["open_offer_count"] += 1

    return object_response(offer_out(rec), 201)


@bp.route("/offers", methods=["GET"])
def list_offers():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    limit, offset = parse_pagination(request.args)
    recs = list(store.offers.values())
    for key in ("conversation_id", "listing_id", "buyer_id", "seller_id", "status"):
        if key in request.args:
            val = request.args.get(key)
            recs = [o for o in recs if o[key] == val]
    return paginate_and_respond(recs, limit, offset, offer_out)


@bp.route("/offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    o = _find_offer(offer_id)
    return object_response(offer_out(o))


@bp.route("/offers/<offer_id>/counter", methods=["POST"])
def counter_offer(offer_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER})
    o = _find_offer(offer_id)
    side = _actor_side(o, user_id)  # ownership (priority 3)
    body = get_json_body()
    amount = V.require_int(body, "amount_cents", minimum=1)

    # State (priority 5): PROPOSED or COUNTERED.
    if o["status"] not in C.OFFER_OPEN_STATES:
        raise err("ERR_INVALID_STATE", "Offer is not open for counter.")

    listing = store.listings.get(o["listing_id"])
    member = store.members.get(user_id)
    # Acting member standing (priority 7).
    if member is not None and member["status"] == "BANNED":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Member is not active.")

    # Turn order (priority 12).
    if side == o["last_actor_side"]:
        raise err("ERR_NOT_YOUR_TURN", "It is not your turn.")
    # Round cap (priority 13).
    if o["round_count"] >= C.MAX_NEGOTIATION_ROUNDS:
        raise err("ERR_MAX_ROUNDS_REACHED", "Negotiation round cap reached.")
    # Listing must still be ACTIVE & AVAILABLE (§3.5).
    if listing is None or listing["publication_status"] != "ACTIVE" or listing["sale_status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Listing is not open for negotiation.")

    o["amount_cents"] = amount
    o["last_actor_side"] = side
    o["round_count"] += 1
    o["expires_at"] = offer_ttl_end()
    o["status"] = "COUNTERED"
    # Counter open->open leaves open_offer_count unchanged (§3.5).

    # Buyer-side counter below floor is auto-rejected (§3.5).
    if side == "BUYER" and amount < listing["min_acceptable_price_cents"]:
        # The offer was open before; moving it to REJECTED removes it from the
        # open set -> decrement by 1. Reconciling open_offer_count is a
        # denormalized-counter update, not a listing-version bump (§2.4/§2.7:
        # listing version advances only on the enumerated listing transitions).
        o["status"] = "REJECTED"
        o["expires_at"] = None
        if listing["open_offer_count"] > 0:
            listing["open_offer_count"] -= 1
    touch(o)
    return object_response(offer_out(o))


@bp.route("/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER})
    o = _find_offer(offer_id)
    side = _actor_side(o, user_id)  # ownership (priority 3)
    body = get_json_body()

    # State (priority 5): PROPOSED or COUNTERED.
    if o["status"] not in C.OFFER_OPEN_STATES:
        raise err("ERR_INVALID_STATE", "Offer is not open for accept.")

    listing = store.listings.get(o["listing_id"])
    if listing is None:
        raise err("ERR_NOT_FOUND", "Listing not found.")

    # OCC (priority 6): expected_listing_version required, must match (§2.7).
    expected = V.require_int(body, "expected_listing_version")
    if expected != listing["version"]:
        raise err("ERR_STALE_LISTING_VERSION", "Listing version is stale.")

    member = store.members.get(user_id)
    if member is not None and member["status"] == "BANNED":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Member is not active.")

    # Turn order (priority 12): the accepting actor must be the side entitled to
    # respond (the side that did NOT make the last move) (§3.5).
    if side == o["last_actor_side"]:
        raise err("ERR_NOT_YOUR_TURN", "It is not your turn.")

    # Listing must be AVAILABLE (§3.5).
    if listing["sale_status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Listing is not available.")

    # Accept: offer -> ACCEPTED; listing AVAILABLE -> RESERVED; set accepted_offer_id;
    # sibling open offers -> REJECTED (cascade). open_offer_count drops by 1 for the
    # accepted offer plus 1 per rejected sibling (§3.5).
    o["status"] = "ACCEPTED"
    o["expires_at"] = None
    listing["sale_status"] = "RESERVED"
    listing["accepted_offer_id"] = o["id"]
    if listing["open_offer_count"] > 0:
        listing["open_offer_count"] -= 1  # accepted offer leaves open set

    for sib in store.offers.values():
        if (
            sib["id"] != o["id"]
            and sib["listing_id"] == listing["id"]
            and sib["status"] in C.OFFER_OPEN_STATES
        ):
            sib["status"] = "REJECTED"
            sib["expires_at"] = None
            if listing["open_offer_count"] > 0:
                listing["open_offer_count"] -= 1
            touch(sib)

    touch(listing)
    touch(o)
    return object_response(offer_out(o))


@bp.route("/offers/<offer_id>/reject", methods=["POST"])
def reject_offer(offer_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER})
    o = _find_offer(offer_id)
    side = _actor_side(o, user_id)  # ownership (priority 3)

    # State (priority 5): PROPOSED or COUNTERED.
    if o["status"] not in C.OFFER_OPEN_STATES:
        raise err("ERR_INVALID_STATE", "Offer is not open for reject.")

    # On a COUNTERED offer the rejecter must be the side entitled to respond (§3.5).
    if o["status"] == "COUNTERED" and side == o["last_actor_side"]:
        raise err("ERR_NOT_YOUR_TURN", "It is not your turn.")

    listing = store.listings.get(o["listing_id"])
    o["status"] = "REJECTED"
    o["expires_at"] = None
    if listing is not None and listing["open_offer_count"] > 0:
        listing["open_offer_count"] -= 1
    touch(o)
    return object_response(offer_out(o))


@bp.route("/offers/<offer_id>/withdraw", methods=["POST"])
def withdraw_offer(offer_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_BUYER})
    o = _find_offer(offer_id)
    # Only the offer's buyer may withdraw (§3.5).
    if user_id != o["buyer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Only the buyer may withdraw.")

    # State (priority 5): PROPOSED or COUNTERED.
    if o["status"] not in C.OFFER_OPEN_STATES:
        raise err("ERR_INVALID_STATE", "Offer is not open for withdraw.")

    listing = store.listings.get(o["listing_id"])
    o["status"] = "WITHDRAWN"
    o["expires_at"] = None
    if listing is not None and listing["open_offer_count"] > 0:
        listing["open_offer_count"] -= 1
    touch(o)
    return object_response(offer_out(o))


@bp.route("/offers/<offer_id>/meetups", methods=["GET"])
def list_offer_meetups(offer_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_offer(offer_id)
    limit, offset = parse_pagination(request.args)
    recs = [m for m in store.meetups.values() if m["offer_id"] == offer_id]
    status = request.args.get("status")
    if status is not None:
        recs = [m for m in recs if m["status"] == status]
    return paginate_and_respond(recs, limit, offset, meetup_out)
