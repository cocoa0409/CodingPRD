from datetime import timedelta

from flask import Blueprint, request

import services as svc
from clock import now
from errors import ApiError, err_invalid_request, err_invalid_state, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    optional,
    require_dt,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("visits", __name__)

BUFFER = timedelta(minutes=15)
MIN_WINDOW = timedelta(minutes=30)


def _check_window_conflict(route, ws, we, exclude_visit_id=None):
    """Priority 15: existing visits on the same route expanded +/-15min,
    half-open intersection [ws, we) vs [es-15, ee+15)."""
    for v in svc.route_visits(route["id"]):
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        if v["status"] in svc.TERMINAL_VISIT_STATES:
            continue
        es = v["scheduled_window_start"] - BUFFER
        ee = v["scheduled_window_end"] + BUFFER
        if ws < ee and es < we:
            raise ApiError("ERR_VISIT_WINDOW_CONFLICT", 409,
                           "Visit window conflicts with an existing visit on this route")


def _check_capacity(route, additional):
    """Priority 16: load factor after adding must stay strictly below 10000bp."""
    svc.recompute_route(route, do_bump=False)
    committed_after = route["committed_visit_count"] + additional
    if (committed_after * 10000) // route["max_visit_capacity"] >= 10000:
        raise ApiError("ERR_ROUTE_AT_CAPACITY", 409,
                       "Adding this visit would push the route to full capacity")


def _owned_visit(vid, uid):
    visit = lookup(svc.visits, vid, "Visit")
    sub = svc.subscriptions.get(visit["subscription_id"])
    if sub is None or sub["customer_id"] != uid:
        raise err_unauthorized("Customers may only act on their own visits")
    return visit, sub


@bp.post("/api/visits")
def create_visit():
    uid, role = auth("OperationsManager", "Customer")
    data = get_body()
    subscription_id = require(data, "subscription_id", str)
    scheduled_date = require_dt(data, "scheduled_date")
    window_start = require_dt(data, "scheduled_window_start")
    window_end = require_dt(data, "scheduled_window_end")
    route_id = optional(data, "service_route_id", str)
    addon_ids = optional(data, "addon_ids", list, []) or []
    for aid in addon_ids:
        if not isinstance(aid, str):
            raise err_invalid_request("addon_ids must be a list of strings")
    sub = lookup_fk(svc.subscriptions, subscription_id, "Subscription")
    route = None
    if route_id is not None:
        route = lookup_fk(svc.routes, route_id, "ServiceRoute")
    for aid in addon_ids:
        lookup_fk(svc.addons, aid, "ServiceAddon")
    if role == "Customer" and sub["customer_id"] != uid:
        raise err_unauthorized("Customers may only schedule visits on their own subscriptions")
    # priority 14: window validity
    if not (window_start < window_end) or (window_end - window_start) < MIN_WINDOW:
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422,
                       "scheduled_window_start must precede scheduled_window_end by >= 30 minutes")
    # priority 15 / 16: route conflict + capacity
    if route is not None:
        _check_window_conflict(route, window_start, window_end)
        _check_capacity(route, 1)
    # priority 20: subscription serviceable
    if sub["status"] == "CANCELLED":
        raise ApiError("ERR_SUBSCRIPTION_NOT_SERVICEABLE", 422,
                       "Subscription is CANCELLED")
    profile = svc.access_profile_of_yard(sub["yard_id"])
    if profile is None or profile["access_status"] != "VERIFIED":
        raise ApiError("ERR_SUBSCRIPTION_NOT_SERVICEABLE", 422,
                       "Yard access profile is not VERIFIED")
    rec = svc.create_visit_record(sub, scheduled_date, window_start, window_end,
                                  route_id, addon_ids)
    return ok_object(svc.ser_visit(rec), status=201)


@bp.get("/api/visits/<vid>")
def get_visit(vid):
    uid, role = auth("OperationsManager", "Customer", "Technician", "BillingAdmin")
    visit = lookup(svc.visits, vid, "Visit")
    if role == "Customer":
        sub = svc.subscriptions.get(visit["subscription_id"])
        if sub is None or sub["customer_id"] != uid:
            raise err_unauthorized("Customers may only access their own visits")
    return ok_object(svc.ser_visit(visit))


@bp.get("/api/visits")
def list_visits():
    uid, role = auth("OperationsManager", "Customer", "Technician", "BillingAdmin")
    limit, offset = parse_pagination()
    records = list(svc.visits.values())
    if role == "Customer":
        own_subs = {s["id"] for s in svc.subscriptions.values() if s["customer_id"] == uid}
        records = [v for v in records if v["subscription_id"] in own_subs]
    sub_id = request.args.get("subscription_id")
    if sub_id is not None:
        records = [v for v in records if v["subscription_id"] == sub_id]
    route_id = request.args.get("service_route_id")
    if route_id is not None:
        records = [v for v in records if v["service_route_id"] == route_id]
    status = request.args.get("status")
    if status is not None:
        records = [v for v in records if v["status"] == status]
    date_param = request.args.get("scheduled_date")
    if date_param is not None:
        from clock import parse_dt
        try:
            d = parse_dt(date_param).date()
        except ValueError:
            raise err_invalid_request("scheduled_date filter is malformed")
        records = [v for v in records if v["scheduled_date"].date() == d]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_visit(v) for v in page], total, limit, offset)


