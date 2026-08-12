"""Subscription endpoints: create/list/read, pause/resume/cancel/plan-change."""

from flask import Blueprint, request

import response
from db import new_entity, store, touch
from errors import (ERR_ACCOUNT_DELINQUENT, ERR_NO_BIN_AVAILABLE,
                    ERR_PAUSE_WINDOW_OVERLAP, ERR_PLAN_DOWNGRADE_BLOCKED,
                    ERR_ROUTE_CAPACITY, ERR_STALE_VERSION,
                    ERR_SUBSCRIPTION_STATE_CONFLICT, ApiError, bad_request,
                    not_found, unprocessable)
from middleware import auth, own_or_403, require_roles
from services import (account_standing, active_subscriptions_count,
                      assigned_bins, by_seq, cancel_scheduled_pickups,
                      return_bin_to_depot, select_depot_bins,
                      send_bin_to_customer, ser_subscription)
from utils import get_body, is_int, paginate, pagination_params, parse_date

bp = Blueprint("subscriptions", __name__)


def _get_subscription_or_404(sid):
    sub = store["subscriptions"].get(sid)
    if sub is None:
        not_found("Subscription not found")
    return sub


def _check_ownership(sub, uid, role):
    if role == "Subscriber":
        own_or_403(sub["subscriber_id"], uid)


@bp.post("/subscriptions")
def create_subscription():
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    body = get_body()
    subscriber_id = body.get("subscriber_id")
    plan_id = body.get("plan_id")
    route_id = body.get("route_id")
    for name, val in (("subscriber_id", subscriber_id), ("plan_id", plan_id),
                      ("route_id", route_id)):
        if not isinstance(val, str) or val == "":
            bad_request("Missing or invalid field: " + name)
    start_date = parse_date(body.get("start_date"), "start_date")
    if role == "Subscriber":
        own_or_403(subscriber_id, uid)
    subscriber = store["subscribers"].get(subscriber_id)
    if subscriber is None:
        not_found("Subscriber not found")
    plan = store["service_plans"].get(plan_id)
    if plan is None:
        not_found("Service plan not found")
    route = store["routes"].get(route_id)
    if route is None:
        not_found("Route not found")
    if plan["subscriber_type"] != subscriber["subscriber_type"]:
        bad_request("Plan subscriber_type does not match subscriber_type")
    # Structural checks, PRD 3.2 order: depot bins first, then route slot.
    chosen = select_depot_bins(plan["bin_type"], plan["included_bins"])
    if chosen is None:
        unprocessable(ERR_NO_BIN_AVAILABLE,
                      "Depot lacks enough clean bins of the plan's bin_type")
    if active_subscriptions_count(route_id) >= route["max_stops"]:
        unprocessable(ERR_ROUTE_CAPACITY, "Route has no free weekly slot")
    sub = new_entity(common=True)
    sub.update({
        "subscriber_id": subscriber_id, "plan_id": plan_id,
        "route_id": route_id, "start_date": start_date.isoformat(),
        "service_status": "ACTIVE", "strike_count": 0,
        "skips_used_this_quarter": 0, "current_quarter": None,
        "pause_windows": [],
    })
    store["subscriptions"][sub["id"]] = sub
    for b in chosen:
        send_bin_to_customer(b, sub["id"])
    return response.ok(ser_subscription(sub), code=201)


@bp.get("/subscriptions")
def list_subscriptions():
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    limit, offset = pagination_params()
    items = by_seq(store["subscriptions"].values())
    if role == "Subscriber":
        items = [s for s in items if s["subscriber_id"] == uid]
    for param, field in (("subscriber_id", "subscriber_id"),
                         ("plan_id", "plan_id"), ("route_id", "route_id"),
                         ("status", "service_status")):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if s[field] == val]
    page, total = paginate(items, limit, offset)
    return response.ok_list([ser_subscription(s) for s in page], limit,
                            offset, total)


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    sub = _get_subscription_or_404(sid)
    _check_ownership(sub, uid, role)
    return response.ok(ser_subscription(sub))


