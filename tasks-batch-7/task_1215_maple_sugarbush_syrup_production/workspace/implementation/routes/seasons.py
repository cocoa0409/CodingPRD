"""Season endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  parse_date, clock_date, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_OUTSIDE_PRODUCTION_WINDOW, ERR_SEASON_ALREADY_ACTIVE,
                    ERR_SEASON_HAS_OPEN_BATCHES, ERR_RECONCILE_BLOCKED)
from services import core

bp = Blueprint("seasons", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}


def get_season_or_404(sid):
    s = db.seasons.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, f"season {sid} not found")
    return s


@bp.post("/sugarhouse/seasons")
def create_season():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    check_unknown_fields(data, {"year", "opens_on", "closes_on", "planned_taps"})
    require_fields(data, ["year", "opens_on", "closes_on", "planned_taps"])
    year = as_int(data["year"], "year")
    planned_taps = as_int(data["planned_taps"], "planned_taps", minimum=1)
    opens_on = as_str(data["opens_on"], "opens_on")
    closes_on = as_str(data["closes_on"], "closes_on")
    try:
        od = parse_date(opens_on)
        cd = parse_date(closes_on)
    except Exception:
        raise_err(ERR_VALIDATION, "opens_on/closes_on must be YYYY-MM-DD dates")
    if cd < od:
        raise_err(ERR_VALIDATION, "closes_on must be on or after opens_on")
    s = core.new_season(year, opens_on, closes_on, planned_taps)
    db.seasons[s["id"]] = s
    return success_object(core.ser_season(s), status=201)


@bp.get("/sugarhouse/seasons/<sid>")
def get_season(sid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    s = get_season_or_404(sid)
    return success_object(core.ser_season(s))


@bp.post("/sugarhouse/seasons/<sid>/open")
def open_season(sid):
    caller = authenticate()
    require_role(caller, MGR)
    s = get_season_or_404(sid)
    if s["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, f"season is {s['status']}, expected PLANNED")
    # Structural precondition from state machine table: no other OPEN/SUSPENDED season.
    # Priority 8 (structural) fires before priority 7 (temporal) when both apply is
    # NOT how the table reads: priority 7 < 8, so temporal wins. Check temporal first.
    today = clock_date()
    od = parse_date(s["opens_on"])
    cd = parse_date(s["closes_on"])
    if not (od <= today <= cd):
        raise_err(ERR_OUTSIDE_PRODUCTION_WINDOW,
                  "logical clock date outside season opens_on..closes_on")
    for other in db.seasons.values():
        if other["id"] != s["id"] and other["status"] in ("OPEN", "SUSPENDED"):
            raise_err(ERR_SEASON_ALREADY_ACTIVE, "another season is OPEN or SUSPENDED")
    s["status"] = "OPEN"
    core.bump(s)
    return success_object(core.ser_season(s))


@bp.post("/sugarhouse/seasons/<sid>/suspend")
def suspend_season(sid):
    caller = authenticate()
    require_role(caller, MGR)
    s = get_season_or_404(sid)
    if s["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"season is {s['status']}, expected OPEN")
    s["status"] = "SUSPENDED"
    core.bump(s)
    return success_object(core.ser_season(s))


@bp.post("/sugarhouse/seasons/<sid>/resume")
def resume_season(sid):
    caller = authenticate()
    require_role(caller, MGR)
    s = get_season_or_404(sid)
    if s["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, f"season is {s['status']}, expected SUSPENDED")
    today = clock_date()
    od = parse_date(s["opens_on"])
    cd = parse_date(s["closes_on"])
    if not (od <= today <= cd):
        raise_err(ERR_OUTSIDE_PRODUCTION_WINDOW,
                  "logical clock date outside season opens_on..closes_on")
    s["status"] = "OPEN"
    core.bump(s)
    return success_object(core.ser_season(s))


@bp.post("/sugarhouse/seasons/<sid>/close")
def close_season(sid):
    caller = authenticate()
    require_role(caller, MGR)
    s = get_season_or_404(sid)
    if s["status"] not in ("OPEN", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, f"season is {s['status']}, expected OPEN or SUSPENDED")
    for bt in db.batches.values():
        if bt["season_id"] == s["id"] and bt["status"] in ("FILLING", "BOILING"):
            raise_err(ERR_SEASON_HAS_OPEN_BATCHES,
                      "season has batches in FILLING or BOILING")
    # Cascades
    for cm in db.crew_members.values():
        if cm["season_id"] == s["id"] and cm["status"] == "ACTIVE":
            cm["status"] = "RELEASED"
            core.bump(cm)
    for w in db.weather_windows.values():
        if w["season_id"] == s["id"] and w["status"] in ("FORECAST", "OPEN"):
            w["status"] = "CLOSED"
            core.bump(w)
    for r in db.sap_runs.values():
        b = db.sugarbushes.get(r["sugarbush_id"])
        if b and b["season_id"] == s["id"] and r["status"] == "DRAFT":
            r["status"] = "VOIDED"
            core.bump(r)
    s["status"] = "CLOSED"
    core.bump(s)
    return success_object(core.ser_season(s))


@bp.post("/sugarhouse/seasons/<sid>/reconcile")
def reconcile_season(sid):
    caller = authenticate()
    require_role(caller, MGR)
    s = get_season_or_404(sid)
    if s["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, f"season is {s['status']}, expected CLOSED")
    for lot in db.syrup_lots.values():
        if lot["season_id"] == s["id"] and lot["status"] in ("UNGRADED", "HELD"):
            raise_err(ERR_RECONCILE_BLOCKED,
                      "season has syrup lots in UNGRADED or HELD")
    for pr in db.packaging_runs.values():
        lot = db.syrup_lots.get(pr["syrup_lot_id"])
        if lot and lot["season_id"] == s["id"] and pr["status"] == "PLANNED":
            raise_err(ERR_RECONCILE_BLOCKED,
                      "season has packaging runs in PLANNED")
    core.settle_final_royalty(s)
    s["status"] = "RECONCILED"
    core.bump(s)
    return success_object(core.ser_season(s))


@bp.post("/sugarhouse/seasons/<sid>/run-sweep")
def run_sweep(sid):
    caller = authenticate()
    require_role(caller, MGR)
    s = get_season_or_404(sid)
    now = core.clock_dt()
    today = clock_date()
    # Close expired windows (OPEN or FORECAST) whose closes_at <= clock
    for w in db.weather_windows.values():
        if w["season_id"] == s["id"] and w["status"] in ("FORECAST", "OPEN"):
            if core.parse_dt(w["closes_at"]) <= now:
                w["status"] = "CLOSED"
                core.bump(w)
    # Expire ACTIVE leases whose term_end < clock date
    for lease in db.leases.values():
        bush = db.sugarbushes.get(lease["sugarbush_id"])
        if not bush or bush["season_id"] != s["id"]:
            continue
        if lease["status"] != "ACTIVE":
            continue
        if parse_date(lease["term_end"]) < today:
            lease["status"] = "EXPIRED"
            core.bump(lease)
            if bush["status"] in ("TAPPING", "LIVE"):
                core.shutdown_bush_cascade(bush, bump_bush=True)
    core.bump(s)
    return success_object(core.ser_season(s))
