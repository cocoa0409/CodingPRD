"""Route and Stop endpoints, including driver field actions."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import services
from db import db
from middleware import (body_json, check_transition, f_bool, f_int, f_str,
                        require_roles)
from response import list_response, ok_object
from services import (add_ledger_entry, base_record, bump, ser_ledger,
                      ser_route, ser_skip_credit, ser_stop)

bp = Blueprint("routes_stops", __name__)

ROUTE_READ_ROLES = ("OpsAdmin", "Dispatcher", "Driver")
ROUTE_TERMINAL = ("COMPLETED", "CANCELLED")
STOP_TERMINAL = ("DELIVERED", "PARTIAL", "SKIPPED", "FAILED", "CANCELLED")


def _get_route(rid):
    r = db.routes.get(rid)
    if r is None:
        raise errors.not_found("route not found")
    return r


def _get_stop(sid):
    s = db.stops.get(sid)
    if s is None:
        raise errors.not_found("stop not found")
    return s


def create_stop_record(route, customer_id, sequence_index, planned_bottles,
                       planned_empties=None):
    rec = base_record()
    rec.update({
        "route_id": route["id"],
        "customer_id": customer_id,
        "sequence_index": sequence_index,
        "planned_bottles": planned_bottles,
        "planned_empties_pickup": (planned_bottles if planned_empties is None
                                   else planned_empties),
        "stop_status": "PLANNED",
        "actual_bottles_delivered": 0,
        "actual_empties_collected": 0,
        "shortage_count": 0,
        "skip_reason": None,
    })
    db.stops[rec["id"]] = rec
    bump(route)
    return rec


# ------------------------------------------------------------------- routes

@bp.post("/routes")
@require_roles("Dispatcher")
def create_route():
    d = body_json()
    zone_id = f_str(d, "zone_id")
    service_date_s = f_str(d, "service_date")
    driver_name = f_str(d, "driver_name")
    truck_capacity_bottles = f_int(d, "truck_capacity_bottles", min_value=1)
    # Stage 6: FK resolution.
    zone = db.zones.get(zone_id)
    if zone is None:
        raise errors.invalid_reference("zone_id does not resolve")
    # Stage 7: date well-formedness and not-in-the-past.
    try:
        service_date = services.parse_date(service_date_s)
    except ValueError:
        raise errors.invalid_date_range("service_date is not a valid date")
    if service_date < services.today():
        raise errors.invalid_date_range("service_date must not lie in the past")
    if not zone["active"]:
        raise errors.invalid_reference("zone is inactive and rejects new routes")
    rec = base_record()
    rec.update({
        "zone_id": zone_id,
        "service_date": service_date_s,
        "driver_name": driver_name,
        "truck_capacity_bottles": truck_capacity_bottles,
        "route_status": "DRAFT",
    })
    with db.lock:
        db.routes[rec["id"]] = rec
    return ok_object(ser_route(rec), 201)


@bp.get("/routes")
@require_roles(*ROUTE_READ_ROLES)
def list_routes():
    items = list(db.routes.values())
    service_date = request.args.get("service_date")
    if service_date is not None:
        items = [r for r in items if r["service_date"] == service_date]
    route_status = request.args.get("route_status")
    if route_status is not None:
        items = [r for r in items if r["route_status"] == route_status]
    zone_id = request.args.get("zone_id")
    if zone_id is not None:
        items = [r for r in items if r["zone_id"] == zone_id]
    return list_response(items, ser_route)


@bp.get("/routes/<rid>")
@require_roles(*ROUTE_READ_ROLES)
def get_route(rid):
    return ok_object(ser_route(_get_route(rid)))


@bp.post("/routes/<rid>/publish")
@require_roles("Dispatcher")
def publish_route(rid):
    r = _get_route(rid)
    check_transition(r, "route_status", ("DRAFT",), ROUTE_TERMINAL, "Route")
    has_planned = any(s["route_id"] == rid and s["stop_status"] == "PLANNED"
                      for s in db.stops.values())
    if not has_planned:
        raise errors.invalid_state("route has no PLANNED stop")
    zone = db.zones.get(r["zone_id"])
    if zone is None or not zone["active"]:
        raise errors.invalid_state("route zone is not active")
    with db.lock:
        r["route_status"] = "PUBLISHED"
        bump(r)
    return ok_object(ser_route(r))


@bp.post("/routes/<rid>/start")
@require_roles("Driver")
def start_route(rid):
    r = _get_route(rid)
    check_transition(r, "route_status", ("PUBLISHED",), ROUTE_TERMINAL,
                     "Route")
    if services.today() < services.parse_date(r["service_date"]):
        raise errors.invalid_state(
            "route cannot start before its service_date")
    with db.lock:
        for s in db.stops.values():
            if s["route_id"] == rid and s["stop_status"] == "PLANNED":
                s["stop_status"] = "EN_ROUTE"
                bump(s)
        # Linked delivery work orders ride the route into IN_PROGRESS.
        stop_ids = {s["id"] for s in db.stops.values()
                    if s["route_id"] == rid}
        for w in db.work_orders.values():
            if (w["order_status"] == "SCHEDULED"
                    and w.get("linked_stop_id") in stop_ids):
                w["order_status"] = "IN_PROGRESS"
                bump(w)
        r["route_status"] = "IN_PROGRESS"
        bump(r)
    return ok_object(ser_route(r))


@bp.post("/routes/<rid>/complete")
@require_roles("Driver")
def complete_route(rid):
    r = _get_route(rid)
    check_transition(r, "route_status", ("IN_PROGRESS",), ROUTE_TERMINAL,
                     "Route")
    for s in db.stops.values():
        if (s["route_id"] == rid
                and s["stop_status"] not in STOP_TERMINAL):
            raise errors.invalid_state(
                "route has stops that are not in a terminal state")
    with db.lock:
        r["route_status"] = "COMPLETED"
        bump(r)
    return ok_object(ser_route(r))


@bp.post("/routes/<rid>/cancel")
@require_roles("Dispatcher")
def cancel_route(rid):
    r = _get_route(rid)
    check_transition(r, "route_status", ("DRAFT", "PUBLISHED"),
                     ROUTE_TERMINAL, "Route")
    with db.lock:
        for s in db.stops.values():
            if (s["route_id"] == rid
                    and s["stop_status"] not in STOP_TERMINAL):
                s["stop_status"] = "CANCELLED"
                bump(s)
        r["route_status"] = "CANCELLED"
        bump(r)
    return ok_object(ser_route(r))


@bp.get("/routes/<rid>/stops")
@require_roles(*ROUTE_READ_ROLES)
def list_route_stops(rid):
    _get_route(rid)
    items = [s for s in db.stops.values() if s["route_id"] == rid]
    return list_response(items, ser_stop)


@bp.post("/routes/<rid>/stops")
@require_roles("Dispatcher")
def plan_stop(rid):
    r = _get_route(rid)
    check_transition(r, "route_status", ("DRAFT", "PUBLISHED"),
                     ROUTE_TERMINAL, "Route")
    d = body_json()
    customer_id = f_str(d, "customer_id")
    sequence_index = f_int(d, "sequence_index", min_value=1)
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.invalid_reference("customer_id does not resolve")
    if customer["service_mode"] == "WILL_CALL":
        raise errors.invalid_request(
            "manual stop planning is refused for WILL_CALL customers; "
            "a work order is required")
    for s in db.stops.values():
        if s["route_id"] == rid and s["sequence_index"] == sequence_index:
            raise errors.ApiError(
                errors.ERR_DUPLICATE_SEQUENCE, 409,
                "sequence_index already used on this route")
    planned = max(0, customer["par_level_bottles"]
                  - services.bottles_on_site(customer_id))
    if (services.committed_bottles(rid) + planned
            > r["truck_capacity_bottles"]):
        raise errors.ApiError(
            errors.ERR_ROUTE_CAPACITY_EXCEEDED, 422,
            "adding this stop would exceed truck capacity")
    with db.lock:
        rec = create_stop_record(r, customer_id, sequence_index, planned)
    return ok_object(ser_stop(rec), 201)


# -------------------------------------------------------------------- stops

@bp.get("/stops")
@require_roles(*ROUTE_READ_ROLES)
def list_stops():
    items = list(db.stops.values())
    route_id = request.args.get("route_id")
    if route_id is not None:
        items = [s for s in items if s["route_id"] == route_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    stop_status = request.args.get("stop_status")
    if stop_status is not None:
        items = [s for s in items if s["stop_status"] == stop_status]
    return list_response(items, ser_stop)


@bp.get("/stops/<sid>")
@require_roles(*ROUTE_READ_ROLES)
def get_stop(sid):
    return ok_object(ser_stop(_get_stop(sid)))


@bp.get("/stops/<sid>/bottle-custody-ledger")
@require_roles("OpsAdmin", "Dispatcher", "BillingAdmin")
def list_stop_ledger(sid):
    _get_stop(sid)
    items = [e for e in db.ledger.values() if e["stop_id"] == sid]
    return list_response(items, ser_ledger)


@bp.get("/stops/<sid>/skip-credits")
@require_roles("OpsAdmin", "Dispatcher", "BillingAdmin")
def list_stop_skip_credits(sid):
    _get_stop(sid)
    items = [s for s in db.skip_credits.values() if s["stop_id"] == sid]
    return list_response(items, ser_skip_credit)


@bp.post("/stops/<sid>/arrive")
@require_roles("Driver")
def arrive_stop(sid):
    s = _get_stop(sid)
    check_transition(s, "stop_status", ("EN_ROUTE",), STOP_TERMINAL, "Stop")
    with db.lock:
        s["stop_status"] = "ARRIVED"
        bump(s)
    return ok_object(ser_stop(s))


@bp.post("/stops/<sid>/deliver")
@require_roles("Driver")
def deliver_stop(sid):
    s = _get_stop(sid)
    check_transition(s, "stop_status", ("ARRIVED",), STOP_TERMINAL, "Stop")
    d = body_json()
    expected_route_version = f_int(d, "expected_route_version")
    actual_delivered = f_int(d, "actual_bottles_delivered", min_value=0)
    actual_collected = f_int(d, "actual_empties_collected", min_value=0)
    route = db.routes.get(s["route_id"])
    # Priority 17: OCC against the parent route version.
    if expected_route_version != route["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_VERSION, 412,
            "expected_route_version does not match route's current version")
    if actual_delivered > s["planned_bottles"]:
        raise errors.invalid_request(
            "actual_bottles_delivered exceeds planned_bottles")
    clean = (actual_delivered == s["planned_bottles"]
             and actual_collected >= s["planned_empties_pickup"])
    shortage = max(0, s["planned_empties_pickup"] - actual_collected)
    with db.lock:
        s["actual_bottles_delivered"] = actual_delivered
        s["actual_empties_collected"] = actual_collected
        s["shortage_count"] = 0 if clean else shortage
        s["stop_status"] = "DELIVERED" if clean else "PARTIAL"
        bump(s)
        # Custody trail.
        if actual_delivered > 0:
            add_ledger_entry(s["customer_id"], sid, "DELIVER_FULL",
                             actual_delivered)
        if actual_collected > 0:
            add_ledger_entry(s["customer_id"], sid, "PICKUP_EMPTY",
                             -actual_collected)
        if not clean and shortage > 0:
            add_ledger_entry(s["customer_id"], sid, "MARK_SHORTAGE",
                             shortage)
        # The delivery cascades a bottles_on_site change onto the account.
        customer = db.customers.get(s["customer_id"])
        if customer is not None:
            bump(customer)
        # Linked work order completes.
        for w in db.work_orders.values():
            if (w.get("linked_stop_id") == sid
                    and w["order_status"] == "IN_PROGRESS"):
                w["order_status"] = "COMPLETED"
                bump(w)
        # Route releases the stop's planned bottles; version bumps.
        bump(route)
    return ok_object(ser_stop(s))


@bp.post("/stops/<sid>/skip")
@require_roles("Driver")
def skip_stop(sid):
    s = _get_stop(sid)
    check_transition(s, "stop_status", ("PLANNED", "EN_ROUTE", "ARRIVED"),
                     STOP_TERMINAL, "Stop")
    d = body_json()
    skip_reason = d.get("skip_reason")
    if (skip_reason is None or not isinstance(skip_reason, str)
            or skip_reason == ""):
        raise errors.ApiError(errors.ERR_SKIP_REASON_REQUIRED, 400,
                              "skip requires a non-empty skip_reason")
    notified = f_bool(d, "notified_before_cutoff", required=False,
                      default=False)
    route = db.routes.get(s["route_id"])
    customer = db.customers.get(s["customer_id"])
    cfg = services.config_at(services.parse_date(route["service_date"]))
    credit = services.skip_credit_cents(customer, s["planned_bottles"],
                                        notified, cfg)
    with db.lock:
        sc = base_record()
        sc.update({
            "customer_id": s["customer_id"],
            "stop_id": sid,
            "credit_cents": credit,
            "credit_status": "PENDING",
            "expires_at": services.now() + timedelta(days=90),
            "notified_before_cutoff": notified,
            "pending_consumption": False,
        })
        db.skip_credits[sc["id"]] = sc
        s["skip_reason"] = skip_reason
        s["stop_status"] = "SKIPPED"
        bump(s)
        bump(route)
    return ok_object(ser_stop(s))


@bp.post("/stops/<sid>/fail")
@require_roles("Driver")
def fail_stop(sid):
    s = _get_stop(sid)
    check_transition(s, "stop_status", ("EN_ROUTE", "ARRIVED"),
                     STOP_TERMINAL, "Stop")
    route = db.routes.get(s["route_id"])
    with db.lock:
        s["stop_status"] = "FAILED"
        bump(s)
        bump(route)
    return ok_object(ser_stop(s))
