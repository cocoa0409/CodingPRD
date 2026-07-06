"""CallScript routes (PRD §3.2)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public, touch,
                    as_str, as_int, as_enum)
from services.lookups import find_or_404, require_account_owner

bp = Blueprint("call_scripts", __name__)

AFTER_HOURS_ACTIONS = {"VOICEMAIL", "OVERFLOW"}
OVERFLOW_ACTIONS = {"QUEUE", "VOICEMAIL"}


@bp.route("/va/call-scripts", methods=["POST"])
def create_script():
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    body = get_body()

    account_id = as_str(body, "account_id", required=True)
    account = find_or_404(db.accounts, account_id)
    require_account_owner(account["id"], user_id, role)

    greeting_en = as_str(body, "greeting_en", required=True)
    business_open_minute = as_int(body, "business_open_minute", required=True, minimum=0, maximum=1439)
    business_close_minute = as_int(body, "business_close_minute", required=True, minimum=1, maximum=1440)
    if business_close_minute <= business_open_minute:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "business_close_minute must be greater than business_open_minute")
    greeting_es = as_str(body, "greeting_es", default="")
    after_hours_action = as_enum(body, "after_hours_action", AFTER_HOURS_ACTIONS, default="VOICEMAIL")
    overflow_action = as_enum(body, "overflow_action", OVERFLOW_ACTIONS, default="QUEUE")
    escalation_threshold_seconds = as_int(body, "escalation_threshold_seconds", default=600, minimum=1)

    rec = make_record({
        "account_id": account_id,
        "greeting_en": greeting_en,
        "greeting_es": greeting_es,
        "business_open_minute": business_open_minute,
        "business_close_minute": business_close_minute,
        "after_hours_action": after_hours_action,
        "overflow_action": overflow_action,
        "escalation_threshold_seconds": escalation_threshold_seconds,
        "status": "DRAFT",
    })
    db.call_scripts[rec["id"]] = rec
    return success_object(serializers.call_script(public(rec)), 201)


@bp.route("/va/call-scripts/<script_id>", methods=["GET"])
def get_script(script_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.call_scripts, script_id)
    require_account_owner(rec["account_id"], user_id, role)
    return success_object(serializers.call_script(public(rec)), 200)


@bp.route("/va/call-scripts", methods=["GET"])
def list_scripts():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.call_scripts.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if role == ROLE_OWNER:
        records = [r for r in records if r["account_id"] == user_id]
    page, meta = paginate(records)
    return success_array([serializers.call_script(public(r)) for r in page], meta, 200)


@bp.route("/va/call-scripts/<script_id>/publish", methods=["POST"])
def publish_script(script_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.call_scripts, script_id)
    require_account_owner(rec["account_id"], user_id, role)

    # Transition must be defined from current state (PRD §2.7 priority 6).
    if rec["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT script may be published")

    # Retire the account's prior PUBLISHED script (PRD §3.2).
    for s in db.call_scripts.values():
        if s["account_id"] == rec["account_id"] and s["status"] == "PUBLISHED" and s["id"] != rec["id"]:
            s["status"] = "RETIRED"
            touch(s)

    rec["status"] = "PUBLISHED"
    touch(rec)
    return success_object(serializers.call_script(public(rec)), 200)
