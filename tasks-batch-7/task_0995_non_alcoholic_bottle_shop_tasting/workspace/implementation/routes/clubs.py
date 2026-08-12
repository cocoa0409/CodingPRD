"""ClubPlan and ClubSubscription endpoints."""
from flask import Blueprint, request

import clock
import db as _db
from db import db, new_entity, touch
from errors import (ApiError, duplicate, invalid_request, invalid_state,
                    not_found, stale_version)
from helpers import (body, get_or_404, opt_int, opt_str, paginate,
                     pagination_params, public, req_date, req_enum, req_int,
                     req_list, req_str)
from middleware import require, require_member_ownership
from response import success
from services import (CADENCE_MONTHS, add_months, advance_billing,
                      recompute_plan_count, _parse_date)

bp = Blueprint("clubs", __name__)

READ_ROLES = ["PlatformAdmin", "ShopStaff", "Member", "Anonymous"]


# ---------------------------------------------------------------------------
# Club plans
# ---------------------------------------------------------------------------

@bp.post("/club-plans")
def create_plan():
    require(["PlatformAdmin"])
    data = body()
    code = req_str(data, "code")
    cadence = req_enum(data, "cadence", set(CADENCE_MONTHS.keys()))
    bottles = req_int(data, "bottles_per_shipment", min_v=1)
    price = req_int(data, "price_cents_per_cycle", min_v=0)
    allowed = req_list(data, "allowed_category_ids")
    for cid in allowed:
        if not isinstance(cid, str):
            raise invalid_request("allowed_category_ids must be strings")
        get_or_404(db["categories"], cid)
    discount_bps = req_int(data, "discount_bps_on_retail", min_v=0, max_v=5000)
    max_active = req_int(data, "max_active_subscriptions", min_v=1)
    for plan in db["club_plans"].values():
        if plan["code"] == code:
            raise duplicate("ClubPlan code already exists")
    ent = new_entity({
        "code": code,
        "cadence": cadence,
        "bottles_per_shipment": bottles,
        "price_cents_per_cycle": price,
        "allowed_category_ids": allowed,
        "discount_bps_on_retail": discount_bps,
        "max_active_subscriptions": max_active,
        "active_subscription_count": 0,
    })
    db["club_plans"][ent["id"]] = ent
    return success(public(ent), status=201)


@bp.get("/club-plans")
def list_plans():
    require(READ_ROLES)
    limit, offset = pagination_params()
    page, pg = paginate(list(db["club_plans"].values()), limit, offset)
    return success([public(p) for p in page], response_type="array",
                   pagination=pg)


@bp.get("/club-plans/<pid>")
def get_plan(pid):
    require(READ_ROLES)
    ent = get_or_404(db["club_plans"], pid)
    return success(public(ent))


@bp.get("/club-plans/<pid>/subscriptions")
def plan_subscriptions(pid):
    require(["PlatformAdmin", "ShopStaff"])
    get_or_404(db["club_plans"], pid)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = [s for s in db["club_subscriptions"].values() if s["plan_id"] == pid]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)


# ---------------------------------------------------------------------------
# Club subscriptions
# ---------------------------------------------------------------------------

@bp.post("/club-subscriptions")
def create_subscription():
    role, uid = require(["Member", "ShopStaff", "PlatformAdmin"])
    data = body()
    # FK existence (priority 3)
    plan_id = data.get("plan_id")
    member_id = data.get("member_id")
    if plan_id is not None and isinstance(plan_id, str):
        get_or_404(db["club_plans"], plan_id)
    if member_id is not None and isinstance(member_id, str):
        get_or_404(db["members"], member_id)
    plan_id = req_str(data, "plan_id")
    member_id = req_str(data, "member_id")
    plan = get_or_404(db["club_plans"], plan_id)
    member = get_or_404(db["members"], member_id)
    if role == "Member" and uid != member_id:
        from errors import unauthorized
        raise unauthorized("Member may only subscribe self")
    started_on = req_date(data, "started_on")
    trial_days = opt_int(data, "trial_days", 0, min_v=0)
    expected = data.get("expected_plan_version")
    # capacity (priority 11)
    if plan["active_subscription_count"] >= plan["max_active_subscriptions"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                       "ClubPlan active_subscription_count at capacity")
    # OCC (priority 19)
    if expected is not None and expected != plan["version"]:
        raise stale_version()
    status = "TRIALING" if (trial_days or 0) > 0 else "ACTIVE"
    start_d = _parse_date(started_on)
    months = CADENCE_MONTHS[plan["cadence"]]
    next_billing = add_months(start_d, months)
    ent = new_entity({
        "plan_id": plan_id,
        "member_id": member_id,
        "status": status,
        "started_on": started_on,
        "trial_days": trial_days or 0,
        "next_billing_on": next_billing.isoformat(),
        "failed_billing_count": 0,
        "shipments_fulfilled": 0,
        "pause_reason": None,
    })
    db["club_subscriptions"][ent["id"]] = ent
    plan["active_subscription_count"] += 1
    touch(plan)
    return success(public(ent), status=201)


