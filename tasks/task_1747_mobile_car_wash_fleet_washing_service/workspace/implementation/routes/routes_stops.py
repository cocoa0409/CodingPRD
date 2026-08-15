"""Route and RouteStop endpoints."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store
from serialize import (
    ser_route, ser_stop, route_assigned_vehicle_count, customer_of_stop,
)
from services import (
    lot_setup_minutes, service_minutes, net_gallons, van_recovery,
    van_free_gal, stops_of_route, cancel_route, DRIVE_MINUTES,
)
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_int, opt_str, stamp_new, touch, parse_date, parse_dt, gal_round,
    ApiError,
)
from errors import (
    ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_ROUTE_LOCKED,
    ERR_STALE_VERSION, ERR_CONTAINMENT_REQUIRED, ERR_DISCHARGE_CAP_EXCEEDED,
    ERR_CERTIFICATION_REQUIRED, ERR_TECHNICIAN_SCHEDULE_CONFLICT,
    ERR_ROUTE_WATER_CAPACITY_EXCEEDED, ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED,
    ERR_VAN_ROUTE_CONFLICT, ERR_TECHNICIAN_NOT_ACTIVE,
)

bp = Blueprint("routes_stops", __name__)

TERMINAL_ROUTE_STATES = ("COMPLETED", "CANCELLED")


def _get_route_or_404(rid):
    rec = store.routes.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Route %s not found" % rid)
    return rec


@bp.post("/fleet-wash/routes")
def create_route():
    _uid, role = caller()
    require_role(role, {"Dispatcher"})
    body = get_body()
    route_date = req_str(body, "route_date")
    rd = parse_date(route_date, "route_date")
    van_id = req_str(body, "van_id")
    van = store.vans.get(van_id)
    if van is None:
        raise ApiError(ERR_NOT_FOUND, "Van %s not found" % van_id)
    tech_id = req_str(body, "lead_technician_id")
    tech = store.technicians.get(tech_id)
    if tech is None:
        raise ApiError(ERR_NOT_FOUND, "Technician %s not found" % tech_id)
    shift_raw = opt_str(body, "shift_start_at")
    if shift_raw is None:
        shift = datetime(rd.year, rd.month, rd.day, 8, 0, 0, tzinfo=timezone.utc)
    else:
        shift = parse_dt(shift_raw, "shift_start_at")
        if shift.date() != rd:
            raise ApiError(ERR_VALIDATION, "shift_start_at must fall on route_date")
    if van["reclaim_system"] == "ADVANCED" and not tech["water_reclaim_certified"]:
        raise ApiError(ERR_CERTIFICATION_REQUIRED,
                       "ADVANCED-reclaim van requires a water-reclaim-certified lead")
    for r in store.routes.values():
        if r["van_id"] == van_id and r["route_date"] == route_date \
                and r["status"] in ("DRAFT", "PUBLISHED", "LOCKED"):
            raise ApiError(ERR_VAN_ROUTE_CONFLICT,
                           "Van already has a non-terminal route on this date")
    if tech["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, "Lead technician is not ACTIVE")
    rec = {
        "route_date": route_date,
        "shift_start_at": shift,
        "van_id": van_id,
        "lead_technician_id": tech_id,
        "status": "DRAFT",
        "cancel_reason": None,
    }
    stamp_new(rec)
    store.routes[rec["id"]] = rec
    return respond(ser_route(rec), 201)


@bp.get("/fleet-wash/routes/<rid>")
def get_route(rid):
    _uid, _role = caller()
    return respond(ser_route(_get_route_or_404(rid)), 200)


@bp.get("/fleet-wash/routes")
def list_routes():
    _uid, _role = caller()
    van_id = request.args.get("van_id")
    tech_id = request.args.get("lead_technician_id")
    route_date = request.args.get("route_date")
    status = request.args.get("status")
    recs = list(store.routes.values())
    if van_id is not None:
        recs = [r for r in recs if r["van_id"] == van_id]
    if tech_id is not None:
        recs = [r for r in recs if r["lead_technician_id"] == tech_id]
    if route_date is not None:
        recs = [r for r in recs if r["route_date"] == route_date]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_route)


@bp.post("/fleet-wash/routes/<rid>/events")
def route_event(rid):
    _uid, role = caller()
    require_role(role, {"Dispatcher"})
    route = _get_route_or_404(rid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("PUBLISH", "UNPUBLISH", "LOCK", "COMPLETE", "CANCEL"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be PUBLISH, UNPUBLISH, LOCK, COMPLETE, or CANCEL")
    stops = stops_of_route(route["id"])
    if event == "PUBLISH":
        if route["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Route is not DRAFT")
        route["status"] = "PUBLISHED"
        touch(route)
    elif event == "UNPUBLISH":
        if route["status"] != "PUBLISHED":
            raise ApiError(ERR_INVALID_STATE, "Route is not PUBLISHED")
        if any(s["status"] in ("ARRIVED", "DONE") for s in stops):
            raise ApiError(ERR_INVALID_STATE,
                           "A stop has already ARRIVED or is DONE")
        route["status"] = "DRAFT"
        touch(route)
    elif event == "LOCK":
        if route["status"] != "PUBLISHED":
            raise ApiError(ERR_INVALID_STATE, "Route is not PUBLISHED")
        route["status"] = "LOCKED"
        touch(route)
    elif event == "COMPLETE":
        if route["status"] != "LOCKED":
            raise ApiError(ERR_INVALID_STATE, "Route is not LOCKED")
        if any(s["status"] not in ("DONE", "SKIPPED", "CANCELLED") for s in stops):
            raise ApiError(ERR_INVALID_STATE, "Not all stops are DONE, SKIPPED, or CANCELLED")
        route["status"] = "COMPLETED"
        touch(route)
    else:  # CANCEL
        if route["status"] in TERMINAL_ROUTE_STATES:
            raise ApiError(ERR_INVALID_STATE, "Route is already %s" % route["status"])
        cancel_route(route, "DISPATCH", weather=False)
    return respond(ser_route(route), 200)


def _tech_buffer_conflict(route, cand_start, cand_end):
    """30-minute cross-route travel buffer for the same lead technician."""
    buffer = timedelta(minutes=30)
    for other in store.routes.values():
        if other["id"] == route["id"] or other["status"] == "CANCELLED":
            continue
        if other["route_date"] != route["route_date"]:
            continue
        if other["lead_technician_id"] != route["lead_technician_id"]:
            continue
        for s in stops_of_route(other["id"]):
            if s["status"] not in ("PLANNED", "ARRIVED", "DONE"):
                continue
            s_start, s_end = s["planned_start_at"], s["planned_end_at"]
            if cand_end <= s_start:
                gap = s_start - cand_end
            elif s_end <= cand_start:
                gap = cand_start - s_end
            else:
                return True  # overlapping windows
            if gap < buffer:
                return True
    return False


@bp.post("/fleet-wash/routes/<rid>/stops")
def add_stop(rid):
    _uid, role = caller()
    require_role(role, {"Dispatcher"})
    route = _get_route_or_404(rid)
    body = get_body()
    wash_order_id = req_str(body, "wash_order_id")
    order = store.orders.get(wash_order_id)
    if order is None:
        raise ApiError(ERR_NOT_FOUND, "WashOrder %s not found" % wash_order_id)
    expected = req_int(body, "expected_route_version")
    if expected != route["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_route_version does not match current version")
    # State tier: the path resource (Route) is checked before the order.
    if route["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_ROUTE_LOCKED,
                       "Route %s does not accept stop mutations" % route["status"])
    if order["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "WashOrder is not SCHEDULED")
    site = store.sites[order["site_id"]]
    van = store.vans[route["van_id"]]
    classes = [store.vehicles[vid]["vehicle_class"] for vid in order["vehicle_ids"]]
    projected = net_gallons(classes, van)
    # Safety tier: containment adequacy, then discharge cap.
    if site["water_reclaim_required"]:
        if van_recovery(van) < Decimal("0.60"):
            raise ApiError(ERR_CONTAINMENT_REQUIRED,
                           "Van recovery is below 0.60 at a reclaim-required site")
        if Decimal(str(projected)) > Decimal(str(site["max_discharge_gal"])):
            raise ApiError(ERR_DISCHARGE_CAP_EXCEEDED,
                           "Projected discharge exceeds the site cap")
    # Planning: sequence, planned window.
    existing = stops_of_route(route["id"])
    sequence = len(existing) + 1
    if sequence == 1:
        planned_start = route["shift_start_at"]
    else:
        planned_start = existing[-1]["planned_end_at"] + timedelta(minutes=DRIVE_MINUTES)
    duration = lot_setup_minutes(site) + service_minutes(classes)
    planned_end = planned_start + timedelta(minutes=duration)
    # Temporal tier: technician travel buffer.
    if _tech_buffer_conflict(route, planned_start, planned_end):
        raise ApiError(ERR_TECHNICIAN_SCHEDULE_CONFLICT,
                       "Less than 30 minutes between stops led by the same technician")
    # Capacity tier: water, then vehicles.
    if van_free_gal(van) < Decimal(str(projected)):
        raise ApiError(ERR_ROUTE_WATER_CAPACITY_EXCEEDED,
                       "Van free gallons are below the stop's projected net draw")
    if route_assigned_vehicle_count(route) + len(order["vehicle_ids"]) > 40:
        raise ApiError(ERR_ROUTE_VEHICLE_CAPACITY_EXCEEDED,
                       "Route would exceed 40 assigned vehicles")
    stop = {
        "route_id": route["id"],
        "wash_order_id": order["id"],
        "sequence": sequence,
        "planned_start_at": planned_start,
        "planned_end_at": planned_end,
        "status": "PLANNED",
        "reserved_water_gal": projected,
    }
    stamp_new(stop)
    store.stops[stop["id"]] = stop
    order["status"] = "ASSIGNED"
    touch(order)
    van["water_reserved_gal"] = gal_round(
        Decimal(str(van["water_reserved_gal"])) + Decimal(str(projected)))
    touch(van)
    touch(route)
    return respond(ser_stop(stop), 201)


@bp.get("/fleet-wash/routes/<rid>/stops")
def list_stops(rid):
    uid, role = caller()
    _get_route_or_404(rid)
    recs = stops_of_route(rid)
    if role == "Customer":
        recs = [s for s in recs if customer_of_stop(s) == uid]
    return paginate(recs, ser_stop, sort_key=lambda s: s["sequence"])


@bp.post("/fleet-wash/routes/<rid>/stops/<sid>/events")
def stop_event(rid, sid):
    uid, role = caller()
    require_role(role, {"Dispatcher", "Technician"})
    route = _get_route_or_404(rid)
    stop = store.stops.get(sid)
    if stop is None or stop["route_id"] != rid:
        raise ApiError(ERR_NOT_FOUND, "RouteStop %s not found" % sid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("ARRIVE", "SKIP", "REMOVE"):
        raise ApiError(ERR_VALIDATION, "event_type must be ARRIVE, SKIP, or REMOVE")
    is_lead = role == "Technician" and route["lead_technician_id"] == uid
    if event == "ARRIVE":
        if not is_lead:
            forbid("ARRIVE requires the route's lead Technician")
        if route["status"] not in ("PUBLISHED", "LOCKED"):
            raise ApiError(ERR_ROUTE_LOCKED,
                           "Route %s does not accept ARRIVE" % route["status"])
        if stop["status"] != "PLANNED":
            raise ApiError(ERR_INVALID_STATE, "Stop is not PLANNED")
        stop["status"] = "ARRIVED"
        touch(stop)
    elif event == "SKIP":
        if role != "Dispatcher" and not is_lead:
            forbid("SKIP requires the route's lead Technician or a Dispatcher")
        if stop["status"] not in ("PLANNED", "ARRIVED"):
            raise ApiError(ERR_INVALID_STATE, "Stop is not PLANNED or ARRIVED")
        van = store.vans.get(route["van_id"])
        if van is not None:
            van["water_reserved_gal"] = gal_round(
                Decimal(str(van["water_reserved_gal"])) - Decimal(str(stop["reserved_water_gal"])))
            touch(van)
        stop["status"] = "SKIPPED"
        touch(stop)
        order = store.orders.get(stop["wash_order_id"])
        if order is not None and order["status"] in ("ASSIGNED", "IN_PROGRESS"):
            order["status"] = "CANCELLED"
            order["cancel_reason"] = "NO_SHOW"
            touch(order)
            if order["rewash_of_id"] is not None:
                original = store.orders.get(order["rewash_of_id"])
                if original is not None and original["status"] == "REWASH_PENDING":
                    original["status"] = "COMPLETED"
                    touch(original)
        touch(route)
    else:  # REMOVE
        if role != "Dispatcher":
            forbid("REMOVE requires a Dispatcher")
        if route["status"] not in ("DRAFT", "PUBLISHED"):
            raise ApiError(ERR_ROUTE_LOCKED,
                           "Route %s does not accept stop removal" % route["status"])
        if stop["status"] != "PLANNED":
            raise ApiError(ERR_INVALID_STATE, "Stop is not PLANNED")
        van = store.vans.get(route["van_id"])
        if van is not None:
            van["water_reserved_gal"] = gal_round(
                Decimal(str(van["water_reserved_gal"])) - Decimal(str(stop["reserved_water_gal"])))
            touch(van)
        stop["status"] = "CANCELLED"
        touch(stop)
        order = store.orders.get(stop["wash_order_id"])
        if order is not None and order["status"] == "ASSIGNED":
            order["status"] = "SCHEDULED"
            touch(order)
        touch(route)
    return respond(ser_stop(stop), 200)
