"""ClientAccount routes (PRD §3.1)."""
from flask import Blueprint, request

import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public,
                    as_str, as_enum)
from services.lookups import find_or_404, require_account_owner

bp = Blueprint("accounts", __name__)

LANGUAGES = {"EN", "ES"}


def open_first_period(account, plan):
    """Open the account's first BillingPeriod (period_index 0) at creation
    (PRD §3.1). included_units pinned from the plan by billing_model."""
    included = plan["included_minutes"] if plan["billing_model"] == "PER_MINUTE" else plan["included_calls"]
    period = make_record({
        "account_id": account["id"],
        "plan_id": plan["id"],
        "period_index": 0,
        "included_units": included,
        "consumed_units": 0,
        "overage_units": 0,
        "overage_charge_cents": 0,
        "status": "OPEN",
    })
    db.billing_periods[period["id"]] = period
    return period


@bp.route("/va/accounts", methods=["POST"])
def create_account():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    business_name = as_str(body, "business_name", required=True)
    plan_id = as_str(body, "plan_id", required=True)
    default_language = as_enum(body, "default_language", LANGUAGES, default="EN")

    plan = find_or_404(db.service_plans, plan_id)

    rec = make_record({
        "business_name": business_name,
        "plan_id": plan_id,
        "default_language": default_language,
        "status": "ACTIVE",
        "current_period_id": None,
        "open_call_count": 0,
        "lifetime_calls_answered": 0,
    })
    db.accounts[rec["id"]] = rec
    period = open_first_period(rec, plan)
    rec["current_period_id"] = period["id"]
    return success_object(serializers.account(public(rec)), 201)


@bp.route("/va/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.accounts, account_id)
    require_account_owner(rec["id"], user_id, role)
    return success_object(serializers.account(public(rec)), 200)


@bp.route("/va/accounts", methods=["GET"])
def list_accounts():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    records = list(db.accounts.values())
    plan_id = request.args.get("plan_id")
    period_id = request.args.get("current_period_id")
    status = request.args.get("status")
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if period_id is not None:
        records = [r for r in records if r["current_period_id"] == period_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = paginate(records)
    return success_array([serializers.account(public(r)) for r in page], meta, 200)
