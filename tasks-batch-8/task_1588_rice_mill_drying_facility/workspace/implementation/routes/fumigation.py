"""FumigationEvent endpoints (PRD §3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_BIN_NOT_FOUND, ERR_BIN_FUMIGATION_ACTIVE,
    ERR_FUMIGATION_WINDOW_CONFLICT, ERR_FUMIGATION_INVALID_STATE,
    ERR_EXPOSURE_INCOMPLETE, ERR_AERATION_INCOMPLETE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq, parse_dt, fmt_dt, add_hours
from validate import get_body, req_str, req_int, req_datetime

bp = Blueprint("fumigation", __name__)


@bp.route("/mill/fumigation-events", methods=["POST"])
def create_fumigation():
    authorized(["FumigationTech"])
    body = get_body()
    season_id = req_str(body, "season_id")
    bin_id = req_str(body, "bin_id")
    fumigant_code = req_str(body, "fumigant_code")
    applicator_license = req_str(body, "applicator_license")
    started_at_raw = req_datetime(body, "started_at")
    exposure_hours = req_int(body, "exposure_hours", non_negative=True)
    aeration_hours = req_int(body, "aeration_hours", non_negative=True)
    season = require_resource("seasons", season_id)
    started = parse_dt(started_at_raw)
    # started_at must be at or before the season logical clock (back-dating allowed).
    if started > core.season_clock_dt(season):
        raise_error(ERR_INVALID_REQUEST,
                    "started_at is in the future relative to the season clock")
    b = db["bins"].get(bin_id)
    if b is None or b["season_id"] != season_id:
        raise_error(ERR_BIN_NOT_FOUND, "bin not found in this season")
    # state: bin must be AVAILABLE
    if b["status"] != "AVAILABLE":
        raise_error(ERR_BIN_FUMIGATION_ACTIVE,
                    f"bin status {b['status']} already under fumigation handling")
    exposure_ends = add_hours(started, exposure_hours)
    clearance = add_hours(exposure_ends, aeration_hours)
    # half-open window [started_at, clearance_at) vs all events on the bin, history included
    for other in db["fumigation_events"].values():
        if other["season_id"] == season_id and other["bin_id"] == bin_id:
            o_start = parse_dt(other["started_at"])
            o_clear = parse_dt(other["clearance_at"])
            if started < o_clear and o_start < clearance:
                raise_error(ERR_FUMIGATION_WINDOW_CONFLICT,
                            "treatment window overlaps another event on this bin")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "bin_id": bin_id,
        "fumigant_code": fumigant_code,
        "applicator_license": applicator_license,
        "started_at": fmt_dt(started),
        "exposure_hours": exposure_hours,
        "aeration_hours": aeration_hours,
        "exposure_ends_at": fmt_dt(exposure_ends),
        "clearance_at": fmt_dt(clearance),
        "status": "ACTIVE",
    }
    core.touch_new(rec)
    db["fumigation_events"][rec["id"]] = rec
    # Cascade: bin -> FUMIGATING; PLANNED drying runs targeting the bin auto-cancel.
    b["status"] = "FUMIGATING"
    core.bump(b)
    for run in list(db["drying_runs"].values()):
        if (run["season_id"] == season_id and run["destination_bin_id"] == bin_id
                and run["status"] == "PLANNED"):
            core.cancel_drying_run(run)
    return success_object(public(rec), 201)


@bp.route("/mill/fumigation-events", methods=["GET"])
def list_fumigations():
    return list_endpoint("fumigation_events", ["season_id", "bin_id", "status"])


@bp.route("/mill/fumigation-events/<rid>", methods=["GET"])
def get_fumigation(rid):
    return get_endpoint("fumigation_events", rid)


@bp.route("/mill/fumigation-events/<rid>/begin-aeration", methods=["POST"])
def begin_aeration(rid):
    authorized(["FumigationTech"])
    ev = require_resource("fumigation_events", rid)
    if ev["status"] != "ACTIVE":
        raise_error(ERR_FUMIGATION_INVALID_STATE,
                    f"begin-aeration requires ACTIVE; event is {ev['status']}")
    season = db["seasons"][ev["season_id"]]
    if core.season_clock_dt(season) < parse_dt(ev["exposure_ends_at"]):
        raise_error(ERR_EXPOSURE_INCOMPLETE,
                    "the season clock has not reached exposure_ends_at")
    ev["status"] = "AERATING"
    core.bump(ev)
    b = db["bins"].get(ev["bin_id"])
    if b is not None and b["status"] == "FUMIGATING":
        b["status"] = "AERATING"
        core.bump(b)
    return success_object(public(ev))


@bp.route("/mill/fumigation-events/<rid>/clear", methods=["POST"])
def clear_fumigation(rid):
    authorized(["FumigationTech"])
    ev = require_resource("fumigation_events", rid)
    if ev["status"] != "AERATING":
        raise_error(ERR_FUMIGATION_INVALID_STATE,
                    f"clear requires AERATING; event is {ev['status']}")
    season = db["seasons"][ev["season_id"]]
    if core.season_clock_dt(season) < parse_dt(ev["clearance_at"]):
        raise_error(ERR_AERATION_INCOMPLETE,
                    "the season clock has not reached clearance_at")
    ev["status"] = "CLEARED"
    core.bump(ev)
    b = db["bins"].get(ev["bin_id"])
    if b is not None and b["status"] == "AERATING":
        b["status"] = "AVAILABLE"
        core.bump(b)
    return success_object(public(ev))