@bp.post("/api/visits/<vid>/assign-route")
def assign_route(vid):
    auth("OperationsManager")
    data = get_body()
    route_id = require(data, "service_route_id", str)
    visit = lookup(svc.visits, vid, "Visit")
    route = lookup_fk(svc.routes, route_id, "ServiceRoute")
    if visit["status"] in svc.TERMINAL_VISIT_STATES:
        raise err_invalid_state("Cannot reassign a visit in a terminal state")
    old_route = svc.visit_route(visit)
    same = old_route is not None and old_route["id"] == route["id"]
    _check_window_conflict(route, visit["scheduled_window_start"],
                           visit["scheduled_window_end"], exclude_visit_id=visit["id"])
    _check_capacity(route, 0 if same else 1)
    visit["service_route_id"] = route["id"]
    svc.bump(visit)
    if old_route is not None and not same:
        svc.recompute_route(old_route)
    svc.recompute_route(route)
    return ok_object(svc.ser_visit(visit))


@bp.post("/api/visits/<vid>/depart")
def depart_visit(vid):
    uid, _ = auth("Technician")
    visit = lookup(svc.visits, vid, "Visit")
    if visit["status"] != "SCHEDULED":
        raise err_invalid_state("depart is only valid from SCHEDULED")
    if not visit["service_route_id"]:
        raise ApiError("ERR_ROUTE_NOT_ASSIGNED", 422,
                       "Visit has no service_route_id")
    route = svc.routes.get(visit["service_route_id"])
    if route is None or route["route_status"] != "IN_PROGRESS":
        raise ApiError("ERR_ROUTE_NOT_IN_PROGRESS", 409,
                       "Route must be IN_PROGRESS")
    if route["assigned_technician_id"] != uid:
        raise ApiError("ERR_ROUTE_TECH_MISMATCH", 403,
                       "Acting technician is not the route's assigned technician")
    visit["status"] = "EN_ROUTE"
    svc.bump(visit)
    return ok_object(svc.ser_visit(visit))


@bp.post("/api/visits/<vid>/ack-safety")
def ack_safety(vid):
    auth("Technician")
    visit = lookup(svc.visits, vid, "Visit")
    if visit["status"] not in ("SCHEDULED", "EN_ROUTE"):
        raise err_invalid_state("ack-safety is only valid before arrival")
    visit["tech_safety_ack_at"] = now()
    svc.bump(visit)
    return ok_object(svc.ser_visit(visit))


@bp.post("/api/visits/<vid>/arrive")
def arrive_visit(vid):
    uid, _ = auth("Technician")
    visit = lookup(svc.visits, vid, "Visit")
    if visit["status"] != "EN_ROUTE":
        raise err_invalid_state("arrive is only valid from EN_ROUTE")
    sub = svc.subscriptions.get(visit["subscription_id"])
    profile = svc.access_profile_of_yard(sub["yard_id"]) if sub else None
    flag = profile["pet_aggression_flag"] if profile else "NONE"
    if flag in ("CAUTION", "AGGRESSIVE") and visit["tech_safety_ack_at"] is None:
        raise ApiError("ERR_PET_SAFETY_ACK_REQUIRED", 422,
                       "tech_safety_ack_at is required before going ON_SITE")
    if flag == "AGGRESSIVE":
        tech = svc.technicians.get(uid)
        if tech is None or not tech["certified_for_aggressive_pets"]:
            raise ApiError("ERR_TECH_NOT_CERTIFIED_AGGRESSIVE", 422,
                           "Technician is not certified for aggressive pets")
    visit["status"] = "ON_SITE"
    svc.bump(visit)
    return ok_object(svc.ser_visit(visit))


@bp.post("/api/visits/<vid>/complete")
def complete_visit(vid):
    auth("Technician")
    visit = lookup(svc.visits, vid, "Visit")
    if visit["status"] != "ON_SITE":
        raise err_invalid_state("complete is only valid from ON_SITE")
    svc.complete_visit_record(visit)
    return ok_object(svc.ser_visit(visit))


@bp.post("/api/visits/<vid>/skip")
def skip_visit(vid):
    uid, _ = auth("Customer")
    visit, sub = _owned_visit(vid, uid)
    if visit["status"] != "SCHEDULED":
        raise err_invalid_state("skip is only valid from SCHEDULED")
    customer = svc.customers.get(sub["customer_id"])
    if customer is not None and customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409,
                       "Customer.account_status must be ACTIVE")
    if visit["scheduled_date"].date() <= now().date():
        raise ApiError("ERR_TOO_LATE_TO_SKIP", 409,
                       "scheduled_date is not strictly after today")
    route = svc.visit_route(visit)
    if route is not None and route["route_status"] == "IN_PROGRESS":
        raise ApiError("ERR_ROUTE_LOCKED", 409,
                       "Visit is on a route that is IN_PROGRESS")
    svc.finalize_visit_skip(
        visit,
        "CUSTOMER_REQUEST",
        sub,
        post_credit=(sub["status"] == "ACTIVE"),
        credit_line_type="VACATION_CREDIT",
    )
    return ok_object(svc.ser_visit(visit))


@bp.post("/api/visits/<vid>/cancel")
def cancel_visit(vid):
    uid, role = auth("Customer", "OperationsManager")
    visit = lookup(svc.visits, vid, "Visit")
    if role == "Customer":
        sub = svc.subscriptions.get(visit["subscription_id"])
        if sub is None or sub["customer_id"] != uid:
            raise err_unauthorized("Customers may only cancel their own visits")
    if visit["status"] != "SCHEDULED":
        raise err_invalid_state("cancel is only valid from SCHEDULED")
    svc.cancel_visit_record(visit)
    return ok_object(svc.ser_visit(visit))