@bp.post("/subscriptions/<sid>/pause")
def pause_subscription(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    body = get_body()
    ps = parse_date(body.get("pause_start"), "pause_start")
    pe = parse_date(body.get("pause_end"), "pause_end")
    if pe <= ps:
        bad_request("pause_end must be later than pause_start")
    sub = _get_subscription_or_404(sid)
    _check_ownership(sub, uid, role)
    if sub["service_status"] != "ACTIVE":
        raise ApiError(ERR_SUBSCRIPTION_STATE_CONFLICT, 409,
                       "Subscription is not ACTIVE")
    if account_standing(sub["subscriber_id"]) != "GOOD_STANDING":
        raise ApiError(ERR_ACCOUNT_DELINQUENT, 402,
                       "Subscriber has an overdue issued invoice")
    for w in sub["pause_windows"]:
        ws = parse_date(w["pause_start"], "pause_start")
        we = parse_date(w["pause_end"], "pause_end")
        if ps < we and ws < pe:  # half-open overlap; adjacency allowed
            unprocessable(ERR_PAUSE_WINDOW_OVERLAP,
                          "Pause window overlaps a recorded window")
    sub["pause_windows"].append({"pause_start": ps.isoformat(),
                                 "pause_end": pe.isoformat()})
    sub["service_status"] = "PAUSED"
    cancel_scheduled_pickups(sub["id"], window=(ps, pe))
    touch(sub)
    return response.ok(ser_subscription(sub))


@bp.post("/subscriptions/<sid>/resume")
def resume_subscription(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    sub = _get_subscription_or_404(sid)
    _check_ownership(sub, uid, role)
    if sub["service_status"] != "PAUSED":
        raise ApiError(ERR_SUBSCRIPTION_STATE_CONFLICT, 409,
                       "Subscription is not PAUSED")
    if account_standing(sub["subscriber_id"]) != "GOOD_STANDING":
        raise ApiError(ERR_ACCOUNT_DELINQUENT, 402,
                       "Subscriber has an overdue issued invoice")
    sub["service_status"] = "ACTIVE"
    touch(sub)
    return response.ok(ser_subscription(sub))


@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    sub = _get_subscription_or_404(sid)
    _check_ownership(sub, uid, role)
    if sub["service_status"] not in ("ACTIVE", "PAUSED", "SUSPENDED"):
        raise ApiError(ERR_SUBSCRIPTION_STATE_CONFLICT, 409,
                       "Subscription is CANCELLED (terminal)")
    if sub["service_status"] in ("ACTIVE", "PAUSED"):
        cancel_scheduled_pickups(sub["id"])
    for b in assigned_bins(sub["id"]):
        return_bin_to_depot(b)
    sub["service_status"] = "CANCELLED"
    touch(sub)
    return response.ok(ser_subscription(sub))


@bp.post("/subscriptions/<sid>/plan-change")
def plan_change(sid):
    uid, role = auth()
    require_roles(role, "Subscriber", "OperationsManager")
    body = get_body()
    new_plan_id = body.get("new_plan_id")
    if not isinstance(new_plan_id, str) or new_plan_id == "":
        bad_request("Missing or invalid field: new_plan_id")
    expected = body.get("expected_subscription_version")
    if not is_int(expected):
        bad_request("expected_subscription_version is required and must be an integer")
    sub = _get_subscription_or_404(sid)
    _check_ownership(sub, uid, role)
    new_plan = store["service_plans"].get(new_plan_id)
    if new_plan is None:
        not_found("New service plan not found")
    if expected != sub["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_subscription_version does not match current version")
    if sub["service_status"] != "ACTIVE":
        raise ApiError(ERR_SUBSCRIPTION_STATE_CONFLICT, 409,
                       "Subscription is not ACTIVE")
    subscriber = store["subscribers"][sub["subscriber_id"]]
    assigned = len(assigned_bins(sub["id"]))
    if (new_plan["subscriber_type"] != subscriber["subscriber_type"]
            or new_plan["included_bins"] < assigned):
        unprocessable(ERR_PLAN_DOWNGRADE_BLOCKED,
                      "Plan crosses subscriber_type or includes fewer bins than assigned")
    sub["plan_id"] = new_plan_id
    touch(sub)
    return response.ok(ser_subscription(sub))
