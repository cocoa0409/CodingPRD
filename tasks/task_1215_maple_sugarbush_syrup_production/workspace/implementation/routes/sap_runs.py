"""SapRun endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import db
from middleware import authenticate, require_role, enforce_entity_identity
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_str,
                  as_number, d, parse_dt, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_SEASON_NOT_OPEN, ERR_SEASON_SUSPENDED,
                    ERR_SUGARBUSH_NOT_LIVE, ERR_WINDOW_NOT_OPEN,
                    ERR_COLLECTED_OUTSIDE_WINDOW, ERR_CREW_NOT_ACTIVE,
                    ERR_RUN_HAS_DRAWS)
from services import core

bp = Blueprint("sap_runs", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}
COLLECTORS = {"SugarhouseManager", "FieldCrew"}


def get_run_or_404(rid):
    r = db.sap_runs.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, f"sap run {rid} not found")
    return r


@bp.post("/sugarhouse/sap-runs")
def create_run():
    caller = authenticate()
    require_role(caller, COLLECTORS)
    data = body_json()
    allowed = {"sugarbush_id", "weather_window_id", "collected_by",
               "gallons_collected", "measured_brix"}
    check_unknown_fields(data, allowed)
    require_fields(data, ["sugarbush_id", "weather_window_id", "collected_by",
                          "gallons_collected", "measured_brix"])
    sugarbush_id = as_str(data["sugarbush_id"], "sugarbush_id")
    weather_window_id = as_str(data["weather_window_id"], "weather_window_id")
    collected_by = as_str(data["collected_by"], "collected_by")
    gallons_collected = as_number(data["gallons_collected"], "gallons_collected",
                                  minimum=0, exclusive_min=True)
    measured_brix = as_number(data["measured_brix"], "measured_brix",
                              minimum="0.5", maximum="40.0")

    # Priority 2: entity-backed identity (FieldCrew collected_by == X-User-ID)
    enforce_entity_identity(caller, collected_by, "collected_by")

    # Priority 3: FK existence, left-to-right
    bush = db.sugarbushes.get(sugarbush_id)
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {sugarbush_id} not found")
    window = db.weather_windows.get(weather_window_id)
    if not window:
        raise_err(ERR_NOT_FOUND, f"weather window {weather_window_id} not found")
    crew = db.crew_members.get(collected_by)
    if not crew:
        raise_err(ERR_NOT_FOUND, f"crew member {collected_by} not found")

    # Priority 5: state gates
    season = db.seasons.get(bush["season_id"])
    if not season:
        raise_err(ERR_NOT_FOUND, f"season {bush['season_id']} not found")
    if season["status"] == "SUSPENDED":
        raise_err(ERR_SEASON_SUSPENDED, "season is SUSPENDED")
    if season["status"] != "OPEN":
        raise_err(ERR_SEASON_NOT_OPEN, f"season is {season['status']}, expected OPEN")
    if bush["status"] != "LIVE":
        raise_err(ERR_SUGARBUSH_NOT_LIVE,
                  f"sugarbush is {bush['status']}, expected LIVE")
    if window["status"] != "OPEN":
        raise_err(ERR_WINDOW_NOT_OPEN, f"window is {window['status']}, expected OPEN")
    if crew["status"] != "ACTIVE":
        raise_err(ERR_CREW_NOT_ACTIVE, f"crew member is {crew['status']}, expected ACTIVE")

    # Priority 7: collection strictly before closes_at
    now = core.clock_dt()
    if now >= parse_dt(window["closes_at"]):
        raise_err(ERR_COLLECTED_OUTSIDE_WINDOW,
                  "collection clock at/after window closes_at")

    run = core.new_sap_run(sugarbush_id, weather_window_id, collected_by,
                           gallons_collected, measured_brix)
    db.sap_runs[run["id"]] = run
    return success_object(core.ser_sap_run(run), status=201)


@bp.get("/sugarhouse/sap-runs/<rid>")
def get_run(rid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    run = get_run_or_404(rid)
    return success_object(core.ser_sap_run(run))


@bp.get("/sugarhouse/sap-runs")
def list_runs():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    sugarbush_id = request.args.get("sugarbush_id")
    weather_window_id = request.args.get("weather_window_id")
    collected_by = request.args.get("collected_by")
    status = request.args.get("status")
    rows = list(db.sap_runs.values())
    if sugarbush_id is not None:
        rows = [r for r in rows if r["sugarbush_id"] == sugarbush_id]
    if weather_window_id is not None:
        rows = [r for r in rows if r["weather_window_id"] == weather_window_id]
    if collected_by is not None:
        rows = [r for r in rows if r["collected_by"] == collected_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_sap_run(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/sap-runs/<rid>/confirm")
def confirm_run(rid):
    caller = authenticate()
    require_role(caller, COLLECTORS)
    run = get_run_or_404(rid)
    if run["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, f"sap run is {run['status']}, expected DRAFT")
    bush = db.sugarbushes.get(run["sugarbush_id"])
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {run['sugarbush_id']} not found")
    season = db.seasons.get(bush["season_id"])
    if not season:
        raise_err(ERR_NOT_FOUND, f"season {bush['season_id']} not found")
    if season["status"] == "SUSPENDED":
        raise_err(ERR_SEASON_SUSPENDED, "season is SUSPENDED")
    if season["status"] != "OPEN":
        raise_err(ERR_SEASON_NOT_OPEN, f"season is {season['status']}, expected OPEN")
    run["status"] = "CONFIRMED"
    core.bump(run)
    core.recompute_season_sap(season)
    return success_object(core.ser_sap_run(run))


@bp.post("/sugarhouse/sap-runs/<rid>/void")
def void_run(rid):
    caller = authenticate()
    require_role(caller, MGR)
    run = get_run_or_404(rid)
    if run["status"] == "VOIDED":
        raise_err(ERR_INVALID_STATE, "sap run is already VOIDED")
    if run["status"] == "CONFIRMED":
        if d(run["gallons_remaining"]) != d(run["gallons_collected"]):
            raise_err(ERR_RUN_HAS_DRAWS,
                      "confirmed run has been drawn into a batch")
    run["status"] = "VOIDED"
    core.bump(run)
    bush = db.sugarbushes.get(run["sugarbush_id"])
    if bush:
        season = db.seasons.get(bush["season_id"])
        if season:
            core.recompute_season_sap(season)
    return success_object(core.ser_sap_run(run))


# Intakes of a sap run (FK reverse lookup)
@bp.get("/sugarhouse/sap-runs/<rid>/intakes")
def list_run_intakes(rid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    run = get_run_or_404(rid)
    limit, offset = parse_pagination(request.args)
    rows = [i for i in db.batch_intakes.values() if i["sap_run_id"] == run["id"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_batch_intake(r) for r in page], limit, offset, total)
