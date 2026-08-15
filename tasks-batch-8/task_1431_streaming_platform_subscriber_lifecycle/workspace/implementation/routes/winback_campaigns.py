"""Win-back campaign endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object, paginate
from util import new_uuid, stamp_new, touch

bp = Blueprint("winback_campaigns", __name__)

VALID_REASONS = {"USER_REQUESTED", "PAYMENT_FAILED", "PRICE_REFUSAL", "WINBACK_EXPIRED", "ADMIN"}


@bp.route("/v1/winback-campaigns", methods=["POST"])
def create_campaign():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    for f in ["campaign_code", "discount_pct", "duration_months",
              "min_days_since_cancel", "max_days_since_cancel", "eligible_cancel_reasons"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    if not isinstance(body["eligible_cancel_reasons"], list) or \
       any(r not in VALID_REASONS for r in body["eligible_cancel_reasons"]):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid eligible_cancel_reasons")
    # campaign_code unique among DRAFT/ACTIVE
    for c in db.winback_campaigns.values():
        if c["campaign_code"] == body["campaign_code"] and c["campaign_status"] in ("DRAFT", "ACTIVE"):
            raise ApiError("ERR_INVALID_REQUEST", 400, "campaign_code already in use")
    c = stamp_new({
        "winback_campaign_id": new_uuid(),
        "campaign_code": body["campaign_code"],
        "discount_pct": body["discount_pct"],
        "duration_months": body["duration_months"],
        "min_days_since_cancel": body["min_days_since_cancel"],
        "max_days_since_cancel": body["max_days_since_cancel"],
        "eligible_cancel_reasons": body["eligible_cancel_reasons"],
        "campaign_status": "DRAFT",
    })
    db.winback_campaigns[c["winback_campaign_id"]] = c
    return success_object(c, 201)


@bp.route("/v1/winback-campaigns", methods=["GET"])
def list_campaigns():
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    items = list(db.winback_campaigns.values())
    v = request.args.get("campaign_status")
    if v is not None:
        items = [c for c in items if c["campaign_status"] == v]
    return paginate(items, request.args)


def _get(cid):
    c = db.winback_campaigns.get(cid)
    if not c:
        raise ApiError("ERR_NOT_FOUND", 404, "campaign not found")
    return c


@bp.route("/v1/winback-campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    return success_object(_get(cid))


@bp.route("/v1/winback-campaigns/<cid>/activate", methods=["POST"])
def activate_campaign(cid):
    require_roles("PlatformAdmin")
    c = _get(cid)
    if c["campaign_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign not DRAFT")
    c["campaign_status"] = "ACTIVE"
    touch(c)
    return success_object(c)


@bp.route("/v1/winback-campaigns/<cid>/close", methods=["POST"])
def close_campaign(cid):
    require_roles("PlatformAdmin")
    c = _get(cid)
    if c["campaign_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Campaign not ACTIVE")
    c["campaign_status"] = "CLOSED"
    touch(c)
    return success_object(c)
