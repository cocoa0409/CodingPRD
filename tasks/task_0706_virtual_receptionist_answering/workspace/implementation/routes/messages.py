"""Message routes (PRD §3.13)."""
from flask import Blueprint, request

import serializers
from db import db
from response import success_object, success_array
from middleware import (get_auth, require_role, ROLE_ADMIN, ROLE_OWNER,
                        ROLE_RECEPTIONIST)
from common import (get_body, make_record, paginate, public,
                    as_str, as_bool)
from services.lookups import find_or_404, require_account_owner

bp = Blueprint("messages", __name__)


@bp.route("/va/messages", methods=["POST"])
def create_message():
    _, role = get_auth()
    require_role(role, {ROLE_RECEPTIONIST})
    body = get_body()

    call_id = as_str(body, "call_id", required=True)
    find_or_404(db.calls, call_id)
    caller_name = as_str(body, "caller_name", required=True)
    callback_number = as_str(body, "callback_number", required=True)
    msg_body = as_str(body, "body", required=True)
    is_lead = as_bool(body, "is_lead", default=False)

    rec = make_record({
        "call_id": call_id,
        "caller_name": caller_name,
        "callback_number": callback_number,
        "body": msg_body,
        "is_lead": is_lead,
        "status": "NEW",
    })
    db.messages[rec["id"]] = rec
    return success_object(serializers.message(public(rec)), 201)


@bp.route("/va/messages/<message_id>", methods=["GET"])
def get_message(message_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER, ROLE_RECEPTIONIST})
    rec = find_or_404(db.messages, message_id)
    if role == ROLE_OWNER:
        call = db.calls.get(rec["call_id"])
        if call is not None:
            require_account_owner(call["account_id"], user_id, role)
    return success_object(serializers.message(public(rec)), 200)


@bp.route("/va/messages", methods=["GET"])
def list_messages():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER, ROLE_RECEPTIONIST})
    records = list(db.messages.values())
    call_id = request.args.get("call_id")
    status = request.args.get("status")
    if call_id is not None:
        records = [r for r in records if r["call_id"] == call_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if role == ROLE_OWNER:
        owned = {c["id"] for c in db.calls.values() if c["account_id"] == user_id}
        records = [r for r in records if r["call_id"] in owned]
    page, meta = paginate(records)
    return success_array([serializers.message(public(r)) for r in page], meta, 200)
