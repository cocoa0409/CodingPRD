"""Subscription billing lifecycle — PRD §3.2."""

from flask import Blueprint, request

from db import db, common_fields, now, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import calc, core
import validation as v

bp = Blueprint("subscriptions", __name__)


@bp.post("/api/subscriptions")
def create_subscription():
    auth("PlatformAdmin")
    data = v.body()
    artist_id = v.req_id(data, "artist_id")
    plan_id = v.req_id(data, "plan_id")
    auto_renew, has_ar = v.opt_bool(data, "auto_renew")

    core.find_artist(artist_id)
    core.find_plan(plan_id)

    row = common_fields()
    row.update({
        "artist_id": artist_id,
        "plan_id": plan_id,
        "status": "PENDING",
        "activated_at": None,
        "past_due_since": None,
        "releases_used": 0,
        "auto_renew": auto_renew if has_ar else True,
    })
    db.subscriptions[row["id"]] = row
    return created(row)


@bp.get("/api/subscriptions/<subscription_id>")
def read_subscription(subscription_id):
    user_id, role = auth("PlatformAdmin", "Artist", "FinanceOps")
    subscription = core.find_subscription(subscription_id)
    if role == "Artist":
        require_ownership(user_id == subscription["artist_id"])
    return ok(subscription)


@bp.get("/api/subscriptions")
def list_subscriptions():
    user_id, role = auth("PlatformAdmin", "Artist", "FinanceOps")
    limit, offset = read_pagination(request.args)
    rows = list(db.subscriptions.values())
    if role == "Artist":
        rows = [r for r in rows if r["artist_id"] == user_id]
    artist_id = request.args.get("artist_id")
    if artist_id is not None:
        rows = [r for r in rows if r["artist_id"] == artist_id]
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/api/subscriptions/<subscription_id>/activate")
def activate_subscription(subscription_id):
    auth("PlatformAdmin")
    data = v.body()
    v.req_string(data, "payment_reference")

    subscription = core.find_subscription(subscription_id)
    if subscription["status"] == "PENDING":
        artist = db.artists.get(subscription["artist_id"])
        if artist is None or artist["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "The owning artist is not ACTIVE.")
    elif subscription["status"] != "PAST_DUE":
        raise ApiError("ERR_INVALID_STATE")

    subscription["status"] = "ACTIVE"
    subscription["activated_at"] = now()
    subscription["past_due_since"] = None
    calc.recompute_releases_used(subscription, bump=False)
    touch(subscription)
    return ok(subscription)


@bp.post("/api/subscriptions/<subscription_id>/lapse")
def lapse_subscription(subscription_id):
    auth("PlatformAdmin")
    subscription = core.find_subscription(subscription_id)
    if subscription["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    subscription["status"] = "PAST_DUE"
    subscription["past_due_since"] = now()
    touch(subscription)
    return ok(subscription)


@bp.post("/api/subscriptions/<subscription_id>/expire")
def expire_subscription(subscription_id):
    auth("PlatformAdmin")
    subscription = core.find_subscription(subscription_id)
    if subscription["status"] == "PAST_DUE":
        subscription["status"] = "EXPIRED"
    elif subscription["status"] == "ACTIVE" and subscription["auto_renew"] is False:
        subscription["status"] = "CANCELLED"
    else:
        raise ApiError("ERR_INVALID_STATE")
    touch(subscription)
    return ok(subscription)
