"""Conversation & Message endpoints (PRD §3.4)."""
from flask import Blueprint, request

import constants as C
from db import store
from domain import touch
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import conversation_out, message_out, offer_out
import validate as V

bp = Blueprint("conversations", __name__)


def _find_conversation(conv_id):
    c = store.conversations.get(conv_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Conversation not found.")
    return c


@bp.route("/conversations", methods=["POST"])
def create_conversation():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_BUYER})
    body = get_json_body()

    listing_id = V.require_str(body, "listing_id")
    buyer_id = V.require_str(body, "buyer_id")

    # Ownership: acting buyer must be buyer_id (§2.1).
    if user_id != buyer_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting buyer is not the conversation owner.")

    # Existence left to right (§2.5): listing then buyer.
    listing = store.listings.get(listing_id)
    if listing is None:
        raise err("ERR_NOT_FOUND", "Listing not found.")
    buyer = store.members.get(buyer_id)
    if buyer is None:
        raise err("ERR_NOT_FOUND", "Buyer not found.")

    # Self-trade ban (§3.4).
    if buyer_id == listing["seller_id"]:
        raise err("ERR_CANNOT_TRADE_OWN_LISTING", "Cannot trade on own listing.")

    now = store.now()
    cid = store.new_id()
    rec = {
        "id": cid,
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "seller_id": listing["seller_id"],
        "status": "OPEN",
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.conversations[cid] = rec
    return object_response(conversation_out(rec), 201)


@bp.route("/conversations", methods=["GET"])
def list_conversations():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    limit, offset = parse_pagination(request.args)
    recs = list(store.conversations.values())
    if "listing_id" in request.args:
        recs = [c for c in recs if c["listing_id"] == request.args.get("listing_id")]
    if "buyer_id" in request.args:
        recs = [c for c in recs if c["buyer_id"] == request.args.get("buyer_id")]
    if "seller_id" in request.args:
        recs = [c for c in recs if c["seller_id"] == request.args.get("seller_id")]
    if "status" in request.args:
        recs = [c for c in recs if c["status"] == request.args.get("status")]
    return paginate_and_respond(recs, limit, offset, conversation_out)


@bp.route("/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    c = _find_conversation(conv_id)
    return object_response(conversation_out(c))


@bp.route("/conversations/<conv_id>/messages", methods=["GET"])
def list_conversation_messages(conv_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_conversation(conv_id)
    limit, offset = parse_pagination(request.args)
    recs = [m for m in store.messages.values() if m["conversation_id"] == conv_id]
    return paginate_and_respond(recs, limit, offset, message_out)


@bp.route("/conversations/<conv_id>/offers", methods=["GET"])
def list_conversation_offers(conv_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_conversation(conv_id)
    limit, offset = parse_pagination(request.args)
    recs = [o for o in store.offers.values() if o["conversation_id"] == conv_id]
    status = request.args.get("status")
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return paginate_and_respond(recs, limit, offset, offer_out)


# --------------------- Messages ---------------------

@bp.route("/messages", methods=["POST"])
def send_message():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER})
    body = get_json_body()

    conversation_id = V.require_str(body, "conversation_id")
    sender_id = V.require_str(body, "sender_id")
    msg_body = V.require_str(body, "body", max_len=2000)

    # Ownership (§2.1): acting member must be the sender.
    if user_id != sender_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting member is not the sender.")

    # Existence (§2.5): conversation then sender.
    conv = store.conversations.get(conversation_id)
    if conv is None:
        raise err("ERR_NOT_FOUND", "Conversation not found.")
    sender = store.members.get(sender_id)
    if sender is None:
        raise err("ERR_NOT_FOUND", "Sender not found.")

    # Acting member standing (priority 7): not BANNED (§1.4).
    if sender["status"] == "BANNED":
        raise err("ERR_MEMBER_NOT_ACTIVE", "Sender is not active.")

    # Participant check (§3.4).
    if sender_id != conv["buyer_id"] and sender_id != conv["seller_id"]:
        raise err("ERR_NOT_CONVERSATION_PARTICIPANT", "Sender is not a participant.")

    now = store.now()
    mid = store.new_id()
    rec = {
        "id": mid,
        "conversation_id": conversation_id,
        "sender_id": sender_id,
        "body": msg_body,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.messages[mid] = rec
    conv["message_count"] += 1
    touch(conv)
    return object_response(message_out(rec), 201)


@bp.route("/messages", methods=["GET"])
def list_messages():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    limit, offset = parse_pagination(request.args)
    recs = list(store.messages.values())
    if "conversation_id" in request.args:
        recs = [m for m in recs if m["conversation_id"] == request.args.get("conversation_id")]
    if "sender_id" in request.args:
        recs = [m for m in recs if m["sender_id"] == request.args.get("sender_id")]
    return paginate_and_respond(recs, limit, offset, message_out)


@bp.route("/messages/<msg_id>", methods=["GET"])
def get_message(msg_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    m = store.messages.get(msg_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Message not found.")
    return object_response(message_out(m))
