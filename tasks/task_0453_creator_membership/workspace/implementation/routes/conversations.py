"""Conversation endpoints + patron-only messaging gate (PRD §3.8)."""
from flask import Blueprint, request

import errors
import response
from db import db
from middleware import require_auth, require_role
from services import serialize
from services.common import (init_common, touch, get_body, parse_pagination, paginate)
from services.lookups import (get_creator, get_patron, get_conversation,
                              require_creator_owner, require_patron_owner)

bp = Blueprint("conversations", __name__)


def _patron_is_member(patron_id, creator_id):
    """Patron holds an ACTIVE/PAUSED pledge to the creator (PRD §3.8)."""
    for p in db.pledges.values():
        if p["patron_id"] == patron_id and p["creator_id"] == creator_id and \
                p["lifecycle_status"] in ("ACTIVE", "PAUSED"):
            return True
    return False


@bp.post("/conversations")
def open_conversation():
    ctx = require_auth()
    require_role(ctx, {"Patron", "Creator"})
    body = get_body()

    creator_id = body.get("creator_id")
    patron_id = body.get("patron_id")
    if creator_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: creator_id")
    if patron_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: patron_id")

    # Ownership: the acting side must own its end of the conversation (PRD §2.1).
    require_creator_owner(ctx, creator_id)
    require_patron_owner(ctx, patron_id)

    creator = get_creator(creator_id)
    patron = get_patron(patron_id)

    # Patron-only messaging gate (PRD §3.8): a patron opening a conversation must
    # hold an ACTIVE/PAUSED pledge to that creator.
    if ctx.is_patron:
        if not _patron_is_member(patron_id, creator_id):
            errors.fail(errors.ERR_NOT_A_PATRON_OF_CREATOR,
                        "Patron has no ACTIVE/PAUSED pledge to this creator")

    rec = init_common({
        "creator_id": creator_id,
        "patron_id": patron_id,
        "status": "OPEN",
        "message_count": 0,
    })
    db.conversations[rec["id"]] = rec
    return response.success(serialize.conversation(rec), status=201)


@bp.get("/conversations")
def list_conversations():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.conversations.values())
    for key in ("creator_id", "patron_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.conversation(r) for r in page], limit, offset, total)


@bp.get("/conversations/<conversation_id>")
def get_one_conversation(conversation_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_conversation(conversation_id)
    return response.success(serialize.conversation(rec))


@bp.post("/conversations/<conversation_id>/close")
def close_conversation(conversation_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron"})
    conv = get_conversation(conversation_id)
    # Ownership: the acting side must own its end of the conversation (PRD §2.1).
    require_creator_owner(ctx, conv["creator_id"])
    require_patron_owner(ctx, conv["patron_id"])

    # State: closing a CLOSED conversation is rejected (PRD §3.8).
    if conv["status"] != "OPEN":
        errors.fail(errors.ERR_CONVERSATION_CLOSED, "Conversation is already CLOSED")

    conv["status"] = "CLOSED"
    touch(conv)
    return response.success(serialize.conversation(conv))
