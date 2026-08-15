"""ReplenishmentRoute and RouteStop endpoints."""

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, touch, parse_iso
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_int, as_dt,
    pagination_params, paginate,
)
from response import success, success_list
from services import create_replenishment_order, recompute_posture

bp = Blueprint("routes", __name__)

ROUTE_ROLES = ["DistributorAdmin", "RouteDriver"]


def serialize_route(r):
    return {
        "id": r["id"],
        "site_id": r["site_id"],
        "route_date": r["route_date"],
        "window_start": r["window_start"],
        "window_end": r["window_end"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_stop(s):
    return {
        "id": s["id"],
        "route_id": s["route_id"],
        "bin_agreement_id": s["bin_agreement_id"],
        "counted_qty": s["counted_qty"],
        "status": s["status"],
        "generated_order_id": s["generated_order_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.post("/vmi/routes")
def create_route():
    role = authenticate()
    body = json_body()
    site_id = as_str(need(body, "site_id"), "site_id")
    route_date = as_dt(need(body, "route_date"), "route_date")
    window_start = as_dt(need(body, "window_start"), "window_start")
    window_end = as_dt(need(body, "window_end"), "window_end")
    expected_site_version = as_int(
        need(body, "expected_site_version"), "expected_site_version"
    )
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        site = store.sites.get(site_id)
        if site is None:
            raise errors.not_found("site not found")
        if site["status"] == "RETIRED":
            raise errors.retired("site is RETIRED")
        # stage 9: half-open [window_start, window_end) overlap on the same site
        ws = parse_iso(window_start)
        we = parse_iso(window_end)
        if not ws < we:
            raise errors.route_window_overlap(
                "window_start must be strictly before window_end"
            )
        for other in store.routes.values():
            if other["site_id"] != site_id:
                continue
            if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            ows = parse_iso(other["window_start"])
            owe = parse_iso(other["window_end"])
            if ws < owe and ows < we:
                raise errors.route_window_overlap(
                    "window overlaps an existing route on this site"
                )
        # stage 15: OCC staleness
        if site["version"] != expected_site_version:
            raise errors.stale_version(
                "expected_site_version does not match the current site version"
            )
        ts = now_iso()
        route = {
            "id": new_id(),
            "site_id": site_id,
            "route_date": route_date,
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.routes[route["id"]] = route
        # scheduling advances the site version (why the OCC guard exists)
        touch(site)
        return success(serialize_route(route), 201)


@bp.get("/vmi/routes/<rid>")
def get_route(rid):
    role = authenticate()
    require_roles(role, ROUTE_ROLES)
    route = store.routes.get(rid)
    if route is None:
        raise errors.not_found("route not found")
    return success(serialize_route(route), 200)


@bp.get("/vmi/routes")
def list_routes():
    role = authenticate()
    require_roles(role, ROUTE_ROLES)
    limit, offset = pagination_params()
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = sorted(store.routes.values(), key=lambda r: r["_seq"])
    if site_id is not None:
        items = [r for r in items if r["site_id"] == site_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_route(r) for r in page], total, limit, offset)


@bp.post("/vmi/routes/<rid>/start")
def start_route(rid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["RouteDriver"])
    with store.lock:
        route = store.routes.get(rid)
        if route is None:
            raise errors.not_found("route not found")
        if route["status"] != "SCHEDULED":
            raise errors.invalid_state("route is not SCHEDULED")
        if store.clock_dt < parse_iso(route["window_start"]):
            raise errors.invalid_state(
                "logical clock has not reached the route window"
            )
        site = store.sites.get(route["site_id"])
        if site is None or site["status"] != "ACTIVE":
            raise errors.invalid_state("route site is not ACTIVE")
        route["status"] = "IN_PROGRESS"
        touch(route)
        return success(serialize_route(route), 200)


@bp.post("/vmi/routes/<rid>/cancel")
def cancel_route(rid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["RouteDriver"])
    with store.lock:
        route = store.routes.get(rid)
        if route is None:
            raise errors.not_found("route not found")
        if route["status"] != "SCHEDULED":
            raise errors.invalid_state("route is not SCHEDULED")
        route["status"] = "CANCELLED"
        touch(route)
        # pending stops carry no side effects and are deleted outright
        doomed = [
            sid for sid, s in store.stops.items()
            if s["route_id"] == rid and s["status"] == "PENDING"
        ]
        for sid in doomed:
            del store.stops[sid]
        return success(serialize_route(route), 200)


@bp.post("/vmi/routes/<rid>/close")
def close_route(rid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["RouteDriver"])
    with store.lock:
        route = store.routes.get(rid)
        if route is None:
            raise errors.not_found("route not found")
        if route["status"] != "IN_PROGRESS":
            raise errors.invalid_state("route is not IN_PROGRESS")
        stops = [s for s in store.stops.values() if s["route_id"] == rid]
        if not any(s["status"] == "SUBMITTED" for s in stops):
            raise errors.route_empty("route has no SUBMITTED stops")
        if any(s["status"] == "PENDING" for s in stops):
            raise errors.route_empty("route still has PENDING stops")
        route["status"] = "CLOSED"
        touch(route)
        return success(serialize_route(route), 200)


@bp.get("/vmi/routes/<rid>/stops")
def list_route_stops(rid):
    role = authenticate()
    require_roles(role, ROUTE_ROLES)
    limit, offset = pagination_params()
    route = store.routes.get(rid)
    if route is None:
        raise errors.not_found("route not found")
    items = sorted(
        (s for s in store.stops.values() if s["route_id"] == rid),
        key=lambda s: s["_seq"],
    )
    page, total = paginate(items, limit, offset)
    return success_list([serialize_stop(s) for s in page], total, limit, offset)


@bp.post("/vmi/routes/<rid>/stops")
def create_stop(rid):
    role = authenticate()
    body = json_body()
    bin_agreement_id = as_str(need(body, "bin_agreement_id"), "bin_agreement_id")
    require_roles(role, ["RouteDriver"])
    with store.lock:
        route = store.routes.get(rid)
        if route is None:
            raise errors.not_found("route not found")
        agr = store.agreements.get(bin_agreement_id)
        if agr is None:
            raise errors.not_found("bin agreement not found")
        if route["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise errors.invalid_state(
                "route is not accepting new stops from its current state"
            )
        if agr["status"] == "RETIRED":
            raise errors.retired("RETIRED bins accept no new stops")
        ts = now_iso()
        stop = {
            "id": new_id(),
            "route_id": rid,
            "bin_agreement_id": bin_agreement_id,
            "counted_qty": None,
            "status": "PENDING",
            "generated_order_id": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
            "_prev_scan_qty": None,
        }
        store.stops[stop["id"]] = stop
        return success(serialize_stop(stop), 201)


# ---------------------------------------------------------------------------
# Route stops
# ---------------------------------------------------------------------------

@bp.get("/vmi/route-stops/<sid>")
def get_stop(sid):
    role = authenticate()
    require_roles(role, ROUTE_ROLES)
    stop = store.stops.get(sid)
    if stop is None:
        raise errors.not_found("route stop not found")
    return success(serialize_stop(stop), 200)


@bp.get("/vmi/route-stops")
def list_stops():
    role = authenticate()
    require_roles(role, ROUTE_ROLES)
    limit, offset = pagination_params()
    route_id = request.args.get("route_id")
    bin_agreement_id = request.args.get("bin_agreement_id")
    generated_order_id = request.args.get("generated_order_id")
    status = request.args.get("status")
    items = sorted(store.stops.values(), key=lambda s: s["_seq"])
    if route_id is not None:
        items = [s for s in items if s["route_id"] == route_id]
    if bin_agreement_id is not None:
        items = [s for s in items if s["bin_agreement_id"] == bin_agreement_id]
    if generated_order_id is not None:
        items = [s for s in items if s["generated_order_id"] == generated_order_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_stop(s) for s in page], total, limit, offset)


@bp.post("/vmi/route-stops/<sid>/submit")
def submit_stop(sid):
    role = authenticate()
    body = json_body()
    counted_qty = as_int(need(body, "counted_qty"), "counted_qty")
    require_roles(role, ["RouteDriver"])
    with store.lock:
        stop = store.stops.get(sid)
        if stop is None:
            raise errors.not_found("route stop not found")
        # stage 5: transition legality (stop PENDING, route IN_PROGRESS)
        if stop["status"] != "PENDING":
            raise errors.invalid_state("route stop is not PENDING")
        route = store.routes.get(stop["route_id"])
        if route is None or route["status"] != "IN_PROGRESS":
            raise errors.invalid_state("route is not IN_PROGRESS")
        agr = store.agreements.get(stop["bin_agreement_id"])
        if agr is None:
            raise errors.not_found("bin agreement not found")
        # stage 6: live parents
        site = store.sites.get(agr["site_id"])
        if site is not None and site["status"] == "RETIRED":
            raise errors.retired("site is RETIRED")
        if agr["status"] == "RETIRED":
            raise errors.retired("bin agreement is RETIRED")
        # stage 12: count bounds
        if counted_qty < 0 or counted_qty > agr["max_qty"]:
            raise errors.quantity_bounds(
                "counted_qty must be >= 0 and <= the agreement max_qty"
            )
        # ---- transition PENDING -> SUBMITTED with cascade ----
        prior_submitted = [
            s for s in store.stops.values()
            if s["bin_agreement_id"] == agr["id"] and s["status"] == "SUBMITTED"
        ]
        if prior_submitted:
            prev = max(prior_submitted, key=lambda s: s["_seq"])["counted_qty"]
        else:
            prev = 0
        stop["_prev_scan_qty"] = prev
        stop["counted_qty"] = counted_qty
        stop["status"] = "SUBMITTED"
        touch(stop)
        agr["on_hand_qty"] = counted_qty
        if counted_qty < agr["min_qty"]:
            order = create_replenishment_order(agr, counted_qty)
            stop["generated_order_id"] = order["id"]
        touch(agr)
        recompute_posture(agr)
        return success(serialize_stop(stop), 200)
