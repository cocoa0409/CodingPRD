"""Meetup endpoints (PRD §3.6) — temporal windowing, OCC, reservation compensation."""
from flask import Blueprint, request

import constants as C
from db import store
from domain import touch, recompute_trust_score, revert_reservation
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import meetup_out
from timeutil import parse_iso, minute_of_day, same_utc_date
import validate as V

bp = Blueprint("meetups", __name__)


def _find_meetup(meetup_id):
    m = store.meetups.get(meetup_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Meetup not found.")
    return m


def _actor_side(meetup, user_id):
    """Resolve which side the acting user is by matching X-User-ID against the
    meetup's buyer_id/seller_id (§2.1). Non-party -> NOT_RESOURCE_OWNER."""
    if user_id == meetup["buyer_id"]:
        return "BUYER"
    if user_id == meetup["seller_id"]:
        return "SELLER"
    raise err("ERR_NOT_RESOURCE_OWNER", "Acting member is not a party to this meetup.")


def _intervals_collide(a_start, a_end, b_start, b_end):
    # Half-open [start, end); collide iff a.start < b.end AND b.start < a.end (§3.6).
    return a_start < b_end and b_start < a_end


@bp.route("/meetups", methods=["POST"])
def create_meetup():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER})
    body = get_json_body()

    offer_id = V.require_str(body, "offer_id")
    spot_id = V.require_str(body, "spot_id")
    start_raw = V.require_field(body, "start_at")
    end_raw = V.require_field(body, "end_at")
    expected_offer_version = V.require_int(body, "expected_offer_version")

    # Existence left to right (§2.5): offer then spot.
    offer = store.offers.get(offer_id)
    if offer is None:
        raise err("ERR_NOT_FOUND", "Offer not found.")
    spot = store.safe_trade_spots.get(spot_id)
    if spot is None:
        raise err("ERR_NOT_FOUND", "Safe-trade spot not found.")

    # Ownership (§2.1): acting user must be a party to the offer.
    if user_id != offer["buyer_id"] and user_id != offer["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting member is not a party to this offer.")

    # State (priority 5): meetups are scheduled against an ACCEPTED offer (§3.6).
    if offer["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Offer is not ACCEPTED.")

    # OCC (priority 6): expected_offer_version must match (§2.7).
    if expected_offer_version != offer["version"]:
        raise err("ERR_STALE_OFFER_VERSION", "Offer version is stale.")

    # Acting member standing (priority 7).
    member = store.members.get(user_id)
    if member is not None and member["status"] == "BANNED":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Member is not active.")

    start_at = parse_iso(start_raw)
    end_at = parse_iso(end_raw)

    # Operating-hours containment + coherence (priority 10, §3.6).
    if not (end_at > start_at):
        raise err("ERR_OUTSIDE_SPOT_HOURS", "end_at must be after start_at.")
    if not same_utc_date(start_at, end_at):
        raise err("ERR_OUTSIDE_SPOT_HOURS", "Meetup may not span midnight.")
    start_mod = minute_of_day(start_at)
    end_mod = minute_of_day(end_at)
    if not (spot["open_minute_of_day"] <= start_mod and end_mod <= spot["close_minute_of_day"]):
        raise err("ERR_OUTSIDE_SPOT_HOURS", "Meetup window outside spot operating hours.")

    now = store.now()
    mid = store.new_id()
    rec = {
        "id": mid,
        "offer_id": offer_id,
        "listing_id": offer["listing_id"],
        "spot_id": spot_id,
        "buyer_id": offer["buyer_id"],
        "seller_id": offer["seller_id"],
        "start_at": start_at,
        "end_at": end_at,
        "status": "PROPOSED",
        # internal: which side proposed (the counterparty confirms, §3.6).
        "_proposer_side": "SELLER" if user_id == offer["seller_id"] else "BUYER",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.meetups[mid] = rec
    return object_response(meetup_out(rec), 201)


@bp.route("/meetups", methods=["GET"])
def list_meetups():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    limit, offset = parse_pagination(request.args)
    recs = list(store.meetups.values())
    for key in ("offer_id", "listing_id", "spot_id", "buyer_id", "seller_id", "status"):
        if key in request.args:
            val = request.args.get(key)
            recs = [m for m in recs if m[key] == val]
    return paginate_and_respond(recs, limit, offset, meetup_out)


@bp.route("/meetups/<meetup_id>", methods=["GET"])
def get_meetup(meetup_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    m = _find_meetup(meetup_id)
    return object_response(meetup_out(m))


@bp.route("/meetups/<meetup_id>/confirm", methods=["POST"])
def confirm_meetup(meetup_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER})
    m = _find_meetup(meetup_id)
    side = _actor_side(m, user_id)  # ownership (priority 3)

    # State (priority 5): must be PROPOSED.
    if m["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Meetup is not PROPOSED.")

    # Counterparty confirms — the side that did NOT propose (§3.6). Treated as a
    # turn-style constraint; the proposer cannot self-confirm.
    if side == m["_proposer_side"]:
        raise err("ERR_NOT_YOUR_TURN", "The counterparty must confirm the meetup.")

    listing = store.listings.get(m["listing_id"])
    # Listing must still be RESERVED with accepted_offer_id == this meetup's offer (§3.6).
    if (
        listing is None
        or listing["sale_status"] != "RESERVED"
        or listing["accepted_offer_id"] != m["offer_id"]
    ):
        raise err("ERR_INVALID_STATE", "Listing is not reserved for this meetup.")

    spot = store.safe_trade_spots.get(m["spot_id"])

    # High-value safe-trade gating (priority 8, §3.6).
    if listing["ask_price_cents"] >= C.HIGH_VALUE_THRESHOLD and not (spot and spot["is_police_verified"]):
        raise err("ERR_SPOT_NOT_POLICE_VERIFIED", "High-value meetup requires a police-verified spot.")

    # Overlap with other CONFIRMED meetups at the same spot (priority 11, §3.6).
    for other in store.meetups.values():
        if (
            other["id"] != m["id"]
            and other["spot_id"] == m["spot_id"]
            and other["status"] == "CONFIRMED"
            and _intervals_collide(m["start_at"], m["end_at"], other["start_at"], other["end_at"])
        ):
            raise err("ERR_SPOT_TIME_CONFLICT", "Meetup time conflicts with a confirmed meetup.")

    m["status"] = "CONFIRMED"
    touch(m)
    return object_response(meetup_out(m))


@bp.route("/meetups/<meetup_id>/complete", methods=["POST"])
def complete_meetup(meetup_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER})
    m = _find_meetup(meetup_id)
    # Only the listing's seller may complete (§3.6).
    if user_id != m["seller_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Only the seller may complete the meetup.")

    # State (priority 5): must be CONFIRMED.
    if m["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Meetup is not CONFIRMED.")

    listing = store.listings.get(m["listing_id"])
    if (
        listing is None
        or listing["sale_status"] != "RESERVED"
        or listing["accepted_offer_id"] != m["offer_id"]
    ):
        raise err("ERR_INVALID_STATE", "Listing is not reserved for this meetup.")

    m["status"] = "COMPLETED"
    # Sale finalization (§3.6): sale_status RESERVED->SOLD; publication ->REMOVED if
    # ACTIVE/EXPIRED (decrement active_listing_count if ACTIVE); close OPEN
    # conversations; recompute buyer and seller trust_score.
    listing["sale_status"] = "SOLD"
    if listing["publication_status"] == "ACTIVE":
        seller_member = store.members.get(listing["seller_id"])
        if seller_member is not None and seller_member["active_listing_count"] > 0:
            seller_member["active_listing_count"] -= 1
        listing["publication_status"] = "REMOVED"
    elif listing["publication_status"] == "EXPIRED":
        listing["publication_status"] = "REMOVED"

    for conv in store.conversations.values():
        if conv["listing_id"] == listing["id"] and conv["status"] == "OPEN":
            conv["status"] = "CLOSED"
            touch(conv)

    touch(listing)
    touch(m)

    buyer = store.members.get(m["buyer_id"])
    seller = store.members.get(m["seller_id"])
    if buyer is not None:
        recompute_trust_score(buyer)
        touch(buyer)
    if seller is not None:
        recompute_trust_score(seller)
        touch(seller)

    return object_response(meetup_out(m))


