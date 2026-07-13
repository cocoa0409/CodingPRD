"""Media plans and the insertion-order budget ledger (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import response
import services
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("media", __name__)

MEDIA_READ_ROLES = ["AgencyAdmin", "AccountManager", "MediaBuyer", "ClientReviewer"]

_HOLDING_STATUSES = ("RESERVED", "PLACED", "DELIVERED")


# --- MediaPlan --------------------------------------------------------------
@bp.post("/media-plans")
@endpoint(["MediaBuyer"])
def create_media_plan():
    b = validate.body()
    campaign_id = validate.req_str(b, "campaign_id")
    budget = validate.req_int(b, "approved_budget_cents", minimum=0)
    channels = validate.req_channels(b, "allowed_channels")

    services.must("campaign", campaign_id)

    obj = db.base_entity()
    obj.update(
        {
            "campaign_id": campaign_id,
            "approved_budget_cents": budget,
            "allowed_channels": channels,
            "uncommitted_cents": budget,
            "status": "DRAFT",
        }
    )
    db.MEDIA_PLANS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/media-plans/<pid>")
@endpoint(MEDIA_READ_ROLES)
def get_media_plan(pid):
    return response.ok(db.public(services.must("media_plan", pid)))


@bp.get("/media-plans")
@endpoint(MEDIA_READ_ROLES)
def list_media_plans():
    limit, offset = validate.pagination()
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    rows = db.ordered(db.MEDIA_PLANS)
    if campaign_id:
        rows = [p for p in rows if p["campaign_id"] == campaign_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    return response.listing(rows, limit, offset)


@bp.post("/media-plans/<pid>/approve")
@endpoint(["ClientReviewer"])
def approve_media_plan(pid):
    plan = services.must("media_plan", pid)
    campaign = services.must("campaign", plan["campaign_id"])
    services.must_own_client(campaign["client_id"])

    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    services.campaign_gate(campaign)

    plan["status"] = "APPROVED"
    services.touch(plan)
    return response.ok(db.public(plan))


# --- InsertionOrder ---------------------------------------------------------
@bp.post("/insertion-orders")
@endpoint(["MediaBuyer"])
def create_insertion_order():
    b = validate.body()
    plan_id = validate.req_str(b, "media_plan_id")
    placement_id = validate.req_str(b, "placement_id")
    flight_start = validate.req_datetime(b, "flight_start")
    flight_end = validate.req_datetime(b, "flight_end")
    gross = validate.req_int(b, "gross_cents", minimum=1)
    expected_version = validate.req_int(b, "expected_media_plan_version")
    if flight_end < flight_start:
        validate.bad("flight_end must be on or after flight_start.")

    # Priority 6: body FKs in declared order.
    plan = services.must("media_plan", plan_id)
    placement = services.must("placement", placement_id)

    # Priority 9: the stale-version guard.
    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_MEDIA_PLAN_VERSION")

    # Priority 14: the slot's channel must be whitelisted on the plan.
    if placement["channel"] not in plan["allowed_channels"]:
        raise ApiError("ERR_PLACEMENT_NOT_ELIGIBLE")

    # Priority 15: closed-interval flight conflict, widened by the dark-day buffer.
    start_d = flight_start.date()
    end_d = flight_end.date()
    buffer = timedelta(days=placement["min_dark_days"])
    for other in db.INSERTION_ORDERS.values():
        if other["placement_id"] != placement_id or other["status"] not in _HOLDING_STATUSES:
            continue
        if start_d <= other["_flight_end"] + buffer and other["_flight_start"] <= end_d + buffer:
            raise ApiError("ERR_PLACEMENT_FLIGHT_CONFLICT")

    # Priority 17: the money must be there (exactly equal passes).
    if gross > plan["uncommitted_cents"]:
        raise ApiError("ERR_MEDIA_BUDGET_EXCEEDED")

    obj = db.base_entity()
    obj.update(
        {
            "media_plan_id": plan_id,
            "placement_id": placement_id,
            "flight_start": b["flight_start"],
            "flight_end": b["flight_end"],
            "gross_cents": gross,
            "delivered_impressions": 0,
            "delivered_spend_cents": 0,
            "status": "RESERVED",
            "_flight_start": start_d,
            "_flight_end": end_d,
        }
    )
    db.INSERTION_ORDERS[obj["id"]] = obj

    plan["uncommitted_cents"] -= gross
    services.touch(plan)
    return response.created(db.public(obj))


@bp.get("/insertion-orders/<oid>")
@endpoint(MEDIA_READ_ROLES)
def get_insertion_order(oid):
    return response.ok(db.public(services.must("insertion_order", oid)))


@bp.get("/insertion-orders")
@endpoint(MEDIA_READ_ROLES)
def list_insertion_orders():
    limit, offset = validate.pagination()
    plan_id = request.args.get("media_plan_id")
    placement_id = request.args.get("placement_id")
    status = request.args.get("status")
    rows = db.ordered(db.INSERTION_ORDERS)
    if plan_id:
        rows = [o for o in rows if o["media_plan_id"] == plan_id]
    if placement_id:
        rows = [o for o in rows if o["placement_id"] == placement_id]
    if status:
        rows = [o for o in rows if o["status"] == status]
    return response.listing(rows, limit, offset)


@bp.post("/insertion-orders/<oid>/place")
@endpoint(["MediaBuyer"])
def place_insertion_order(oid):
    order = services.must("insertion_order", oid)
    if order["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE")
    plan = services.must("media_plan", order["media_plan_id"])
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_MEDIA_PLAN_NOT_APPROVED")

    order["status"] = "PLACED"
    services.touch(order)
    return response.ok(db.public(order))


@bp.post("/insertion-orders/<oid>/cancel")
@endpoint(["MediaBuyer"])
def cancel_insertion_order(oid):
    order = services.must("insertion_order", oid)
    if order["status"] not in ("RESERVED", "PLACED"):
        raise ApiError("ERR_INVALID_STATE")

    order["status"] = "CANCELLED"
    services.touch(order)

    plan = db.MEDIA_PLANS.get(order["media_plan_id"])
    if plan is not None:
        plan["uncommitted_cents"] += order["gross_cents"]
        services.touch(plan)
    return response.ok(db.public(order))


@bp.post("/insertion-orders/<oid>/deliver")
@endpoint(["MediaBuyer"])
def deliver_insertion_order(oid):
    b = validate.body()
    impressions = validate.req_int(b, "delivered_impressions", minimum=0)
    spend = validate.req_int(b, "delivered_spend_cents", minimum=0)

    order = services.must("insertion_order", oid)
    if order["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE")

    order["delivered_impressions"] = impressions
    order["delivered_spend_cents"] = spend
    order["status"] = "DELIVERED"
    services.touch(order)
    return response.ok(db.public(order))
