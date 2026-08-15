"""Plan catalog endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object, paginate
from util import new_uuid, stamp_new, touch

bp = Blueprint("plans", __name__)

TIERS = {"BASIC", "STANDARD", "PREMIUM"}


def plan_view(p):
    return p


@bp.route("/v1/plans", methods=["POST"])
def create_plan():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    required = ["plan_code", "display_name", "tier", "monthly_price_cents",
                "trial_days", "max_profiles", "max_households"]
    for f in required:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    if body["tier"] not in TIERS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid tier")
    for intf in ["monthly_price_cents", "trial_days", "max_profiles", "max_households"]:
        if not isinstance(body[intf], int):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"{intf} must be integer")
    # plan_code unique among active (non-archived) plans
    for p in db.plans.values():
        if p["plan_code"] == body["plan_code"] and not p["is_archived"]:
            raise ApiError("ERR_INVALID_REQUEST", 400, "plan_code already in use")
    plan = stamp_new({
        "plan_id": new_uuid(),
        "plan_code": body["plan_code"],
        "display_name": body["display_name"],
        "tier": body["tier"],
        "monthly_price_cents": body["monthly_price_cents"],
        "trial_days": body["trial_days"],
        "max_profiles": body["max_profiles"],
        "max_households": body["max_households"],
        "is_archived": False,
    })
    db.plans[plan["plan_id"]] = plan
    return success_object(plan_view(plan), 201)


@bp.route("/v1/plans", methods=["GET"])
def list_plans():
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    items = list(db.plans.values())
    tier = request.args.get("tier")
    is_archived = request.args.get("is_archived")
    if tier is not None:
        items = [p for p in items if p["tier"] == tier]
    if is_archived is not None:
        flag = is_archived.lower() == "true"
        items = [p for p in items if p["is_archived"] == flag]
    return paginate([plan_view(p) for p in items], request.args)


@bp.route("/v1/plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps", "Subscriber")
    plan = db.plans.get(pid)
    if not plan:
        raise ApiError("ERR_NOT_FOUND", 404, "plan not found")
    return success_object(plan_view(plan))


@bp.route("/v1/plans/<pid>/archive", methods=["POST"])
def archive_plan(pid):
    require_roles("PlatformAdmin")
    plan = db.plans.get(pid)
    if not plan:
        raise ApiError("ERR_NOT_FOUND", 404, "plan not found")
    plan["is_archived"] = True
    touch(plan)
    return success_object(plan_view(plan))
