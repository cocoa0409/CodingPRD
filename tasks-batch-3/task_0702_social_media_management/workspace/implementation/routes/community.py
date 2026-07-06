"""Community conversation + engagement message routes (PRD §3.5)."""
from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_CHANNEL_NOT_LIVE, ERR_INVALID_REQUEST,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_string, require_enum,
)
from services import lookup, listing
from services.serialize import conversation_out, message_out

bp = Blueprint("community", __name__)

KINDS = {"DM", "COMMENT"}
DIRECTIONS = {"INBOUND", "OUTBOUND"}


def _recount_messages(conversation_id):
    return sum(1 for m in db.messages.values() if m["conversation_id"] == conversation_id)


# ---------------- Conversations ----------------

@bp.post("/conversations")
def create_conversation():
    _, role = get_user_context()
    require_role(role, {"CommunityAgent", "AccountManager"})
    body = get_json_body()
    channel_id = require_string(body, "channel_id")
    with db.LOCK:
        lookup.get_channel(channel_id)
        kind = require_enum(body, "kind", KINDS)
        external = require_string(body, "external_author_handle")
        conv = {
            "id": db.new_id(),
            "channel_id": channel_id,
            "kind": kind,
            "external_author_handle": external,
            "status": "OPEN",
            "assigned_agent_id": None,
            "message_count": 0,
        }
        db.stamp_create(conv, full=True)
        db.conversations[conv["id"]] = conv
        return response.created(conversation_out(conv))


@bp.get("/conversations")
def list_conversations():
    _, role = get_user_context()
    require_role(role, {"CommunityAgent", "AccountManager", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.conversations.values()), {
            "channel_id": request.args.get("channel_id"),
            "status": request.args.get("status"),
            "assigned_agent_id": request.args.get("assigned_agent_id"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([conversation_out(c) for c in window], limit, offset, total)


@bp.get("/conversations/<conversation_id>")
def get_conversation(conversation_id):
    _, role = get_user_context()
    require_role(role, {"CommunityAgent", "AccountManager", "PlatformAdmin"})
    with db.LOCK:
        c = lookup.get_conversation(conversation_id)
        return response.ok(conversation_out(c))


@bp.post("/conversations/<conversation_id>/assign")
def assign_conversation(conversation_id):
    user_id, role = get_user_context()
    require_role(role, {"CommunityAgent"})
    with db.LOCK:
        c = lookup.get_conversation(conversation_id)
        # transition defined from OPEN or ESCALATED -> ASSIGNED
        if c["status"] not in ("OPEN", "ESCALATED"):
            raise err(ERR_INVALID_STATE, "Conversation cannot be assigned from its current state")
        # cross-entity state: channel must be LIVE
        channel = lookup.get_channel(c["channel_id"])
        if channel["status"] != "LIVE":
            raise err(ERR_CHANNEL_NOT_LIVE, "Channel must be LIVE to assign a conversation")
        c["status"] = "ASSIGNED"
        c["assigned_agent_id"] = user_id
        db.touch(c)
        return response.ok(conversation_out(c))


@bp.post("/conversations/<conversation_id>/escalate")
def escalate_conversation(conversation_id):
    _, role = get_user_context()
    require_role(role, {"CommunityAgent"})
    get_json_body()  # optional reason; not persisted
    with db.LOCK:
        c = lookup.get_conversation(conversation_id)
        if c["status"] not in ("OPEN", "ASSIGNED"):
            raise err(ERR_INVALID_STATE, "Conversation cannot be escalated from its current state")
        c["status"] = "ESCALATED"
        db.touch(c)
        return response.ok(conversation_out(c))


@bp.post("/conversations/<conversation_id>/resolve")
def resolve_conversation(conversation_id):
    _, role = get_user_context()
    require_role(role, {"CommunityAgent"})
    with db.LOCK:
        c = lookup.get_conversation(conversation_id)
        if c["status"] not in ("ASSIGNED", "ESCALATED"):
            raise err(ERR_INVALID_STATE, "Conversation cannot be resolved from its current state")
        c["status"] = "RESOLVED"
        db.touch(c)
        return response.ok(conversation_out(c))


# ---------------- Engagement messages ----------------

@bp.post("/messages")
def create_message():
    _, role = get_user_context()
    require_role(role, {"CommunityAgent"})
    body = get_json_body()
    conversation_id = require_string(body, "conversation_id")
    with db.LOCK:
        conv = lookup.get_conversation(conversation_id)
        direction = require_enum(body, "direction", DIRECTIONS)
        msg_body = require_string(body, "body")
        author_agent_id = body.get("author_agent_id")
        if direction == "OUTBOUND":
            if not isinstance(author_agent_id, str) or not author_agent_id.strip():
                raise err(ERR_INVALID_REQUEST,
                          "OUTBOUND message requires author_agent_id")
        else:
            author_agent_id = None
        m = {
            "id": db.new_id(),
            "conversation_id": conversation_id,
            "direction": direction,
            "body": msg_body,
            "author_agent_id": author_agent_id,
        }
        db.stamp_create(m, full=False)
        db.messages[m["id"]] = m
        conv["message_count"] = _recount_messages(conversation_id)
        db.touch(conv)
        return response.created(message_out(m))


@bp.get("/messages")
def list_messages():
    _, role = get_user_context()
    require_role(role, {"CommunityAgent", "AccountManager", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.messages.values()), {
            "conversation_id": request.args.get("conversation_id"),
            "direction": request.args.get("direction"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([message_out(m) for m in window], limit, offset, total)


@bp.get("/messages/<message_id>")
def get_message(message_id):
    _, role = get_user_context()
    require_role(role, {"CommunityAgent", "AccountManager", "PlatformAdmin"})
    with db.LOCK:
        m = lookup.get_message(message_id)
        return response.ok(message_out(m))
