"""Crew, Route, and WeatherAdvisory endpoints, including the guarded visit
commit (POST /routes/{id}/visits)."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from helpers import (
    REGIONS, SKILL_CODES, body, get_or_404, paginate, pagination_params,
    recompute_route_minutes, req_int, req_str, req_enum,
)
from response import success, list_success
from serialize import public, public_list

bp = Blueprint("fleet", __name__)

_ON_ROUTE_STATUSES = {"SCHEDULED", "DISPATCHED", "IN_PROGRESS"}


# ---------------------------------------------------------------- Crews
@bp.post("/crews")
def create_crew():
    require_roles({"Dispatcher"})
    data = body()
    crew_name = req_str(data, "crew_name")
    region_code = req_enum(data, "region_code", REGIONS)
    daily_capacity_minutes = req_int(data, "daily_capacity_minutes")
    if daily_capacity_minutes <= 0:
        raise err("ERR_INVALID_REQUEST", "daily_capacity_minutes must be > 0")
    skill_codes = []
    if data.get("skill_codes") is not None:
        raw = data["skill_codes"]
        if not isinstance(raw, list):
            raise err("ERR_INVALID_REQUEST", "skill_codes must be a list")
        for s in raw:
            if not isinstance(s, str) or s not in SKILL_CODES:
                raise err("ERR_INVALID_REQUEST", "skill_codes contains an invalid value")
            skill_codes.append(s)
    rec = db.new_record(db.crews, {
        "crew_name": crew_name,
        "region_code": region_code,
        "skill_codes": skill_codes,
        "daily_capacity_minutes": daily_capacity_minutes,
        "status": "AVAILABLE",
    })
    return success(public(rec), status=201)


@bp.get("/crews/<rid>")
def read_crew(rid):
    require_roles({"Dispatcher", "Billing"})
    rec = get_or_404(db.crews, rid)
    return success(public(rec))


@bp.post("/crews/<rid>/set-status")
def set_crew_status(rid):
    require_roles({"Dispatcher"})
    rec = get_or_404(db.crews, rid)
    data = body()
    new_status = req_enum(data, "status", {"AVAILABLE", "OFFLINE"})
    if new_status == "OFFLINE":
        if rec["status"] != "AVAILABLE":
            raise err("ERR_INVALID_STATE", "Crew is not AVAILABLE")
    else:  # AVAILABLE
        if rec["status"] != "OFFLINE":
            raise err("ERR_INVALID_STATE", "Crew is not OFFLINE")
    rec["status"] = new_status
    db.touch(rec)
    return success(public(rec))


# ---------------------------------------------------------------- Routes
@bp.post("/routes")
def create_route():
    require_roles({"Dispatcher"})
    data = body()
    crew_id = req_str(data, "crew_id")
    region_code = req_enum(data, "region_code", REGIONS)
    service_date = req_str(data, "service_date")
    crew = get_or_404(db.crews, crew_id)
    # route.region must equal crew.region.
    if region_code != crew["region_code"]:
        raise err("ERR_REFERENTIAL_MISMATCH", "route region must equal crew region")
    # Whole-day crew exclusivity: at most one non-CLOSED route per service_date.
    for r in db.routes.values():
        if (r["crew_id"] == crew_id and r["service_date"] == service_date
                and r["status"] != "CLOSED"):
            raise err("ERR_CREW_DOUBLE_BOOKED", "Crew already has a non-CLOSED route on this date")
    rec = db.new_record(db.routes, {
        "crew_id": crew_id,
        "region_code": region_code,
        "service_date": service_date,
        "booked_minutes": 0,
        "status": "PLANNING",
    })
    return success(public(rec), status=201)


@bp.get("/routes")
def list_routes():
    require_roles({"Dispatcher", "Billing"})
    limit, offset = pagination_params()
    crew_id = request.args.get("crew_id")
    service_date = request.args.get("service_date")
    rows = list(db.routes.values())
    if crew_id is not None:
        rows = [r for r in rows if r["crew_id"] == crew_id]
    if service_date is not None:
        rows = [r for r in rows if r["service_date"] == service_date]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/routes/<rid>")
def read_route(rid):
    require_roles({"Dispatcher", "Billing"})
    rec = get_or_404(db.routes, rid)
    return success(public(rec))


@bp.get("/routes/<rid>/visits")
def list_route_visits(rid):
    require_roles({"Dispatcher", "Billing", "FieldCrew"})
    get_or_404(db.routes, rid)
    limit, offset = pagination_params()
    rows = [v for v in db.visits.values() if v.get("route_id") == rid]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start,end) overlap test; touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end


@bp.post("/routes/<rid>/visits")
def commit_visit(rid):
    require_roles({"Dispatcher"})
    route = get_or_404(db.routes, rid)
    data = body()
    visit_id = req_str(data, "visit_id")
    expected_version = req_int(data, "expected_route_version")
    visit = get_or_404(db.visits, visit_id)

    agreement = db.agreements.get(visit["agreement_id"])
    if agreement is None:
        raise err("ERR_REFERENTIAL_MISMATCH", "visit agreement does not resolve")
    crew = db.crews.get(route["crew_id"])
    prop = db.properties.get(visit["property_id"])
    account = db.accounts.get(agreement["account_id"]) if agreement else None

    # ---- state guards (priority order, §3.9) ----
    # generic transition-defined guard first
    if visit["schedule_status"] != "UNSCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit is not UNSCHEDULED")
    # agreement-active precedes route-planning
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement is not ACTIVE")
    if route["status"] != "PLANNING":
        raise err("ERR_ROUTE_NOT_PLANNING", "Route is not in PLANNING")

    # ---- business-safety: crew skills ----
    crew_skills = set(crew["skill_codes"]) if crew else set()
    if visit["requires_soft_wash"] and "SOFT_WASH" not in crew_skills:
        raise err("ERR_CREW_SKILL_MISSING", "Crew lacks SOFT_WASH skill")
    if visit["requires_high_rise"] and "HIGH_RISE" not in crew_skills:
        raise err("ERR_CREW_SKILL_MISSING", "Crew lacks HIGH_RISE skill")

    # ---- business-constraint / temporal ----
    if account is None or account["region_code"] != route["region_code"]:
        raise err("ERR_REGION_MISMATCH", "Visit region != route region")
    if visit["planned_date"] != route["service_date"]:
        raise err("ERR_DATE_MISMATCH", "visit.planned_date != route.service_date")
    # window overlap against SCHEDULED|DISPATCHED|IN_PROGRESS visits on this route
    for other in db.visits.values():
        if other["id"] == visit_id:
            continue
        if other.get("route_id") != rid:
            continue
        if other["schedule_status"] not in _ON_ROUTE_STATUSES:
            continue
        if _windows_overlap(visit["window_start_min"], visit["window_end_min"],
                            other["window_start_min"], other["window_end_min"]):
            raise err("ERR_VISIT_WINDOW_OVERLAP", "Visit window overlaps an existing visit")

    # ---- fiscal: capacity ----
    if route["booked_minutes"] + visit["duration_minutes"] > crew["daily_capacity_minutes"]:
        raise err("ERR_ROUTE_CAPACITY_EXCEEDED", "Route capacity exceeded")

    # ---- OCC (last) ----
    if expected_version != route["version"]:
        raise err("ERR_STALE_ROUTE_VERSION", "expected_route_version != route.version")

    # commit
    visit["route_id"] = rid
    visit["schedule_status"] = "SCHEDULED"
    db.touch(visit)
    recompute_route_minutes(route)
    return success(public(visit), status=201)


@bp.post("/routes/<rid>/dispatch")
def dispatch_route(rid):
    require_roles({"Dispatcher"})
    route = get_or_404(db.routes, rid)
    if route["status"] != "PLANNING":
        raise err("ERR_INVALID_STATE", "Route is not in PLANNING")
    crew = db.crews.get(route["crew_id"])
    if crew is None or crew["status"] != "AVAILABLE":
        raise err("ERR_CREW_OFFLINE", "Crew is OFFLINE")
    committed = [
        v for v in db.visits.values()
        if v.get("route_id") == rid and v["schedule_status"] == "SCHEDULED"
    ]
    if not committed:
        raise err("ERR_EMPTY_ROUTE", "Route has no committed visits")
    route["status"] = "DISPATCHED"
    db.touch(route)
    for v in committed:
        v["schedule_status"] = "DISPATCHED"
        db.touch(v)
    return success(public(route))


@bp.post("/routes/<rid>/close")
def close_route(rid):
    require_roles({"Dispatcher"})
    route = get_or_404(db.routes, rid)
    if route["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Route is not in DISPATCHED")
    open_ones = any(
        v.get("route_id") == rid and v["schedule_status"] in ("DISPATCHED", "IN_PROGRESS")
        for v in db.visits.values()
    )
    if open_ones:
        raise err("ERR_OPEN_VISITS_EXIST", "Open committed visits remain")
    route["status"] = "CLOSED"
    db.touch(route)
    return success(public(route))


# ---------------------------------------------------------------- Weather
@bp.post("/weather-advisories")
def create_weather_advisory():
    require_roles({"Dispatcher"})
    data = body()
    region_code = req_enum(data, "region_code", REGIONS)
    advisory_date = req_str(data, "advisory_date")
    severity = req_enum(data, "severity", {"ADVISORY", "SUSPEND"})
    rec = db.new_record(db.weather_advisories, {
        "region_code": region_code,
        "advisory_date": advisory_date,
        "severity": severity,
    })
    return success(public(rec), status=201)


@bp.get("/weather-advisories/<rid>")
def read_weather_advisory(rid):
    require_roles({"Dispatcher"})
    rec = get_or_404(db.weather_advisories, rid)
    return success(public(rec))