@bp.get("/club-subscriptions/<sid>")
def get_subscription(sid):
    role, uid = require(["PlatformAdmin", "ShopStaff", "Member"])
    ent = get_or_404(db["club_subscriptions"], sid)
    require_member_ownership(role, uid, ent["member_id"])
    return success(public(ent))


def _sub_action(sid, allowed_from, actor_check=True):
    role, uid = require(["Member", "ShopStaff"])
    sub = get_or_404(db["club_subscriptions"], sid)
    if role == "Member" and uid != sub["member_id"]:
        from errors import unauthorized
        raise unauthorized("Member may only act on own subscription")
    if sub["status"] not in allowed_from:
        raise invalid_state("Subscription state does not permit this action")
    return role, uid, sub


@bp.post("/club-subscriptions/<sid>/pause")
def pause_subscription(sid):
    role, uid, sub = _sub_action(sid, {"ACTIVE"})
    data = body()
    sub["pause_reason"] = opt_str(data, "pause_reason")
    sub["status"] = "PAUSED"
    touch(sub)
    plan = db["club_plans"].get(sub["plan_id"])
    if plan is not None:
        recompute_plan_count(plan)
    return success(public(sub))


@bp.post("/club-subscriptions/<sid>/resume")
def resume_subscription(sid):
    role, uid, sub = _sub_action(sid, {"PAUSED"})
    plan = db["club_plans"].get(sub["plan_id"])
    months = CADENCE_MONTHS[plan["cadence"]] if plan is not None else 1
    start_d = _parse_date(sub["started_on"])
    today = clock.today()
    candidate = start_d
    while candidate < today:
        candidate = add_months(candidate, months)
    sub["next_billing_on"] = candidate.isoformat()
    sub["status"] = "ACTIVE"
    sub["pause_reason"] = None
    touch(sub)
    if plan is not None:
        recompute_plan_count(plan)
    return success(public(sub))


@bp.post("/club-subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    role, uid, sub = _sub_action(sid, {"TRIALING", "ACTIVE", "PAST_DUE", "PAUSED"})
    sub["status"] = "CANCELLED"
    touch(sub)
    plan = db["club_plans"].get(sub["plan_id"])
    if plan is not None:
        recompute_plan_count(plan)
    return success(public(sub))


@bp.get("/club-subscriptions/<sid>/shipments")
def subscription_shipments(sid):
    role, uid = require(["PlatformAdmin", "ShopStaff", "Member"])
    sub = get_or_404(db["club_subscriptions"], sid)
    require_member_ownership(role, uid, sub["member_id"])
    limit, offset = pagination_params()
    items = [s for s in db["shipments"].values()
             if s.get("club_subscription_id") == sid]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)


@bp.get("/club-subscriptions/<sid>/orders")
def subscription_orders(sid):
    role, uid = require(["PlatformAdmin", "ShopStaff", "Member"])
    sub = get_or_404(db["club_subscriptions"], sid)
    require_member_ownership(role, uid, sub["member_id"])
    limit, offset = pagination_params()
    items = [o for o in db["orders"].values()
             if o.get("applied_club_subscription_id") == sid]
    page, pg = paginate(items, limit, offset)
    return success([public(o) for o in page], response_type="array",
                   pagination=pg)
