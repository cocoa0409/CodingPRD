"""Breeding season and birth record endpoints (PRD 3.1)."""
from datetime import timedelta

from flask import Blueprint, g, request

import calc
import clock
import db
import serial
import validate as v
from errors import (ERR_BIRTH_COUNT_MISMATCH, ERR_BIRTH_OUTSIDE_WINDOW,
                    ERR_FLOCK_RETIRED, ERR_OPEN_SEASON_EXISTS,
                    ERR_SEASON_INVALID_STATE, ERR_SEASON_TOO_EARLY,
                    ERR_VALIDATION, raise_err)
from middleware import require_roles
from response import success
from routes.flocks import check_flock_active

bp = Blueprint("breeding", __name__)

SEASON_TARGETS = ("BREEDING", "GESTATION", "LAMBING", "WEANING", "CLOSED", "CANCELLED")
_OPEN_SEASON = {"PLANNED", "BREEDING", "GESTATION", "LAMBING", "WEANING"}

_SEASON_TRANSITIONS = {
    ("PLANNED", "BREEDING"),
    ("BREEDING", "GESTATION"),
    ("GESTATION", "LAMBING"),
    ("LAMBING", "WEANING"),
    ("WEANING", "CLOSED"),
    ("PLANNED", "CANCELLED"),
    ("BREEDING", "CANCELLED"),
}


@bp.post("/api/breeding-seasons")
def create_season():
    require_roles("RanchManager")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    label = v.req_str(b, "season_label")
    ewes = v.req_int(b, "ewes_bred", min=1)
    start = v.req_dt(b, "breeding_start_date")
    end = v.req_dt(b, "breeding_end_date")
    if not start < end:
        raise_err(ERR_VALIDATION, "breeding_start_date must be strictly before breeding_end_date")
    flock = db.get_or_404("flocks", flock_id)
    if any(s["flock_id"] == flock_id and s["season_label"] == label
           for s in db.STORE["seasons"].values()):
        raise_err(ERR_VALIDATION, "season_label must be unique within the flock")
    check_flock_active(flock)
    if any(s["flock_id"] == flock_id and s["season_status"] in _OPEN_SEASON
           for s in db.STORE["seasons"].values()):
        raise_err(ERR_OPEN_SEASON_EXISTS, "flock already has an open breeding season")
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "season_label": label,
        "ewes_bred": ewes,
        "breeding_start_date": start,
        "breeding_end_date": end,
        "expected_lambing_start": start + timedelta(days=calc.GESTATION_DAYS[flock["species"]]),
        "season_status": "PLANNED",
    })
    db.STORE["seasons"][row["id"]] = row
    return success(serial.season_public(row), status=201)


@bp.get("/api/breeding-seasons")
def list_seasons():
    require_roles("RanchManager", "RangeHand")
    limit, offset = v.pagination()
    rows = db.sorted_rows("seasons")
    flock_id = request.args.get("flock_id")
    if flock_id is not None:
        rows = [r for r in rows if r["flock_id"] == flock_id]
    status = request.args.get("season_status")
    if status is not None:
        rows = [r for r in rows if r["season_status"] == status]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.season_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/breeding-seasons/<sid>")
def get_season(sid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("seasons", sid)
    return success(serial.season_public(row))


@bp.post("/api/breeding-seasons/<sid>/transitions")
def season_transition(sid):
    require_roles("RanchManager")
    b = v.body()
    to = v.req_enum(b, "to", SEASON_TARGETS)
    row = db.get_or_404("seasons", sid)
    cur = row["season_status"]
    if (cur, to) not in _SEASON_TRANSITIONS:
        raise_err(ERR_SEASON_INVALID_STATE,
                  "season transition %s -> %s is not allowed" % (cur, to))
    now = clock.now()
    if (cur, to) == ("PLANNED", "BREEDING"):
        flock = db.STORE["flocks"][row["flock_id"]]
        if flock["flock_status"] != "ACTIVE":
            raise_err(ERR_FLOCK_RETIRED, "flock %s is RETIRED" % flock["id"])
    elif (cur, to) == ("BREEDING", "GESTATION"):
        if now < row["breeding_end_date"]:
            raise_err(ERR_SEASON_TOO_EARLY, "breeding_end_date has not been reached")
    elif (cur, to) == ("GESTATION", "LAMBING"):
        if now < row["expected_lambing_start"]:
            raise_err(ERR_SEASON_TOO_EARLY, "expected_lambing_start has not been reached")
    elif (cur, to) == ("LAMBING", "WEANING"):
        if now < calc.lambing_window_end(row):
            raise_err(ERR_SEASON_TOO_EARLY, "weaning date has not been reached")
    row["season_status"] = to
    db.touch(row)
    return success(serial.season_public(row))


@bp.post("/api/birth-records")
def create_birth():
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    season_id = v.req_str(b, "season_id")
    birth_date = v.req_dt(b, "birth_date")
    reported = v.req_int(b, "births_reported", min=1)
    alive = v.req_int(b, "born_alive", min=0)
    dead = v.req_int(b, "born_dead", min=0)
    season = db.get_or_404("seasons", season_id)
    flock = db.STORE["flocks"][season["flock_id"]]
    check_flock_active(flock)
    if season["season_status"] != "LAMBING":
        raise_err(ERR_SEASON_INVALID_STATE, "births may only be logged while the season is LAMBING")
    if not (season["expected_lambing_start"] <= birth_date <= calc.lambing_window_end(season)):
        raise_err(ERR_BIRTH_OUTSIDE_WINDOW, "birth_date is outside the lambing window")
    if reported != alive + dead:
        raise_err(ERR_BIRTH_COUNT_MISMATCH, "births_reported must equal born_alive + born_dead")
    row = db.new_birth_row()
    row.update({
        "season_id": season_id,
        "birth_date": birth_date,
        "births_reported": reported,
        "born_alive": alive,
        "born_dead": dead,
        "recorded_by_user_id": g.user_id,
    })
    db.STORE["births"][row["id"]] = row
    return success(serial.birth_public(row), status=201)


@bp.get("/api/birth-records")
def list_births():
    require_roles("RanchManager", "RangeHand")
    limit, offset = v.pagination()
    rows = db.sorted_rows("births")
    season_id = request.args.get("season_id")
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.birth_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/birth-records/<bid>")
def get_birth(bid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("births", bid)
    return success(serial.birth_public(row))
