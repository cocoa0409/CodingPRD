"""CrmHandoff routes (PRD §3.13)."""
from flask import Blueprint, request

import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public, touch,
                    as_str, as_enum)
from services.lookups import find_or_404, require_account_owner

bp = Blueprint("crm_handoffs", __name__)

CRM_TARGETS = {"SALESFORCE", "HUBSPOT", "ZOHO"}


@bp.route("/va/crm-handoffs", methods=["POST"])
def create_handoff():
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    body = get_body()

    call_id = as_str(body, "call_id", required=True)
    call = find_or_404(db.calls, call_id)
    require_account_owner(call["account_id"], user_id, role)
    crm_target = as_enum(body, "crm_target", CRM_TARGETS, required=True)

    # Flip every NEW Message on the call to HANDED_OFF (PRD §3.13).
    pushed = 0
    for m in db.messages.values():
        if m["call_id"] == call_id and m["status"] == "NEW":
            m["status"] = "HANDED_OFF"
            touch(m)
            pushed += 1

    rec = make_record({
        "call_id": call_id,
        "crm_target": crm_target,
        "messages_pushed": pushed,
        "status": "PUSHED",
    })
    db.crm_handoffs[rec["id"]] = rec
    return success_object(serializers.crm_handoff(public(rec)), 201)


@bp.route("/va/crm-handoffs/<handoff_id>", methods=["GET"])
def get_handoff(handoff_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.crm_handoffs, handoff_id)
    if role == ROLE_OWNER:
        call = db.calls.get(rec["call_id"])
        if call is not None:
            require_account_owner(call["account_id"], user_id, role)
    return success_object(serializers.crm_handoff(public(rec)), 200)


@bp.route("/va/crm-handoffs", methods=["GET"])
def list_handoffs():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.crm_handoffs.values())
    call_id = request.args.get("call_id")
    if call_id is not None:
        records = [r for r in records if r["call_id"] == call_id]
    if role == ROLE_OWNER:
        owned = {c["id"] for c in db.calls.values() if c["account_id"] == user_id}
        records = [r for r in records if r["call_id"] in owned]
    page, meta = paginate(records)
    return success_array([serializers.crm_handoff(public(r)) for r in page], meta, 200)
