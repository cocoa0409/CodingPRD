"""WashOrder endpoints: booking, lifecycle events, reschedule, rewash."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from serialize import ser_order, ser_stop
from services import (
    wash_quote_cents, order_stop, cancel_order, complete_order, hold_order,
    create_rewash_order, has_open_rewash, active_contract_for,
)
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_str_list, opt_str, opt_bool, opt_int, req_int, stamp_new, touch, now,
    clock_date, parse_dt, ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_CONTAINMENT_REQUIRED, ERR_SITE_WINDOW_CONFLICT, ERR_CUSTOMER_SUSPENDED,
    ERR_SITE_SUSPENDED, ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_CONTRACT_NOT_ACTIVE,
    ERR_INSPECTION_REQUIRED, ERR_REWASH_WINDOW_EXPIRED, ERR_REWASH_IN_PROGRESS,
    ERR_RESCHEDULE_WINDOW_EXPIRED,
)

bp = Blueprint("orders", __name__)

ORDER_EVENTS = ("CONFIRM", "START", "COMPLETE", "CANCEL", "WEATHER_HOLD")
WINDOW_STATES = ("SCHEDULED", "ASSIGNED", "IN_PROGRESS")


def window_conflict(site_id, start, end, exclude_order_id=None):
    """Half-open [start, end) overlap with active orders at the site."""
    for o in store.orders.values():
        if o["site_id"] != site_id or o["id"] == exclude_order_id:
            continue
        if o["status"] in WINDOW_STATES:
            if start < o["scheduled_window_end"] and o["scheduled_window_start"] < end:
                return True
    return False


def _get_order_or_404(oid):
    rec = store.orders.get(oid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "WashOrder %s not found" % oid)
    return rec


@bp.post("/fleet-wash/wash-orders")
def create_order():
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    if role == "Customer" and customer_id != uid:
        forbid("Customers may only book their own wash orders")
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % customer_id)
    site_id = req_str(body, "site_id")
    site = store.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_NOT_FOUND, "Site %s not found" % site_id)
    vehicle_ids = req_str_list(body, "vehicle_ids")
    if len(vehicle_ids) == 0:
        raise ApiError(ERR_VALIDATION, "vehicle_ids must be non-empty")
    for vid in vehicle_ids:
        if vid not in store.vehicles:
            raise ApiError(ERR_NOT_FOUND, "Vehicle %s not found" % vid)
    subscription_id = opt_str(body, "subscription_id")
    subscription = None
    if subscription_id is not None:
        subscription = store.subscriptions.get(subscription_id)
        if subscription is None:
            raise ApiError(ERR_NOT_FOUND, "Subscription %s not found" % subscription_id)
    start = parse_dt(body.get("scheduled_window_start"), "scheduled_window_start")
    end = parse_dt(body.get("scheduled_window_end"), "scheduled_window_end")
    if end <= start:
        raise ApiError(ERR_VALIDATION,
                       "scheduled_window_end must be strictly after scheduled_window_start")
    requires_inspection = opt_bool(body, "requires_inspection", False)
    for vid in vehicle_ids:
        if store.vehicles[vid]["customer_id"] != customer_id:
            raise ApiError(ERR_VALIDATION,
                           "Every vehicle must belong to customer_id")
    if subscription is not None and subscription["vehicle_id"] not in vehicle_ids:
        raise ApiError(ERR_VALIDATION,
                       "subscription_id must cover one of vehicle_ids")
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Customer is not ACTIVE")
    classes = [store.vehicles[vid]["vehicle_class"] for vid in vehicle_ids]
    quote = wash_quote_cents(customer_id, site, classes)
    rec = {
        "customer_id": customer_id,
        "site_id": site_id,
        "subscription_id": subscription_id,
        "vehicle_ids": list(vehicle_ids),
        "scheduled_window_start": start,
        "scheduled_window_end": end,
        "requires_inspection": requires_inspection,
        "status": "DRAFT",
        "billing_status": "UNBILLED",
        "quote_cents": quote,
        "final_cents": None,
        "vehicles_washed_ids": None,
        "rewash_of_id": None,
        "hold_reason": None,
        "held_at": None,
        "cancel_reason": None,
        "completed_at": None,
    }
    stamp_new(rec)
    store.orders[rec["id"]] = rec
    return respond(ser_order(rec), 201)


@bp.get("/fleet-wash/wash-orders/<oid>")
def get_order(oid):
    uid, role = caller()
    rec = _get_order_or_404(oid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only access their own wash orders")
    return respond(ser_order(rec), 200)


@bp.get("/fleet-wash/wash-orders")
def list_orders():
    uid, role = caller()
    customer_id = request.args.get("customer_id")
    site_id = request.args.get("site_id")
    subscription_id = request.args.get("subscription_id")
    rewash_of_id = request.args.get("rewash_of_id")
    status = request.args.get("status")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            forbid("Customers may only list their own wash orders")
        customer_id = uid
    recs = list(store.orders.values())
    if customer_id is not None:
        recs = [o for o in recs if o["customer_id"] == customer_id]
    if site_id is not None:
        recs = [o for o in recs if o["site_id"] == site_id]
    if subscription_id is not None:
        recs = [o for o in recs if o["subscription_id"] == subscription_id]
    if rewash_of_id is not None:
        recs = [o for o in recs if o["rewash_of_id"] == rewash_of_id]
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return paginate(recs, ser_order)


def _check_event_actor(order, event, uid, role):
    """Per-event role and ownership checks (403 on failure)."""
    if event in ("CONFIRM", "CANCEL"):
        if role == "Dispatcher":
            return
        if role == "Customer" and order["customer_id"] == uid:
            return
        forbid("%s requires the owning Customer or a Dispatcher" % event)
    if event == "WEATHER_HOLD":
        if role != "Dispatcher":
            forbid("WEATHER_HOLD requires a Dispatcher")
        return
    if event in ("START", "COMPLETE"):
        if role != "Technician":
            forbid("%s requires the route's lead Technician" % event)
        stop = order_stop(order["id"])
        if stop is not None:
            route = store.routes.get(stop["route_id"])
            if route is not None and route["lead_technician_id"] != uid:
                forbid("Technician is not the lead of the route holding this order")


def _confirm(order):
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "WashOrder is not DRAFT")
    site = store.sites[order["site_id"]]
    if site["water_reclaim_required"] and site["containment_type"] == "NONE":
        raise ApiError(ERR_CONTAINMENT_REQUIRED,
                       "Site requires reclamation but has no containment")
    if window_conflict(order["site_id"], order["scheduled_window_start"],
                       order["scheduled_window_end"], exclude_order_id=order["id"]):
        raise ApiError(ERR_SITE_WINDOW_CONFLICT,
                       "Window overlaps another active order at this site")
    customer = store.customers[order["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Customer is not ACTIVE")
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_SUSPENDED, "Site is not ACTIVE")
    if order["subscription_id"] is not None:
        sub = store.subscriptions[order["subscription_id"]]
        if sub["status"] != "ACTIVE":
            raise ApiError(ERR_SUBSCRIPTION_NOT_ACTIVE,
                           "Subscription is not ACTIVE")
    if customer["customer_type"] == "FLEET":
        if active_contract_for(customer["id"]) is None:
            raise ApiError(ERR_CONTRACT_NOT_ACTIVE,
                           "FLEET customer has no ACTIVE FleetContract")
    order["status"] = "SCHEDULED"
    touch(order)


def _start(order):
    if order["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, "WashOrder is not ASSIGNED")
    stop = order_stop(order["id"])
    if stop is None or stop["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, "The order's stop is not ARRIVED")
    if order["requires_inspection"]:
        submitted = any(
            r["wash_order_id"] == order["id"] and r["status"] == "SUBMITTED"
            for r in store.reports.values())
        if not submitted:
            raise ApiError(ERR_INSPECTION_REQUIRED,
                           "A SUBMITTED InspectionReport is required before START")
    site = store.sites[order["site_id"]]
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_SITE_SUSPENDED, "Site is not ACTIVE")
    order["status"] = "IN_PROGRESS"
    touch(order)


@bp.post("/fleet-wash/wash-orders/<oid>/events")
def order_event(oid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer", "Technician"})
    order = _get_order_or_404(oid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ORDER_EVENTS:
        raise ApiError(ERR_VALIDATION, "event_type must be one of %s" % list(ORDER_EVENTS))
    washed = None
    if event == "COMPLETE":
        washed = req_str_list(body, "vehicles_washed_ids")
        if len(washed) == 0:
            raise ApiError(ERR_VALIDATION, "vehicles_washed_ids must be non-empty")
        if not all(v in order["vehicle_ids"] for v in washed):
            raise ApiError(ERR_VALIDATION,
                           "vehicles_washed_ids must be a subset of vehicle_ids")
    _check_event_actor(order, event, uid, role)
    if event == "CONFIRM":
        _confirm(order)
    elif event == "START":
        _start(order)
    elif event == "COMPLETE":
        if order["status"] != "IN_PROGRESS":
            raise ApiError(ERR_INVALID_STATE, "WashOrder is not IN_PROGRESS")
        complete_order(order, washed)
    elif event == "CANCEL":
        if order["status"] not in ("DRAFT", "SCHEDULED", "ASSIGNED", "WEATHER_HELD"):
            raise ApiError(ERR_INVALID_STATE,
                           "WashOrder cannot be cancelled from %s" % order["status"])
        reason = "CUSTOMER_REQUEST" if role == "Customer" else "DISPATCH"
        cancel_order(order, reason)
    else:  # WEATHER_HOLD
        if order["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, "WashOrder is not SCHEDULED")
        hold_order(order)
    return respond(ser_order(order), 200)


@bp.post("/fleet-wash/wash-orders/<oid>/reschedule")
def reschedule_order(oid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Customer"})
    order = _get_order_or_404(oid)
    if role == "Customer" and order["customer_id"] != uid:
        forbid("Customers may only reschedule their own wash orders")
    body = get_body()
    start = parse_dt(body.get("scheduled_window_start"), "scheduled_window_start")
    end = parse_dt(body.get("scheduled_window_end"), "scheduled_window_end")
    if end <= start:
        raise ApiError(ERR_VALIDATION,
                       "scheduled_window_end must be strictly after scheduled_window_start")
    expected = req_int(body, "expected_wash_order_version")
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_wash_order_version does not match current version")
    if order["status"] not in ("SCHEDULED", "WEATHER_HELD"):
        raise ApiError(ERR_INVALID_STATE,
                       "WashOrder is not SCHEDULED or WEATHER_HELD")
    if window_conflict(order["site_id"], start, end, exclude_order_id=order["id"]):
        raise ApiError(ERR_SITE_WINDOW_CONFLICT,
                       "Window overlaps another active order at this site")
    if order["status"] == "WEATHER_HELD":
        if clock_date() > order["held_at"].date() + timedelta(days=14):
            raise ApiError(ERR_RESCHEDULE_WINDOW_EXPIRED,
                           "More than 14 days have passed since the weather hold")
    order["scheduled_window_start"] = start
    order["scheduled_window_end"] = end
    if order["status"] == "WEATHER_HELD":
        order["status"] = "SCHEDULED"
        order["hold_reason"] = None
        order["held_at"] = None
    touch(order)
    return respond(ser_order(order), 200)


@bp.post("/fleet-wash/wash-orders/<oid>/rewash")
def rewash_order(oid):
    uid, role = caller()
    require_role(role, {"Customer"})
    order = _get_order_or_404(oid)
    if order["customer_id"] != uid:
        forbid("Customers may only request rewashes of their own wash orders")
    if order["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, "WashOrder is not COMPLETED")
    if now() > order["completed_at"] + timedelta(hours=72):
        raise ApiError(ERR_REWASH_WINDOW_EXPIRED,
                       "More than 72 hours have passed since completion")
    if has_open_rewash(order["id"]):
        raise ApiError(ERR_REWASH_IN_PROGRESS,
                       "Another rewash of this order is still open")
    rewash = create_rewash_order(order)
    order["status"] = "REWASH_PENDING"
    touch(order)
    return respond(ser_order(rewash), 201)


@bp.get("/fleet-wash/wash-orders/<oid>/route-stops")
def list_order_stops(oid):
    uid, role = caller()
    order = _get_order_or_404(oid)
    if role == "Customer" and order["customer_id"] != uid:
        forbid("Customers may only access their own wash orders")
    recs = [s for s in store.stops.values() if s["wash_order_id"] == oid]
    return paginate(recs, ser_stop)
