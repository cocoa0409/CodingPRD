"""Technicians and ServiceRoutes."""
from flask import Blueprint, request

import services as svc
from clock import now, parse_dt
from errors import ApiError, err_invalid_request, err_invalid_state, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    optional,
    optional_dt,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("field", __name__)


# ------------------------------- Technicians --------------------------------

@bp.post("/api/technicians")
def create_technician():
    auth("OperationsManager")
    data = get_body()
    full_name = require(data, "full_name", str)
    employee_code = require(data, "employee_code", str)
    certified = optional(data, "certified_for_aggressive_pets", bool, False)
    for t in svc.technicians.values():
        if t["employee_code"] == employee_code:
            raise err_invalid_request("employee_code must be unique")
    rec = svc.new_record()
    rec.update(
        {
            "full_name": full_name,
            "employee_code": employee_code,
            "certified_for_aggressive_pets": certified,
            "active": True,
        }
    )
    svc.technicians[rec["id"]] = rec
    return ok_object(svc.ser_technician(rec), status=201)


@bp.get("/api/technicians/<tid>")
def get_technician(tid):
    uid, role = auth("OperationsManager", "Technician")
    rec = lookup(svc.technicians, tid, "Technician")
    if role == "Technician" and rec["id"] != uid:
        raise err_unauthorized("Technicians may only access their own record")
    return ok_object(svc.ser_technician(rec))


# ------------------------------- ServiceRoutes ------------------------------

@bp.post("/api/service-routes")
def create_route():
    auth("OperationsManager")
    data = get_body()
    route_code = require(data, "route_code", str)
    service_date = None
    raw_date = require(data, "service_date", str)
    try:
        service_date = parse_dt(raw_date)
    except ValueError:
        raise err_invalid_request("service_date must be a valid ISO 8601 date")
    region = require(data, "service_region_code", str)
    max_cap = require(data, "max_visit_capacity", int)
    tech_id = optional(data, "assigned_technician_id", str)
    if max_cap < 1:
        raise err_invalid_request("max_visit_capacity must be >= 1")
    if tech_id is not None:
        lookup_fk(svc.technicians, tech_id, "Technician")
    for r in svc.routes.values():
        if (
            r["route_code"] == route_code
            and r["service_date"].date() == service_date.date()
        ):
            raise err_invalid_request("route_code must be unique per service_date")
    rec = svc.new_record()
    rec.update(
        {
            "route_code": route_code,
            "service_date": service_date,
            "service_region_code": region,
            "assigned_technician_id": tech_id,
            "max_visit_capacity": max_cap,
            "committed_visit_count": 0,
            "route_load_factor_bp": 0,
            "route_status": "PLANNED",
        }
    )
    svc.routes[rec["id"]] = rec
    return ok_object(svc.ser_route(rec), status=201)


@bp.get("/api/service-routes/<rid>")
def get_route(rid):
    auth("OperationsManager", "Technician", "BillingAdmin")
    rec = lookup(svc.routes, rid, "ServiceRoute")
    return ok_object(svc.ser_route(rec))


@bp.get("/api/service-routes")
def list_routes():
    auth("OperationsManager", "Technician", "BillingAdmin")
    limit, offset = parse_pagination()
    records = list(svc.routes.values())
    date_param = request.args.get("service_date")
    if date_param is not None:
        try:
            d = parse_dt(date_param).date()
        except ValueError:
            raise err_invalid_request("service_date filter is malformed")
        records = [r for r in records if r["service_date"].date() == d]
    region = request.args.get("service_region_code")
    if region is not None:
        records = [r for r in records if r["service_region_code"] == region]
    status = request.args.get("route_status")
    if status is not None:
        records = [r for r in records if r["route_status"] == status]
    tech = request.args.get("assigned_technician_id")
    if tech is not None:
        records = [r for r in records if r["assigned_technician_id"] == tech]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_route(r) for r in page], total, limit, offset)


@bp.get("/api/service-routes/<rid>/visits")
def route_visit_list(rid):
    auth("OperationsManager", "Technician", "BillingAdmin")
    route = lookup(svc.routes, rid, "ServiceRoute")
    limit, offset = parse_pagination()
    records = svc.route_visits(route["id"])
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_visit(v) for v in page], total, limit, offset)


@bp.post("/api/service-routes/<rid>/publish")
def publish_route(rid):
    auth("OperationsManager")
    route = lookup(svc.routes, rid, "ServiceRoute")
    if route["route_status"] != "PLANNED":
        raise err_invalid_state("publish is only valid from PLANNED")
    if not route["assigned_technician_id"]:
        raise ApiError("ERR_TECH_REQUIRED", 422,
                       "Route publish requires an assigned technician")
    tech = svc.technicians.get(route["assigned_technician_id"])
    if tech is None or not tech["active"]:
        raise ApiError("ERR_TECH_INACTIVE", 422,
                       "Assigned technician is inactive")
    svc.recompute_route(route, do_bump=False)
    if route["committed_visit_count"] < 1:
        raise ApiError("ERR_EMPTY_ROUTE", 422,
                       "Route publish requires at least one committed visit")
    route["route_status"] = "PUBLISHED"
    svc.bump(route)
    return ok_object(svc.ser_route(route))


@bp.post("/api/service-routes/<rid>/unpublish")
def unpublish_route(rid):
    auth("OperationsManager")
    route = lookup(svc.routes, rid, "ServiceRoute")
    if route["route_status"] != "PUBLISHED":
        raise err_invalid_state("unpublish is only valid from PUBLISHED")
    for v in svc.route_visits(route["id"]):
        if v["status"] in ("EN_ROUTE", "ON_SITE"):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot unpublish while a visit is EN_ROUTE or ON_SITE")
    route["route_status"] = "PLANNED"
    svc.bump(route)
    return ok_object(svc.ser_route(route))


@bp.post("/api/service-routes/<rid>/start")
def start_route(rid):
    uid, _ = auth("Technician")
    route = lookup(svc.routes, rid, "ServiceRoute")
    if route["route_status"] != "PUBLISHED":
        raise err_invalid_state("start is only valid from PUBLISHED")
    if route["assigned_technician_id"] != uid:
        raise ApiError("ERR_ROUTE_TECH_MISMATCH", 403,
                       "Acting technician is not the route's assigned technician")
    if now().date() != route["service_date"].date():
        raise ApiError("ERR_ROUTE_WRONG_DAY", 409,
                       "Route may only be started on its service_date")
    route["route_status"] = "IN_PROGRESS"
    svc.bump(route)
    return ok_object(svc.ser_route(route))


@bp.post("/api/service-routes/<rid>/close")
def close_route(rid):
    auth("OperationsManager")
    route = lookup(svc.routes, rid, "ServiceRoute")
    if route["route_status"] != "IN_PROGRESS":
        raise err_invalid_state("close is only valid from IN_PROGRESS")
    rvs = svc.route_visits(route["id"])
    if not all(v["status"] in svc.TERMINAL_VISIT_STATES for v in rvs):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "All visits on the route must be in a terminal state")
    route["route_status"] = "CLOSED"
    svc.bump(route)
    return ok_object(svc.ser_route(route))