@bp.route("/meetups/<meetup_id>/cancel", methods=["POST"])
def cancel_meetup(meetup_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER, C.ROLE_MODERATOR})
    m = _find_meetup(meetup_id)
    # Seller/Buyer must be a party; Moderator is opaque (§2.1).
    if role in (C.ROLE_SELLER, C.ROLE_BUYER):
        _actor_side(m, user_id)

    # State (priority 5): cancel defined from PROPOSED or CONFIRMED (§3.6).
    if m["status"] not in ("PROPOSED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Meetup cannot be cancelled from current state.")

    m["status"] = "CANCELLED"
    touch(m)

    # If this meetup references the listing's accepted_offer_id, revert the
    # reservation (compensation, §3.6).
    listing = store.listings.get(m["listing_id"])
    if (
        listing is not None
        and listing["sale_status"] == "RESERVED"
        and listing["accepted_offer_id"] == m["offer_id"]
    ):
        revert_reservation(listing, m["offer_id"])

    return object_response(meetup_out(m))


@bp.route("/meetups/<meetup_id>/no-show", methods=["POST"])
def no_show_meetup(meetup_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_SELLER, C.ROLE_BUYER})
    m = _find_meetup(meetup_id)
    _actor_side(m, user_id)  # ownership (priority 3)

    # State (priority 5): must be CONFIRMED (§3.6).
    if m["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Meetup is not CONFIRMED.")

    # No-show may be reported only once clock >= end_at (§3.6).
    if store.now() < m["end_at"]:
        raise err("ERR_INVALID_STATE", "No-show can only be reported after end_at.")

    m["status"] = "NO_SHOW"
    touch(m)

    listing = store.listings.get(m["listing_id"])
    if (
        listing is not None
        and listing["sale_status"] == "RESERVED"
        and listing["accepted_offer_id"] == m["offer_id"]
    ):
        revert_reservation(listing, m["offer_id"])

    return object_response(meetup_out(m))
