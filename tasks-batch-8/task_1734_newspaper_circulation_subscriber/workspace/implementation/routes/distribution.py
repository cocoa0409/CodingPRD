"""DeliveryRoute, Carrier, RouteAssignment endpoints + carrier settlement."""
from flask import Blueprint, request

import domain
from db import bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_assignment, ser_carrier, ser_route
from util import parse_date
from validate import opt_int, req_enum, req_int, req_str, req_date, opt_date

bp = Blueprint("distribution", __name__)

COMPENSATION_MODELS = ("PER_COPY_GROSS", "PER_COPY_NET_OF_COMPLAINTS")
ROUTE_STATUSES = ("ACTIVE", "INACTIVE")
DIST_ROLES = ("DistrictManager", "CirculationDirector")
READ_ROLES = ("ServiceRep", "DistrictManager", "CirculationDirector")


# --- DeliveryRoute ----------------------------------------------------------

@bp.post("/api/routes")
def create_route():
    require_roles(*DIST_ROLES)
    b = body()
    route_code = req_str(b, "route_code")
    carrier_id = b.get("carrier_id")
    if carrier_id is not None:
        if not isinstance(carrier_id, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "carrier_id must be a string")
        domain.fetch(store.carriers, carrier_id)
    max_stops = req_int(b, "max_stops", min_v=1)
    # Uniqueness: route_code unique among non-INACTIVE routes.
    for r in store.routes.values():
        if r["route_code"] == route_code and r["status"] != "INACTIVE":
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "route_code must be unique among non-INACTIVE routes")
    rec = create_rec(store.routes, {
        "route_code": route_code,
        "carrier_id": carrier_id,
        "max_stops": max_stops,
        "assigned_stop_count": 0,
        "status": "ACTIVE",
    })
    return ok_obj(ser_route(rec), 201)


@bp.get("/api/routes")
def list_routes():
    require_roles(*READ_ROLES)
    recs = by_created(store.routes.values())
    carrier_id = request.args.get("carrier_id")
    if carrier_id is not None:
        recs = [r for r in recs if r["carrier_id"] == carrier_id]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_route)


@bp.get("/api/routes/<rid>")
def get_route(rid):
    require_roles(*READ_ROLES)
    return ok_obj(ser_route(domain.fetch(store.routes, rid)))


@bp.patch("/api/routes/<rid>")
def update_route(rid):
    require_roles(*DIST_ROLES)
    route = domain.fetch(store.routes, rid)
    b = body()
    changed = False
    if "carrier_id" in b:
        carrier_id = b.get("carrier_id")
        if carrier_id is not None:
            if not isinstance(carrier_id, str):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "carrier_id must be a string or null")
            domain.fetch(store.carriers, carrier_id)
        route["carrier_id"] = carrier_id
        changed = True
    if "max_stops" in b:
        route["max_stops"] = req_int(b, "max_stops", min_v=1)
        changed = True
    if "status" in b:
        status = req_enum(b, "status", ROUTE_STATUSES)
        if status != route["status"]:
            if route["status"] == "ACTIVE" and status == "INACTIVE":
                route["status"] = "INACTIVE"
            else:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Route status transition not permitted")
            changed = True
    if changed:
        bump(route)
    return ok_obj(ser_route(route))


# --- Carrier ----------------------------------------------------------------

@bp.post("/api/carriers")
def create_carrier():
    require_roles(*DIST_ROLES)
    b = body()
    display_name = req_str(b, "display_name")
    model = req_enum(b, "compensation_model", COMPENSATION_MODELS)
    rate = req_int(b, "per_copy_rate_cents", min_v=1)
    rec = create_rec(store.carriers, {
        "display_name": display_name,
        "compensation_model": model,
        "per_copy_rate_cents": rate,
        "status": "ACTIVE",
    })
    return ok_obj(ser_carrier(rec), 201)


@bp.get("/api/carriers")
def list_carriers():
    require_roles(*READ_ROLES)
    recs = by_created(store.carriers.values())
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_carrier)


