"""Subscription endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from serialize import ser_subscription, pause_counters
from services import parse_d
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_int, req_enum, stamp_new, touch, parse_date, iso_d, clock_date, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_DUPLICATE_SUBSCRIPTION,
    ERR_CUSTOMER_SUSPENDED, ERR_PAUSE_LIMIT_EXCEEDED, ERR_PAUSE_DURATION_EXCEEDED,
)

bp = Blueprint("subscriptions", __name__)

CADENCES = {"WEEKLY", "BIWEEKLY", "MONTHLY"}


@bp.post("/fleet-wash/subscriptions")
def create_subscription():
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "Customer"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    if role == "Customer" and customer_id != uid:
        forbid("Customers may only create their own subscriptions")
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % customer_id)
    vehicle_id = req_str(body, "vehicle_id")
    if vehicle_id not in store.vehicles:
        raise ApiError(ERR_NOT_FOUND, "Vehicle %s not found" % vehicle_id)
    cadence = req_enum(body, "cadence", CADENCES)
    next_service = req_str(body, "next_service_date")
    parse_date(next_service, "next_service_date")
    for s in store.subscriptions.values():
        if s["vehicle_id"] == vehicle_id and s["status"] in ("ACTIVE", "PAUSED"):
            raise ApiError(ERR_DUPLICATE_SUBSCRIPTION,
                           "Vehicle already has an ACTIVE or PAUSED subscription")
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Customer is not ACTIVE")
    rec = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "cadence": cadence,
        "next_service_date": next_service,
        "status": "ACTIVE",
        "pauses": [],
    }
    stamp_new(rec)
    store.subscriptions[rec["id"]] = rec
    return respond(ser_subscription(rec), 201)


@bp.get("/fleet-wash/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = caller()
    rec = store.subscriptions.get(sid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Subscription %s not found" % sid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only access their own subscriptions")
    return respond(ser_subscription(rec), 200)


@bp.get("/fleet-wash/subscriptions")
def list_subscriptions():
    uid, role = caller()
    customer_id = request.args.get("customer_id")
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            forbid("Customers may only list their own subscriptions")
        customer_id = uid
    recs = list(store.subscriptions.values())
    if customer_id is not None:
        recs = [s for s in recs if s["customer_id"] == customer_id]
    if vehicle_id is not None:
        recs = [s for s in recs if s["vehicle_id"] == vehicle_id]
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    return paginate(recs, ser_subscription)


def _close_open_pause(sub):
    for p in sub["pauses"]:
        if p["ended_at"] is None:
            p["ended_at"] = clock_date()
            p["days"] = (clock_date() - p["started_at"]).days
            return p
    return None


@bp.post("/fleet-wash/subscriptions/<sid>/events")
def subscription_event(sid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "Customer"})
    rec = store.subscriptions.get(sid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Subscription %s not found" % sid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only manage their own subscriptions")
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("PAUSE", "RESUME", "CANCEL"):
        raise ApiError(ERR_VALIDATION, "event_type must be PAUSE, RESUME, or CANCEL")
    if event == "PAUSE":
        pause_days = req_int(body, "pause_days")
        if rec["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Subscription is not ACTIVE")
        count, days_used = pause_counters(rec)
        if count >= 2 or pause_days < 7:
            raise ApiError(ERR_PAUSE_LIMIT_EXCEEDED,
                           "Pause count limit reached or pause shorter than 7 days")
        if days_used + pause_days > 90:
            raise ApiError(ERR_PAUSE_DURATION_EXCEEDED,
                           "Paused days in the trailing 365 days would exceed 90")
        rec["pauses"].append({
            "started_at": clock_date(),
            "ended_at": None,
            "days": pause_days,
        })
        rec["status"] = "PAUSED"
    elif event == "RESUME":
        if rec["status"] != "PAUSED":
            raise ApiError(ERR_INVALID_STATE, "Subscription is not PAUSED")
        closed = _close_open_pause(rec)
        if closed is not None:
            new_date = parse_d(rec["next_service_date"]) + timedelta(days=closed["days"])
            rec["next_service_date"] = iso_d(new_date)
        rec["status"] = "ACTIVE"
    else:  # CANCEL
        if rec["status"] not in ("ACTIVE", "PAUSED"):
            raise ApiError(ERR_INVALID_STATE,
                           "Subscription is not ACTIVE or PAUSED")
        if rec["status"] == "PAUSED":
            _close_open_pause(rec)
        rec["status"] = "CANCELLED"
    touch(rec)
    return respond(ser_subscription(rec), 200)
