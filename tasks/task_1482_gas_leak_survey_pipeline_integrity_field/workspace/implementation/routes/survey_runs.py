"""SurveyRun endpoints (PRD §3.4)."""
from flask import g, request

from db import STORE, make_entity, now, serialize, touch
from errors import err
from middleware import body, parse_pagination, req_num, req_str, require_roles
from response import list_response, success
from services import (FIELDS, MIN_COVERAGE_PCT, compute_coverage, get_or_404,
                      refresh_segment, sorted_all)
from . import bp

RUN_ROLES = ("FieldTechnician", "IntegrityAnalyst", "DispatchCoordinator")


def ser(run):
    return serialize(run, FIELDS["survey_runs"])


@bp.post("/survey-runs")
@require_roles("FieldTechnician")
def create_run():
    d = body()
    route_id = req_str(d, "route_id")
    instrument_id = req_str(d, "instrument_id")
    distance = req_num(d, "distance_covered_feet")
    if distance < 0:
        from errors import bad_request
        raise bad_request("distance_covered_feet must be >= 0")
    get_or_404("survey_routes", route_id)
    inst = get_or_404("instruments", instrument_id)
    if inst["status"] != "IN_SERVICE":
        raise err("ERR_INSTRUMENT_OUT_OF_CALIBRATION",
                  "Instrument.status != IN_SERVICE at run start", 422)
    run = make_entity()
    run.update({"route_id": route_id, "instrument_id": instrument_id,
                "technician_id": g.user_id, "started_at": now(),
                "ended_at": None, "distance_covered_feet": distance,
                "coverage_pct": 0.0, "status": "DRAFT"})
    _, pct = compute_coverage(run)
    run["coverage_pct"] = pct
    STORE["survey_runs"][run["id"]] = run
    return success(ser(run), code=201)


@bp.get("/survey-runs")
@require_roles(*RUN_ROLES)
def list_runs():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    route_id = request.args.get("route_id")
    instrument_id = request.args.get("instrument_id")
    items = sorted_all("survey_runs")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if route_id is not None:
        items = [r for r in items if r["route_id"] == route_id]
    if instrument_id is not None:
        items = [r for r in items if r["instrument_id"] == instrument_id]
    return list_response(items, ser, limit, offset)


@bp.get("/survey-runs/<rid>")
@require_roles(*RUN_ROLES)
def get_run(rid):
    return success(ser(get_or_404("survey_runs", rid)))


@bp.post("/survey-runs/<rid>/submit")
@require_roles("FieldTechnician")
def submit_run(rid):
    run = get_or_404("survey_runs", rid)
    # PRD §3.4: ownership first, then state, then instrument currency.
    if run["technician_id"] != g.user_id:
        raise err("ERR_NOT_RUN_OWNER", "X-User-ID != SurveyRun.technician_id",
                  403)
    if run["status"] != "DRAFT":
        raise err("ERR_RUN_NOT_DRAFT", "SurveyRun.status != DRAFT", 409)
    inst = STORE["instruments"].get(run["instrument_id"])
    if inst is None or inst["status"] != "IN_SERVICE":
        raise err("ERR_INSTRUMENT_OUT_OF_CALIBRATION",
                  "Instrument.status != IN_SERVICE at run submit", 422)
    run["status"] = "SUBMITTED"
    run["ended_at"] = now()
    touch(run)
    return success(ser(run))


@bp.post("/survey-runs/<rid>/accept")
@require_roles("IntegrityAnalyst")
def accept_run(rid):
    run = get_or_404("survey_runs", rid)
    if run["status"] != "SUBMITTED":
        raise err("ERR_RUN_NOT_SUBMITTED", "SurveyRun.status != SUBMITTED", 409)
    if run["technician_id"] == g.user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Accepting analyst must differ from the run's technician", 422)
    covered_ids, pct = compute_coverage(run)
    if pct < MIN_COVERAGE_PCT:
        raise err("ERR_COVERAGE_BELOW_MINIMUM",
                  "SurveyRun coverage_pct below 95", 422)
    run["coverage_pct"] = pct
    for aid in covered_ids:
        a = STORE["route_segment_assignments"].get(aid)
        if a is not None and a["status"] != "COVERED":
            a["status"] = "COVERED"
            touch(a)
    seen = set()
    for aid in covered_ids:
        a = STORE["route_segment_assignments"].get(aid)
        seg = (STORE["pipe_segments"].get(a["segment_id"])
               if a is not None else None)
        if seg is not None and seg["id"] not in seen:
            seen.add(seg["id"])
            refresh_segment(seg)
    run["status"] = "ACCEPTED"
    touch(run)
    return success(ser(run))


@bp.post("/survey-runs/<rid>/reject")
@require_roles("IntegrityAnalyst")
def reject_run(rid):
    run = get_or_404("survey_runs", rid)
    if run["status"] != "SUBMITTED":
        raise err("ERR_RUN_NOT_SUBMITTED", "SurveyRun.status != SUBMITTED", 409)
    affected = set()
    for leak in STORE["leaks"].values():
        if leak["survey_run_id"] == rid and leak["status"] == "OPEN":
            leak["status"] = "ABANDONED_SEGMENT"
            touch(leak)
            affected.add(leak["segment_id"])
    for sid in affected:
        seg = STORE["pipe_segments"].get(sid)
        if seg is not None:
            refresh_segment(seg)
    run["status"] = "REJECTED"
    touch(run)
    return success(ser(run))
