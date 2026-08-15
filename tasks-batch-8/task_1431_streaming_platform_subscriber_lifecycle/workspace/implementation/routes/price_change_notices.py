"""Price change notice endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object, paginate
from util import new_uuid, stamp_new, touch, parse_iso

bp = Blueprint("price_change_notices", __name__)


@bp.route("/v1/price-change-notices", methods=["POST"])
def create_notice():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    for f in ["plan_id", "old_price_cents", "new_price_cents", "effective_at_utc",
              "grandfather_period_months"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    plan = db.plans.get(body["plan_id"])
    if not plan:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "plan not found")
    try:
        effective = parse_iso(body["effective_at_utc"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid effective_at_utc")
    now = db.get_now()
    # Effective at least 30 days after announcement
    if (effective - now).total_seconds() < 30 * 86400:
        raise ApiError("ERR_PRICE_CHANGE_NOTICE_TOO_SHORT", 422,
                       "effective date < 30 days after announcement")
    notice = stamp_new({
        "price_change_notice_id": new_uuid(),
        "plan_id": body["plan_id"],
        "old_price_cents": body["old_price_cents"],
        "new_price_cents": body["new_price_cents"],
        "announced_at_utc": notice_ts(now),
        "effective_at_utc": body["effective_at_utc"],
        "notice_status": "ANNOUNCED",
        "grandfather_period_months": body["grandfather_period_months"],
    })
    db.price_change_notices[notice["price_change_notice_id"]] = notice
    # Link subscriptions on this plan to the latest notice
    for sub in db.subscriptions.values():
        if sub["plan_id"] == plan["plan_id"] and sub["subscription_status"] in (
                "TRIALING", "ACTIVE", "PAST_DUE"):
            sub["price_change_notice_id"] = notice["price_change_notice_id"]
            touch(sub)
    return success_object(notice, 201)


def notice_ts(dt):
    from util import format_ts
    return format_ts(dt)


@bp.route("/v1/price-change-notices", methods=["GET"])
def list_notices():
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    items = list(db.price_change_notices.values())
    for f in ["plan_id", "notice_status"]:
        v = request.args.get(f)
        if v is not None:
            items = [n for n in items if str(n.get(f)) == v]
    return paginate(items, request.args)


@bp.route("/v1/price-change-notices/<nid>", methods=["GET"])
def get_notice(nid):
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    n = db.price_change_notices.get(nid)
    if not n:
        raise ApiError("ERR_NOT_FOUND", 404, "notice not found")
    return success_object(n)


@bp.route("/v1/price-change-notices/<nid>/cancel", methods=["POST"])
def cancel_notice(nid):
    require_roles("PlatformAdmin")
    n = db.price_change_notices.get(nid)
    if not n:
        raise ApiError("ERR_NOT_FOUND", 404, "notice not found")
    if n["notice_status"] != "ANNOUNCED":
        raise ApiError("ERR_INVALID_STATE", 409, "Notice not ANNOUNCED")
    if db.get_now() >= parse_iso(n["effective_at_utc"]):
        raise ApiError("ERR_OFFER_EXPIRED", 422, "Notice already effective")
    n["notice_status"] = "CANCELLED"
    touch(n)
    return success_object(n)
