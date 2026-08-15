"""Shearing crew, shearing event, and wool clip endpoints (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import clock
import db
import serial
import util
import validate as v
from errors import (ERR_CREW_BUSY, ERR_CREW_INACTIVE, ERR_CREW_OVERLAP,
                    ERR_INSUFFICIENT_HEAD, ERR_SHEARING_INVALID_STATE,
                    ERR_SHEARING_WINDOW_INFEASIBLE, ERR_VALIDATION, raise_err)
from middleware import require_roles
from response import success
from routes.flocks import check_flock_active

bp = Blueprint("shearing", __name__)

SHEARING_TARGETS = ("IN_PROGRESS", "CANCELLED")
_SHEARING_TRANSITIONS = {
    ("SCHEDULED", "IN_PROGRESS"),
    ("SCHEDULED", "CANCELLED"),
}
_BUFFER = timedelta(hours=24)


# ------------------------------------------------------------------ crews
@bp.post("/api/shearing-crews")
def create_crew():
    require_roles("RanchManager")
    b = v.body()
    name = v.req_str(b, "crew_name")
    capacity = v.req_int(b, "head_per_day_capacity", min=1)
    rate = v.req_int(b, "daily_rate_cents", min=0)
    if any(c["crew_name"] == name for c in db.STORE["crews"].values()):
        raise_err(ERR_VALIDATION, "crew_name must be unique")
    row = db.new_row()
    row.update({
        "crew_name": name,
        "crew_status": "ACTIVE",
        "head_per_day_capacity": capacity,
        "daily_rate_cents": rate,
    })
    db.STORE["crews"][row["id"]] = row
    return success(serial.crew_public(row), status=201)


@bp.get("/api/shearing-crews/<cid>")
def get_crew(cid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("crews", cid)
    return success(serial.crew_public(row))


@bp.post("/api/shearing-crews/<cid>/deactivate")
def deactivate_crew(cid):
    require_roles("RanchManager")
    row = db.get_or_404("crews", cid)
    if row["crew_status"] != "ACTIVE":
        raise_err(ERR_CREW_INACTIVE, "crew %s is already INACTIVE" % cid)
    if any(e["crew_id"] == cid and e["shearing_status"] in ("SCHEDULED", "IN_PROGRESS")
           for e in db.STORE["shearings"].values()):
        raise_err(ERR_CREW_BUSY, "crew still has scheduled or in-progress events")
    row["crew_status"] = "INACTIVE"
    db.touch(row)
    return success(serial.crew_public(row))


# ------------------------------------------------------------------ events
@bp.post("/api/shearing-events")
def create_shearing():
    require_roles("RanchManager")
    b = v.body()
    flock_id = v.req_str(b, "flock_id")
    crew_id = v.req_str(b, "crew_id")
    start = v.req_dt(b, "scheduled_start")
    end = v.req_dt(b, "scheduled_end")
    expected = v.req_int(b, "expected_head", min=1)
    if not start < end:
        raise_err(ERR_VALIDATION, "scheduled_start must be strictly before scheduled_end")
    flock = db.get_or_404("flocks", flock_id)
    crew = db.get_or_404("crews", crew_id)
    check_flock_active(flock)
    if crew["crew_status"] != "ACTIVE":
        raise_err(ERR_CREW_INACTIVE, "crew %s is INACTIVE" % crew_id)
    # sanitation-buffer overlap: adjacency forbidden; a full 24h gap is required
    for other in db.STORE["shearings"].values():
        if other["crew_id"] != crew_id or other["shearing_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if not (start >= other["scheduled_end"] + _BUFFER or end + _BUFFER <= other["scheduled_start"]):
            raise_err(ERR_CREW_OVERLAP, "booking collides with another crew booking under the 24h buffer rule")
    days = util.whole_days(start, end)
    if days * crew["head_per_day_capacity"] < expected:
        raise_err(ERR_SHEARING_WINDOW_INFEASIBLE, "window days * crew capacity is below expected_head")
    if expected > calc.flock_headcount(flock_id):
        raise_err(ERR_INSUFFICIENT_HEAD, "expected_head exceeds flock current_headcount")
    row = db.new_row()
    row.update({
        "flock_id": flock_id,
        "crew_id": crew_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "expected_head": expected,
        "shearing_status": "SCHEDULED",
        "shorn_head_count": None,
    })
    db.STORE["shearings"][row["id"]] = row
    return success(serial.shearing_public(row), status=201)


@bp.get("/api/shearing-events")
def list_shearings():
    require_roles("RanchManager", "RangeHand")
    limit, offset = v.pagination()
    rows = db.sorted_rows("shearings")
    for param, field in (("flock_id", "flock_id"), ("crew_id", "crew_id"),
                         ("shearing_status", "shearing_status")):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.shearing_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/shearing-events/<eid>")
def get_shearing(eid):
    require_roles("RanchManager", "RangeHand")
    row = db.get_or_404("shearings", eid)
    return success(serial.shearing_public(row))


@bp.post("/api/shearing-events/<eid>/transitions")
def shearing_transition(eid):
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    to = v.req_enum(b, "to", SHEARING_TARGETS)
    row = db.get_or_404("shearings", eid)
    cur = row["shearing_status"]
    if (cur, to) not in _SHEARING_TRANSITIONS:
        raise_err(ERR_SHEARING_INVALID_STATE,
                  "shearing transition %s -> %s is not allowed" % (cur, to))
    if to == "IN_PROGRESS" and clock.now() < row["scheduled_start"]:
        raise_err(ERR_SHEARING_INVALID_STATE, "scheduled_start has not been reached")
    row["shearing_status"] = to
    db.touch(row)
    return success(serial.shearing_public(row))


@bp.post("/api/shearing-events/<eid>/complete")
def complete_shearing(eid):
    require_roles("RanchManager", "RangeHand")
    b = v.body()
    shorn = v.req_int(b, "shorn_head_count", min=1)
    greasy = v.req_num(b, "greasy_weight_lbs", gt=0)
    skirtings = v.req_num(b, "skirtings_weight_lbs", gte=0)
    if not skirtings < greasy:
        raise_err(ERR_VALIDATION, "skirtings_weight_lbs must be strictly below greasy_weight_lbs")
    row = db.get_or_404("shearings", eid)
    if row["shearing_status"] != "IN_PROGRESS":
        raise_err(ERR_SHEARING_INVALID_STATE, "only an IN_PROGRESS shearing can be completed")
    row["shearing_status"] = "COMPLETED"
    row["shorn_head_count"] = shorn
    db.touch(row)
    # cascade: exactly one WoolClip per completed shearing (1:1)
    clip = db.new_row()
    clip.update({
        "shearing_event_id": row["id"],
        "flock_id": row["flock_id"],
        "greasy_weight_lbs": greasy,
        "skirtings_weight_lbs": skirtings,
    })
    db.STORE["clips"][clip["id"]] = clip
    return success(serial.shearing_public(row))


# ------------------------------------------------------------------ clips
@bp.get("/api/wool-clips")
def list_clips():
    require_roles("RanchManager", "RangeHand", "WoolPoolOperator")
    limit, offset = v.pagination()
    rows = db.sorted_rows("clips")
    for param in ("flock_id", "shearing_event_id"):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[param] == val]
    page, meta = v.paginate(rows, limit, offset)
    return success([serial.clip_public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/api/wool-clips/<cid>")
def get_clip(cid):
    require_roles("RanchManager", "RangeHand", "WoolPoolOperator")
    row = db.get_or_404("clips", cid)
    return success(serial.clip_public(row))
