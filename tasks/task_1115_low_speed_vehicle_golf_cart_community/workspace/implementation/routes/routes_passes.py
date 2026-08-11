"""Route and RoutePass endpoints, incl. decommission cascade and half-open
overlap semantics per PRD §2.10 / §3.7."""
from flask import Blueprint, request

import db
from db import touch
from errors import (err_not_found, err_invalid_state, err_route_not_designated,
                    err_route_vehicle_class, err_route_pass_overlap,
                    err_holder_not_eligible)
from middleware import get_caller, require_role, check_holder_ownership
from response import ok_object, ok_list
from services import validate as v
from services.serializers import base_entity, route_view, route_pass_view

bp = Blueprint("routes_passes", __name__)

READ_ROLES = ["PlatformAdmin", "CommunityAdmin", "Inspector", "EnforcementOfficer", "PermitHolder"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@bp.post("/api/routes")
def create_route():
    data = v.body()
    community_id = v.require_str(data, "community_id")
    name = v.require_str(data, "name")
    route_type = v.require_enum(data, "route_type", {"STREET", "PATH"})
    allowed_class = v.require_enum(data, "allowed_vehicle_class", {"GOLF_CART_ONLY", "LSV_ALLOWED"})
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    if db.communities.get(community_id) is None:
        raise err_not_found("Community not found")

    r = base_entity()
    r.update({
        "community_id": community_id,
        "name": name,
        "route_type": route_type,
        "allowed_vehicle_class": allowed_class,
        "designation_status": "DESIGNATED",
    })
    db.routes[r["id"]] = r
    return ok_object(route_view(r), 201)


@bp.get("/api/routes/<rid>")
def get_route(rid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    r = db.routes.get(rid)
    if r is None:
        raise err_not_found("Route not found")
    return ok_object(route_view(r))


@bp.get("/api/routes")
def list_routes():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    community_id = request.args.get("community_id")
    rows = list(db.routes.values())
    if community_id is not None:
        rows = [r for r in rows if r["community_id"] == community_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([route_view(r) for r in page], limit, offset, total)


@bp.post("/api/routes/<rid>/decommission")
def decommission_route(rid):
    caller = get_caller()
    require_role(caller, ["CommunityAdmin"])
    r = db.routes.get(rid)
    if r is None:
        raise err_not_found("Route not found")
    if r["designation_status"] != "DESIGNATED":
        raise err_invalid_state("Route is not DESIGNATED")
    r["designation_status"] = "DECOMMISSIONED"
    touch(r)
    for p in db.route_passes.values():
        if p["route_id"] == rid and p["status"] == "ACTIVE":
            p["status"] = "REVOKED"
            touch(p)
    return ok_object(route_view(r))


# ---------------------------------------------------------------------------
# Route passes
# ---------------------------------------------------------------------------
@bp.post("/api/route-passes")
def create_route_pass():
    data = v.body()
    route_id = v.require_str(data, "route_id")
    registration_id = v.require_str(data, "registration_id")
    holder_id = v.require_str(data, "holder_id")
    start_at, end_at = v.require_window(data, "start_at", "end_at")
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    check_holder_ownership(caller, holder_id)
    # Stage 4: body FKs in declared order
    route = db.routes.get(route_id)
    if route is None:
        raise err_not_found("Route not found")
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise err_not_found("Registration not found")
    holder = db.permit_holders.get(holder_id)
    if holder is None:
        raise err_not_found("PermitHolder not found")
    if reg["holder_id"] != holder_id:
        raise err_not_found("Registration does not belong to the supplied holder")
    # Stage 6: safety gate — vehicle class admissibility
    veh = db.vehicles.get(reg["vehicle_id"])
    if route["allowed_vehicle_class"] == "GOLF_CART_ONLY" and veh["vehicle_type"] == "LSV":
        raise err_route_vehicle_class()
    # Stage 7: half-open overlap vs other ACTIVE passes on this registration
    for p in db.route_passes.values():
        if p["registration_id"] != registration_id or p["status"] != "ACTIVE":
            continue
        # half-open [start,end): overlap iff new.start < existing.end AND existing.start < new.end
        if start_at < p["end_at"] and p["start_at"] < end_at:
            raise err_route_pass_overlap()
    # Stage 8: cross-entity state gates
    if holder["eligibility_status"] != "ELIGIBLE":
        raise err_holder_not_eligible()
    if reg["status"] != "ACTIVE":
        from errors import ApiError
        raise ApiError("ERR_REGISTRATION_NOT_ACTIVE", 422, "Registration is not ACTIVE")
    if route["designation_status"] != "DESIGNATED":
        raise err_route_not_designated()

    p = base_entity()
    p.update({
        "route_id": route_id,
        "registration_id": registration_id,
        "holder_id": holder_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "ACTIVE",
    })
    db.route_passes[p["id"]] = p
    return ok_object(route_pass_view(p), 201)


@bp.get("/api/route-passes/<pid>")
def get_route_pass(pid):
    caller = get_caller()
    require_role(caller, READ_ROLES)
    p = db.route_passes.get(pid)
    if p is None:
        raise err_not_found("RoutePass not found")
    check_holder_ownership(caller, p["holder_id"])
    return ok_object(route_pass_view(p))


@bp.get("/api/route-passes")
def list_route_passes():
    caller = get_caller()
    require_role(caller, READ_ROLES)
    limit, offset = v.pagination_args()
    route_id = request.args.get("route_id")
    registration_id = request.args.get("registration_id")
    holder_id = request.args.get("holder_id")
    rows = list(db.route_passes.values())
    if route_id is not None:
        rows = [p for p in rows if p["route_id"] == route_id]
    if registration_id is not None:
        rows = [p for p in rows if p["registration_id"] == registration_id]
    if holder_id is not None:
        rows = [p for p in rows if p["holder_id"] == holder_id]
    if caller.role == "PermitHolder":
        rows = [p for p in rows if p["holder_id"] == caller.user_id]
    rows = v.sorted_by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([route_pass_view(p) for p in page], limit, offset, total)


@bp.post("/api/route-passes/<pid>/cancel")
def cancel_route_pass(pid):
    caller = get_caller()
    require_role(caller, ["PermitHolder"])
    p = db.route_passes.get(pid)
    if p is None:
        raise err_not_found("RoutePass not found")
    check_holder_ownership(caller, p["holder_id"])
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Route pass is not ACTIVE")
    if not (db.now() < p["start_at"]):
        raise err_invalid_state("A pass whose window has begun cannot be cancelled")
    p["status"] = "CANCELLED"
    touch(p)
    return ok_object(route_pass_view(p))
