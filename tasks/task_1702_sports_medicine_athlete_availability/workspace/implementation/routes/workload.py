"""Workload session ingestion."""
from flask import Blueprint, request

from db import STORE, new_id, now_stamp, clock_date
from errors import not_found, unprocessable, ERR_FUTURE_DATE_NOT_ALLOWED
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import workload_session_json, sorted_items
from services.derived import recompute_load_and_tier
from util import (body, present, require_enum, require_date, require_int,
                  require_str, parse_date_value)

bp = Blueprint("workload", __name__)

SESSION_TYPES = ["PRACTICE", "GAME", "CONDITIONING", "REHAB_SESSION"]
SURFACES = ["GRASS", "TURF", "COURT", "ICE", "TRAINING_ROOM"]
EXPOSURE_MIN_MINUTES = 10
EXPOSURE_TYPES = {"PRACTICE", "GAME", "CONDITIONING"}
READERS = ("PerformanceStaff", "MedicalStaff", "TeamAdmin")


@bp.route("/workload-sessions", methods=["POST"])
def create_workload_session():
    uid, _ = require_roles("PerformanceStaff")
    j = body()
    # existence (3)
    athlete = None
    if present(j, "athlete_id"):
        athlete = STORE["athletes"].get(j["athlete_id"])
        if athlete is None:
            raise not_found("Athlete not found: athlete_id")
    if athlete is None:
        require_str(j, "athlete_id")
    # field constraints (10)
    sraw, sdate = require_date(j, "session_date")
    session_type = require_enum(j, "session_type", SESSION_TYPES)
    surface = require_enum(j, "surface", SURFACES)
    duration = require_int(j, "duration_minutes", 0, 600)
    rpe = require_int(j, "rpe", 0, 10)
    # future-date (14)
    if sdate > clock_date():
        raise unprocessable(ERR_FUTURE_DATE_NOT_ALLOWED,
                            "session_date later than current date")
    session_load = duration * rpe
    counts = session_type in EXPOSURE_TYPES and duration >= EXPOSURE_MIN_MINUTES
    ts = now_stamp()
    session = {
        "id": new_id(), "athlete_id": athlete["id"], "team_id": athlete["team_id"],
        "session_date": sraw, "_session_date": sdate,
        "session_type": session_type, "surface": surface,
        "duration_minutes": duration, "rpe": rpe,
        "session_load": session_load, "counts_as_exposure": counts,
        "ingested_by_user_id": uid, "created_at": ts,
    }
    STORE["workload_sessions"][session["id"]] = session
    team = STORE["teams"].get(athlete["team_id"])
    recompute_load_and_tier(athlete, team)
    return ok_obj(workload_session_json(session), 201)


@bp.route("/workload-sessions", methods=["GET"])
def list_workload_sessions():
    require_roles(*READERS)
    items = sorted_items(STORE["workload_sessions"])
    athlete_id = request.args.get("athlete_id")
    team_id = request.args.get("team_id")
    session_type = request.args.get("session_type")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    if athlete_id is not None:
        items = [s for s in items if s["athlete_id"] == athlete_id]
    if team_id is not None:
        items = [s for s in items if s["team_id"] == team_id]
    if session_type is not None:
        items = [s for s in items if s["session_type"] == session_type]
    if from_date is not None:
        fd = parse_date_value(from_date)
        if fd is not None:
            items = [s for s in items if s["_session_date"] >= fd]
    if to_date is not None:
        td = parse_date_value(to_date)
        if td is not None:
            items = [s for s in items if s["_session_date"] <= td]
    return ok_list([workload_session_json(s) for s in items])


@bp.route("/workload-sessions/<sessionId>", methods=["GET"])
def get_workload_session(sessionId):
    require_roles(*READERS)
    s = STORE["workload_sessions"].get(sessionId)
    if s is None:
        raise not_found("WorkloadSession not found")
    return ok_obj(workload_session_json(s))