@bp.get("/api/carriers/<cid>")
def get_carrier(cid):
    require_roles(*READ_ROLES)
    return ok_obj(ser_carrier(domain.fetch(store.carriers, cid)))


@bp.get("/api/carriers/<cid>/settlement")
def get_settlement(cid):
    require_roles("DistrictManager", "CirculationDirector")
    carrier = domain.fetch(store.carriers, cid)
    raw = request.args.get("week_start_date")
    week_start = parse_date(raw)
    if week_start is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "week_start_date query parameter must be an ISO date (YYYY-MM-DD)")
    return ok_obj(domain.carrier_settlement(carrier, week_start))


# --- RouteAssignment --------------------------------------------------------

@bp.post("/api/route-assignments")
def create_assignment():
    require_roles(*DIST_ROLES)
    b = body()
    subscription_id = req_str(b, "subscription_id")
    route_id = req_str(b, "route_id")
    start_date = req_date(b, "start_date")
    end_date = opt_date(b, "end_date")
    if end_date is not None and end_date < start_date:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_date must be on or after start_date")
    sub = domain.fetch(store.subscriptions, subscription_id)
    route = domain.fetch(store.routes, route_id)
    # State: subscription billing axis in the active set; route ACTIVE.
    if sub["billing_status"] not in domain.ACTIVE_SET:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Assignment requires billing_status ACTIVE or GRACE")
    if route["status"] != "ACTIVE":
        raise ApiError("ERR_ROUTE_INACTIVE", 409, "Route is INACTIVE")
    # Temporal: closed-interval collision with another ACTIVE assignment of
    # the same subscription — touching ends DO collide.
    for a in store.assignments.values():
        if a["subscription_id"] != sub["id"] or a["status"] != "ACTIVE":
            continue
        a_end = a["end_date"]
        new_end = end_date
        overlap = (a_end is None or start_date <= a_end) and \
                  (new_end is None or a["start_date"] <= new_end)
        if overlap:
            raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                           "Assignment interval collides with an ACTIVE assignment")
    # Referential: print-capable plans only.
    if not domain.print_capable(domain.plan_of(sub)):
        raise ApiError("ERR_DIGITAL_ONLY_PLAN", 409,
                       "Route assignments require a print-capable plan")
    # Capacity.
    if route["assigned_stop_count"] >= route["max_stops"]:
        raise ApiError("ERR_ROUTE_AT_CAPACITY", 409, "Route is at capacity")
    rec = create_rec(store.assignments, {
        "subscription_id": sub["id"],
        "route_id": route["id"],
        "start_date": start_date,
        "end_date": end_date,
        "status": "ACTIVE",
    })
    route["assigned_stop_count"] += 1
    bump(route)
    return ok_obj(ser_assignment(rec), 201)


@bp.get("/api/route-assignments")
def list_assignments():
    require_roles(*READ_ROLES)
    recs = by_created(store.assignments.values())
    subscription_id = request.args.get("subscription_id")
    if subscription_id is not None:
        recs = [a for a in recs if a["subscription_id"] == subscription_id]
    route_id = request.args.get("route_id")
    if route_id is not None:
        recs = [a for a in recs if a["route_id"] == route_id]
    status = request.args.get("status")
    if status is not None:
        recs = [a for a in recs if a["status"] == status]
    return paginate(recs, ser_assignment)


@bp.get("/api/route-assignments/<aid>")
def get_assignment(aid):
    require_roles(*READ_ROLES)
    return ok_obj(ser_assignment(domain.fetch(store.assignments, aid)))


@bp.post("/api/route-assignments/<aid>/end")
def end_assignment(aid):
    require_roles(*DIST_ROLES)
    asg = domain.fetch(store.assignments, aid)
    b = body()
    end_date = req_date(b, "end_date")
    if end_date < asg["start_date"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "end_date must be on or after start_date")
    if asg["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not ACTIVE")
    asg["end_date"] = end_date
    asg["status"] = "ENDED"
    bump(asg)
    route = store.routes.get(asg["route_id"])
    if route is not None and route["assigned_stop_count"] > 0:
        route["assigned_stop_count"] -= 1
        bump(route)
    return ok_obj(ser_assignment(asg))
