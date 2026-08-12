"""TapLine and VacuumReading endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  as_number, d, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_TAP_CAPACITY_EXCEEDED, ERR_VACUUM_STILL_LOW)
from services import core

bp = Blueprint("tap_lines", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}


def get_line_or_404(lid):
    l = db.tap_lines.get(lid)
    if not l:
        raise_err(ERR_NOT_FOUND, f"tap line {lid} not found")
    return l


@bp.post("/sugarhouse/tap-lines")
def create_line():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    check_unknown_fields(data, {"sugarbush_id", "line_code", "tap_count", "vacuum_target_inhg"})
    require_fields(data, ["sugarbush_id", "line_code", "tap_count", "vacuum_target_inhg"])
    sugarbush_id = as_str(data["sugarbush_id"], "sugarbush_id")
    line_code = as_str(data["line_code"], "line_code")
    tap_count = as_int(data["tap_count"], "tap_count", minimum=1)
    vacuum_target_inhg = as_number(data["vacuum_target_inhg"], "vacuum_target_inhg",
                                   minimum=0, exclusive_min=True)

    bush = db.sugarbushes.get(sugarbush_id)
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {sugarbush_id} not found")
    if bush["status"] != "TAPPING":
        raise_err(ERR_INVALID_STATE,
                  f"sugarbush is {bush['status']}, expected TAPPING")
    existing = sum(l["tap_count"] for l in core.lines_of_bush(bush["id"])
                   if l["status"] != "PULLED")
    if existing + tap_count > bush["tap_capacity"]:
        raise_err(ERR_TAP_CAPACITY_EXCEEDED,
                  f"tap capacity {bush['tap_capacity']} would be exceeded")

    line = core.new_tap_line(sugarbush_id, line_code, tap_count, vacuum_target_inhg)
    db.tap_lines[line["id"]] = line
    core.recompute_bush_taps(bush)
    season = db.seasons.get(bush["season_id"])
    if season:
        core.recompute_season_taps_live(season)
    return success_object(core.ser_tap_line(line), status=201)


@bp.get("/sugarhouse/tap-lines/<lid>")
def get_line(lid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    line = get_line_or_404(lid)
    return success_object(core.ser_tap_line(line))


@bp.get("/sugarhouse/tap-lines")
def list_lines():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    sugarbush_id = request.args.get("sugarbush_id")
    status = request.args.get("status")
    rows = list(db.tap_lines.values())
    if sugarbush_id is not None:
        rows = [r for r in rows if r["sugarbush_id"] == sugarbush_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_tap_line(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/tap-lines/<lid>/activate")
def activate_line(lid):
    caller = authenticate()
    require_role(caller, MGR)
    line = get_line_or_404(lid)
    if line["status"] != "INSTALLING":
        raise_err(ERR_INVALID_STATE, f"tap line is {line['status']}, expected INSTALLING")
    bush = db.sugarbushes.get(line["sugarbush_id"])
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {line['sugarbush_id']} not found")
    if bush["status"] not in ("TAPPING", "LIVE"):
        raise_err(ERR_INVALID_STATE,
                  f"sugarbush is {bush['status']}, expected TAPPING or LIVE")
    line["status"] = "ACTIVE"
    core.bump(line)
    core.recompute_bush_taps(bush)
    season = db.seasons.get(bush["season_id"])
    if season:
        core.recompute_season_taps_live(season)
    return success_object(core.ser_tap_line(line))


@bp.post("/sugarhouse/tap-lines/<lid>/repair")
def repair_line(lid):
    caller = authenticate()
    require_role(caller, MGR)
    line = get_line_or_404(lid)
    if line["status"] != "LEAK":
        raise_err(ERR_INVALID_STATE, f"tap line is {line['status']}, expected LEAK")
    bush = db.sugarbushes.get(line["sugarbush_id"])
    if not bush:
        raise_err(ERR_NOT_FOUND, f"sugarbush {line['sugarbush_id']} not found")
    if bush["status"] not in ("TAPPING", "LIVE"):
        raise_err(ERR_INVALID_STATE,
                  f"sugarbush is {bush['status']}, expected TAPPING or LIVE")
    # latest reading by recorded_at, tie-break created_at
    readings = [r for r in db.vacuum_readings.values() if r["tap_line_id"] == line["id"]]
    if readings:
        readings.sort(key=lambda r: (r["recorded_at"], r["created_at"]))
        latest = readings[-1]
        if latest["inhg"] < line["vacuum_target_inhg"] - core.REPAIR_HYSTERESIS:
            raise_err(ERR_VACUUM_STILL_LOW,
                      "latest reading below vacuum_target_inhg - 0.5")
    else:
        raise_err(ERR_VACUUM_STILL_LOW, "no vacuum readings on this line")
    line["status"] = "ACTIVE"
    core.bump(line)
    core.recompute_bush_taps(bush)
    season = db.seasons.get(bush["season_id"])
    if season:
        core.recompute_season_taps_live(season)
    return success_object(core.ser_tap_line(line))


@bp.post("/sugarhouse/tap-lines/<lid>/pull")
def pull_line_endpoint(lid):
    caller = authenticate()
    require_role(caller, MGR)
    line = get_line_or_404(lid)
    if line["status"] not in ("INSTALLING", "ACTIVE", "LEAK"):
        raise_err(ERR_INVALID_STATE,
                  f"tap line is {line['status']}, expected INSTALLING/ACTIVE/LEAK")
    core.pull_line(line)
    return success_object(core.ser_tap_line(line))


# ---------------- Vacuum readings (sub-resource) ----------------

@bp.post("/sugarhouse/tap-lines/<lid>/vacuum-readings")
def record_reading(lid):
    caller = authenticate()
    require_role(caller, {"SugarhouseManager", "FieldCrew"})
    line = get_line_or_404(lid)
    data = body_json()
    check_unknown_fields(data, {"inhg"})
    require_fields(data, ["inhg"])
    inhg = as_number(data["inhg"], "inhg", minimum=0)

    reading = core.new_vacuum_reading(line["id"], inhg)
    db.vacuum_readings[reading["id"]] = reading

    # update latest_vacuum_inhg: latest by recorded_at, tie-break created_at.
    # Since recorded_at == created_at == now for a fresh insert, the newest record wins.
    line["latest_vacuum_inhg"] = reading["inhg"]
    core.touch(line)

    # Leak trigger: only from ACTIVE, strictly below target - 2.0
    if line["status"] == "ACTIVE":
        threshold = line["vacuum_target_inhg"] - core.LEAK_DROP
        if reading["inhg"] < threshold:
            line["status"] = "LEAK"
            core.bump(line)
            bush = db.sugarbushes.get(line["sugarbush_id"])
            if bush:
                core.recompute_bush_taps(bush)
                core.maybe_auto_regress_bush(bush)
                season = db.seasons.get(bush["season_id"])
                if season:
                    core.recompute_season_taps_live(season)

    return success_object(core.ser_vacuum_reading(reading), status=201)


@bp.get("/sugarhouse/tap-lines/<lid>/vacuum-readings")
def list_readings(lid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    line = get_line_or_404(lid)
    limit, offset = parse_pagination(request.args)
    rows = [r for r in db.vacuum_readings.values() if r["tap_line_id"] == line["id"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_vacuum_reading(r) for r in page], limit, offset, total)
