"""Facility endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, clock_now_dt, parse_iso8601,
)
from errors import raise_err, ERR_INVALID_REQUEST

bp = Blueprint("facilities", __name__)


def _upcoming_booked_hours(facility_id):
    now = clock_now_dt()
    total_seconds = 0
    for b in db.facility_bookings.values():
        if b.get("facility_id") != facility_id:
            continue
        if b.get("status") != "CONFIRMED":
            continue
        try:
            ends = parse_iso8601(b["ends_at"])
            starts = parse_iso8601(b["starts_at"])
        except Exception:
            continue
        if ends <= now:
            continue
        total_seconds += (ends - starts).total_seconds()
    return total_seconds / 3600.0


@bp.route("/facilities", methods=["POST"])
def create_facility():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()
    for k in ("name", "capacity"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["name"], str) or body["name"] == "":
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if not isinstance(body["capacity"], int) or isinstance(body["capacity"], bool):
        raise_err(ERR_INVALID_REQUEST, "capacity must be an integer")
    if body["capacity"] <= 0:
        raise_err(ERR_INVALID_REQUEST, "capacity must be > 0")
    buffer_minutes = body.get("buffer_minutes", 0)
    if buffer_minutes is None:
        buffer_minutes = 0
    if not isinstance(buffer_minutes, int) or isinstance(buffer_minutes, bool):
        raise_err(ERR_INVALID_REQUEST, "buffer_minutes must be an integer")
    if buffer_minutes < 0:
        raise_err(ERR_INVALID_REQUEST, "buffer_minutes must be >= 0")

    rec = {
        "name": body["name"],
        "capacity": body["capacity"],
        "buffer_minutes": buffer_minutes,
        "status": "AVAILABLE",
        "upcoming_booked_hours": 0.0,
    }
    stamp_common_create(rec)
    db.facilities[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    require_role({"Coordinator", "FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.facilities, fid, "Facility")
    # Recompute upcoming_booked_hours on read for accuracy.
    out = dict(rec)
    out["upcoming_booked_hours"] = _upcoming_booked_hours(fid)
    return success(out, 200)
