"""SpamRule routes (PRD §3.2)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public,
                    as_str, as_int, as_array)
from services.lookups import find_or_404, require_account_owner

bp = Blueprint("spam_rules", __name__)


@bp.route("/va/spam-rules", methods=["POST"])
def create_rule():
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER, ROLE_ADMIN})
    body = get_body()

    account_id = as_str(body, "account_id", required=True)
    account = find_or_404(db.accounts, account_id)
    require_account_owner(account["id"], user_id, role)

    blocked = as_array(body, "blocked_area_codes", default=[])
    for code in blocked:
        if not isinstance(code, str):
            raise errors.err(errors.ERR_INVALID_REQUEST, "blocked_area_codes must be strings")
    spam_score_threshold = as_int(body, "spam_score_threshold", default=70, minimum=0, maximum=100)
    anonymous_penalty = as_int(body, "anonymous_penalty", default=40, minimum=0, maximum=100)

    rec = make_record({
        "account_id": account_id,
        "blocked_area_codes": list(blocked),
        "spam_score_threshold": spam_score_threshold,
        "anonymous_penalty": anonymous_penalty,
        "status": "ACTIVE",
    })
    db.spam_rules[rec["id"]] = rec
    return success_object(serializers.spam_rule(public(rec)), 201)


@bp.route("/va/spam-rules/<rule_id>", methods=["GET"])
def get_rule(rule_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.spam_rules, rule_id)
    require_account_owner(rec["account_id"], user_id, role)
    return success_object(serializers.spam_rule(public(rec)), 200)


@bp.route("/va/spam-rules", methods=["GET"])
def list_rules():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.spam_rules.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if role == ROLE_OWNER:
        records = [r for r in records if r["account_id"] == user_id]
    page, meta = paginate(records)
    return success_array([serializers.spam_rule(public(r)) for r in page], meta, 200)
