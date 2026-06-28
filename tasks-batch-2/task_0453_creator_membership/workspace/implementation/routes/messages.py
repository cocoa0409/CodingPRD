"""Message endpoints (PRD §3.8)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_auth, require_role
from services import serialize
from services.common import (init_audit, touch, get_body, require_string,
                             parse_pagination, paginate)
from services.lookups import get_conversation, get_message

bp = Blueprint("messages", __name__)


def _patron_is_member(patron_id, creator_id):
    for p in db.pledges.values():
        if p["patron_id"] == patron_id and p["creator_id"] == creator_id and \
                p["lifecycle_status"] in ("ACTIVE", "PAUSED"):
            return True
    return False


@bp.post("/messages")
def post_message():
    ctx = require_auth()
    require_role(ctx, {"Patron", "Creator"})
    body = get_body()

    conversation_id = body.get("conversation_id")
    if conversation_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: conversation_id")
    conv = get_conversation(conversation_id)
    body_text = require_string(body, "body")

    # Ownership (PRD §2.1): the sender must be on the conversation's matching side.
    if ctx.is_creator and ctx.user_id != conv["creator_id"]:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Creator does not own this conversation")
    if ctx.is_patron and ctx.user_id != conv["patron_id"]:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Patron does not own this conversation")

    # State: messages only to an OPEN conversation (PRD §3.8).
    if conv["status"] != "OPEN":
        errors.fail(errors.ERR_CONVERSATION_CLOSED, "Conversation is CLOSED")

    # Cross-link: the conversation must match the sender's side (PRD §3.8).
    if ctx.is_creator:
        sender_role = "CREATOR"
        sender_id = ctx.user_id
        if conv["creator_id"] != sender_id:
            errors.fail(errors.ERR_CROSS_LINK_MISMATCH, "Conversation does not match sender")
    else:
        sender_role = "PATRON"
        sender_id = ctx.user_id
        if conv["patron_id"] != sender_id:
            errors.fail(errors.ERR_CROSS_LINK_MISMATCH, "Conversation does not match sender")
        # Patron sender must still be an ACTIVE/PAUSED patron of the creator
        # (PRD §3.8).
        if not _patron_is_member(conv["patron_id"], conv["creator_id"]):
            errors.fail(errors.ERR_NOT_A_PATRON_OF_CREATOR,
                        "Patron has no ACTIVE/PAUSED pledge to this creator")

    rec = init_audit({
        "conversation_id": conversation_id,
        "sender_role": sender_role,
        "sender_id": sender_id,
        "body": body_text,
    })
    db.messages[rec["id"]] = rec

    # Each posted message increments the conversation's message_count (PRD §3.8).
    conv["message_count"] = conv.get("message_count", 0) + 1
    touch(conv)

    return response.success(serialize.message(rec), status=201)


@bp.get("/messages")
def list_messages():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.messages.values())
    conversation_id = request.args.get("conversation_id")
    if conversation_id is not None:
        items = [m for m in items if m["conversation_id"] == conversation_id]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.message(r) for r in page], limit, offset, total)


@bp.get("/messages/<message_id>")
def get_one_message(message_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_message(message_id)
    return response.success(serialize.message(rec))
