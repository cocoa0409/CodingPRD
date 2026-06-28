"""Message endpoints (append-only) (PRD §3.8)."""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from helpers import (get_json_body, require_fields, require_string,
                     pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import message_view
from services import domain

bp = Blueprint("messages", __name__)

ROLE_TO_SENDER = {"Trainer": "TRAINER", "Client": "CLIENT"}


@bp.route("/messages", methods=["POST"])
@require_roles("Trainer", "Client")
def create_message():
    body = get_json_body()
    require_fields(body, "engagement_id", "body")

    engagement = domain.get_engagement(body["engagement_id"])
    domain.assert_owns_engagement(engagement)

    text = require_string(body["body"], "body")

    mid = new_id()
    ts = now_ts()
    message = {
        "id": mid,
        "engagement_id": engagement["id"],
        "sender_role": ROLE_TO_SENDER[g.user_role],
        "body": text,
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    db.messages[mid] = message
    return success(message_view(message), 201)


@bp.route("/messages/<message_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_message(message_id):
    message = domain.get_message(message_id)
    engagement = domain.get_engagement(message["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(message_view(message), 200)


@bp.route("/messages", methods=["GET"])
@require_roles("Trainer", "Client")
def list_messages():
    limit, offset = pagination_params()
    engagement_filter = request.args.get("engagement_id")
    items = list(db.messages.values())
    if engagement_filter is not None:
        items = [m for m in items if m["engagement_id"] == engagement_filter]
    items = [m for m in items if _owns_message(m)]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([message_view(m) for m in page], limit, offset, total, 200)


def _owns_message(message):
    engagement = db.engagements.get(message["engagement_id"])
    if engagement is None:
        return False
    if g.user_role == "Trainer":
        return engagement["trainer_id"] == g.user_id
    if g.user_role == "Client":
        return engagement["client_id"] == g.user_id
    return True
