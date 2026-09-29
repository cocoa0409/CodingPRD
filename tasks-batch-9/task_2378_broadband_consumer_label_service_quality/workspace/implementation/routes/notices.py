"""Plan-change and price-increase notices (PRD §3.7)."""

from flask import Blueprint, request

import db
import errors
import lookup
import response
import serializers
import validators
from errors import fail
from middleware import (COMPLAINT_ANALYST, COMPLIANCE_OFFICER,
                        REGULATORY_LIAISON, RETAIL_AGENT, SUBSCRIBER,
                        authorize, require_own_account)
from services import calculations as calc

bp = Blueprint("notices", __name__)

NOTICE_TYPES = ("PLAN_CHANGE", "PRICE_INCREASE")
READ_ROLES = (COMPLIANCE_OFFICER, COMPLAINT_ANALYST, REGULATORY_LIAISON,
              RETAIL_AGENT, SUBSCRIBER)


@bp.route("/plan-change-notices", methods=["POST"])
def create_plan_change_notice():
    authorize(RETAIL_AGENT)
    body = validators.json_body()

    account_ref = validators.get_id_ref(body, "account_id")
    target_ref = validators.get_id_ref(body, "target_plan_id")
    notice_type = validators.get_enum(body, "notice_type", NOTICE_TYPES)
    effective_raw = validators.get_datetime(body, "effective_date")
    reason = validators.get_str(body, "reason", 1, 500)

    account = lookup.subscriber_account(account_ref)
    target_plan = lookup.service_plan(target_ref)

    # Step 6 — the account must not already have a change pending.
    if account["subscription_state"] != "ACTIVE":
        fail(errors.ERR_ACCOUNT_CHANGE_ALREADY_PENDING)

    # Step 9 — the disclosure posture of the plan the account is on.
    source_plan = lookup.service_plan(account["plan_id"])
    posture = source_plan["label_posture"]
    if posture == "FROZEN":
        fail(errors.ERR_PLAN_POSTURE_FROZEN)
    if posture == "RESTRICTED" and notice_type == "PRICE_INCREASE":
        fail(errors.ERR_PLAN_POSTURE_RESTRICTED)

    # Step 11 — the notice period.
    notice_days = db.whole_days_between(db.now(), db.parse_iso(effective_raw))
    if notice_days < calc.NOTICE_MIN_DAYS:
        fail(errors.ERR_NOTICE_PERIOD_TOO_SHORT)

    published = calc.published_label(target_plan["id"])
    disclosed_net = (published["net_monthly_post_promo_cents"]
                     if published is not None else None)

    notice = db.new_record()
    notice.update({
        "account_id": account["id"],
        "target_plan_id": target_plan["id"],
        "notice_type": notice_type,
        "effective_date": effective_raw,
        "reason": reason,
        "notice_days": notice_days,
        "etf_disclosed_cents": calc.etf_disclosure_amount(account,
                                                          source_plan),
        "disclosed_net_monthly_cents": disclosed_net,
        "source_plan_id": source_plan["id"],
        "state": "SENT",
        "acknowledged_at": None,
        "effected_at": None,
    })
    db.store.plan_change_notices[notice["id"]] = notice

    account["subscription_state"] = "PENDING_CHANGE"
    db.touch(account)

    return response.success(serializers.plan_change_notice(notice), 201)


@bp.route("/plan-change-notices/<notice_id>", methods=["GET"])
def read_plan_change_notice(notice_id):
    principal = authorize(*READ_ROLES)
    notice = lookup.plan_change_notice(notice_id)
    require_own_account(principal, notice["account_id"])
    return response.success(serializers.plan_change_notice(notice), 200)


@bp.route("/plan-change-notices", methods=["GET"])
def list_plan_change_notices():
    principal = authorize(*READ_ROLES)
    validators.pagination_params()
    account_id = request.args.get("account_id")
    target_plan_id = request.args.get("target_plan_id")
    state = request.args.get("state")

    if principal.is_subscriber:
        if account_id is not None and account_id != principal.user_id:
            fail(errors.ERR_ACCOUNT_SCOPE_VIOLATION)
        account_id = principal.user_id

    rows = [n for n in db.store.plan_change_notices.values()
            if (account_id is None or n["account_id"] == account_id)
            and (target_plan_id is None
                 or n["target_plan_id"] == target_plan_id)
            and (state is None or n["state"] == state)]
    items, meta = validators.paginate(db.ordered(rows),
                                      serializers.plan_change_notice)
    return response.success_list(items, meta, 200)


@bp.route("/plan-change-notices/<notice_id>/acknowledge", methods=["POST"])
def acknowledge_plan_change_notice(notice_id):
    principal = authorize(SUBSCRIBER)
    notice = lookup.plan_change_notice(notice_id)
    require_own_account(principal, notice["account_id"])

    if notice["state"] != "SENT":
        fail(errors.ERR_NOTICE_INVALID_STATE)

    notice["state"] = "ACKNOWLEDGED"
    notice["acknowledged_at"] = db.now_iso()
    db.touch(notice)
    return response.success(serializers.plan_change_notice(notice), 200)


@bp.route("/plan-change-notices/<notice_id>/effect", methods=["POST"])
def effect_plan_change_notice(notice_id):
    authorize(RETAIL_AGENT)
    notice = lookup.plan_change_notice(notice_id)

    if notice["state"] != "ACKNOWLEDGED":
        fail(errors.ERR_NOTICE_INVALID_STATE)

    effective = db.dt_of(notice, "effective_date")
    if effective is not None and db.now() < effective:
        fail(errors.ERR_NOTICE_NOT_DUE)

    notice["state"] = "EFFECTED"
    notice["effected_at"] = db.now_iso()
    db.touch(notice)

    account = db.store.subscriber_accounts.get(notice["account_id"])
    if account is not None:
        if notice["notice_type"] == "PLAN_CHANGE":
            account["plan_id"] = notice["target_plan_id"]
        account["subscription_state"] = "ACTIVE"
        db.touch(account)

    return response.success(serializers.plan_change_notice(notice), 200)
