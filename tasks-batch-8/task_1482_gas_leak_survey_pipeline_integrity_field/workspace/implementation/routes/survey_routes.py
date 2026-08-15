"""SurveyRoute and RouteSegmentAssignment endpoints (PRD §3.4)."""
from flask import g, request

from db import STORE, make_entity, now, serialize, touch
from errors import bad_request, err, not_found
from middleware import (body, parse_pagination, req_dt, req_enum, req_int,
                        req_str, require_roles)
from response import list_response, success
from services import (FIELDS, compute_interval_days, compute_risk_score,
                      get_or_404, sorted_all)
from . import bp

SURVEY_METHODS = ["WALKING", "MOBILE", "AERIAL", "PATROL"]
ROUTE_ROLES = ("DispatchCoordinator", "IntegrityAnalyst", "FieldTechnician")


def ser(route):
    return serialize(route, FIELDS["survey_routes"])


def ser_assignment(a):
    return serialize(a, FIELDS["route_segment_assignments"])


@bp.post("/survey-routes")
@require_roles("DispatchCoordinator")
def create_route():
    d = body()
    code = req_str(d, "route_code")
    method = req_enum(d, "survey_method", SURVEY_METHODS)
    win_start = req_dt(d, "scheduled_window_start")
    win_end = req_dt(d, "scheduled_window_end")
    if any(r["route_code"] == code for r in STORE["survey_routes"].values()):
        raise bad_request("route_code must be unique")
    route = make_entity()
    route.update({"route_code": code, "survey_method": method,
                  "scheduled_window_start": win_start,
                  "scheduled_window_end": win_end, "status": "PLANNED"})
    STORE["survey_routes"][route["id"]] = route
    return success(ser(route), code=201)


@bp.get("/survey-routes")
@require_roles(*ROUTE_ROLES)
def list_routes():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    method = request.args.get("survey_method")
    items = sorted_all("survey_routes")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if method is not None:
        items = [r for r in items if r["survey_method"] == method]
    return list_response(items, ser, limit, offset)


@bp.get("/survey-routes/<rid>")
@require_roles(*ROUTE_ROLES)
def get_route(rid):
    return success(ser(get_or_404("survey_routes", rid)))


@bp.get("/survey-routes/<rid>/route-segment-assignments")
@require_roles(*ROUTE_ROLES)
def list_assignments(rid):
    get_or_404("survey_routes", rid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [a for a in sorted_all("route_segment_assignments")
             if a["route_id"] == rid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser_assignment, limit, offset)


@bp.post("/survey-routes/<rid>/route-segment-assignments")
@require_roles("DispatchCoordinator")
def add_assignment(rid):
    route = get_or_404("survey_routes", rid)
    d = body()
    segment_id = req_str(d, "segment_id")
    sequence_index = req_int(d, "sequence_index")
    if sequence_index < 1:
        raise bad_request("sequence_index must be >= 1")
    get_or_404("pipe_segments", segment_id)
    if route["status"] != "PLANNED":
        raise err("ERR_ROUTE_NOT_PLANNED", "SurveyRoute.status != PLANNED", 409)
    a = make_entity()
    a.update({"route_id": rid, "segment_id": segment_id,
              "sequence_index": sequence_index, "status": "PENDING"})
    STORE["route_segment_assignments"][a["id"]] = a
    return success(ser_assignment(a), code=201)


@bp.post("/survey-routes/<rid>/dispatch")
@require_roles("DispatchCoordinator")
def dispatch_route(rid):
    route = get_or_404("survey_routes", rid)
    if route["status"] != "PLANNED":
        raise err("ERR_ROUTE_NOT_PLANNED", "SurveyRoute.status != PLANNED", 409)
    for a in STORE["route_segment_assignments"].values():
        if a["route_id"] != rid:
            continue
        seg = STORE["pipe_segments"].get(a["segment_id"])
        if seg is None or seg["status"] != "ACTIVE":
            raise err("ERR_ROUTE_INCLUDES_INACTIVE_SEGMENT",
                      "Route contains a segment not in ACTIVE status", 422)
    if now() >= route["scheduled_window_end"]:
        raise err("ERR_ROUTE_WINDOW_PASSED",
                  "Current logical clock beyond scheduled_window_end", 422)
    route["status"] = "DISPATCHED"
    touch(route)
    return success(ser(route))


@bp.post("/survey-routes/<rid>/start")
@require_roles("FieldTechnician")
def start_route(rid):
    route = get_or_404("survey_routes", rid)
    if route["status"] != "DISPATCHED":
        raise err("ERR_ROUTE_NOT_DISPATCHED",
                  "SurveyRoute.status != DISPATCHED", 409)
    tech = STORE["field_technicians"].get(g.user_id)
    if tech is None:
        raise not_found("FieldTechnician record not found for X-User-ID")
    if route["survey_method"] not in tech["qualified_methods"]:
        raise err("ERR_TECHNICIAN_NOT_QUALIFIED",
                  "FieldTechnician.qualified_methods missing route's "
                  "survey_method", 422)
    n = now()
    if not (route["scheduled_window_start"] <= n < route["scheduled_window_end"]):
        raise err("ERR_OUTSIDE_SCHEDULED_WINDOW",
                  "Route start attempted outside scheduled window", 422)
    route["status"] = "IN_PROGRESS"
    touch(route)
    return success(ser(route))


@bp.post("/survey-routes/<rid>/complete")
@require_roles("FieldTechnician")
def complete_route(rid):
    route = get_or_404("survey_routes", rid)
    if route["status"] != "IN_PROGRESS":
        raise err("ERR_ROUTE_NOT_IN_PROGRESS",
                  "SurveyRoute.status != IN_PROGRESS", 409)
    accepted = [r for r in STORE["survey_runs"].values()
                if r["route_id"] == rid and r["status"] == "ACCEPTED"]
    if not accepted:
        raise err("ERR_NO_ACCEPTED_RUN",
                  "Route completion requires at least one ACCEPTED SurveyRun",
                  422)
    completed_at = now()
    for a in STORE["route_segment_assignments"].values():
        if a["route_id"] != rid or a["status"] != "COVERED":
            continue
        seg = STORE["pipe_segments"].get(a["segment_id"])
        if seg is None:
            continue
        seg["last_surveyed_at"] = completed_at
        interval = compute_interval_days(seg)
        from datetime import timedelta
        seg["next_survey_due_at"] = completed_at + timedelta(days=interval)
        seg["risk_score"] = compute_risk_score(seg)
        touch(seg)
    route["status"] = "COMPLETED"
    touch(route)
    return success(ser(route))


@bp.post("/survey-routes/<rid>/abort")
@require_roles("DispatchCoordinator")
def abort_route(rid):
    route = get_or_404("survey_routes", rid)
    if route["status"] not in ("PLANNED", "DISPATCHED"):
        raise err("ERR_ROUTE_NOT_ABORTABLE",
                  "SurveyRoute not in PLANNED or DISPATCHED", 409)
    route["status"] = "ABORTED"
    touch(route)
    return success(ser(route))
