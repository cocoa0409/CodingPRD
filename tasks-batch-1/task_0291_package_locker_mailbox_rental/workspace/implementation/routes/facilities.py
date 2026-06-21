"""Facility + clock endpoints."""
from flask import Blueprint, g

from db import db, new_id, now_iso
from errors import err
from response import success
from middleware import require_roles
from common import get_json, require_str, get_or_404, touch
import clock
import serializers as S
from services import sweep

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
def create_facility():
    require_roles("FacilityOperator")
    body = get_json()
    name = require_str(body, "name")
    time_zone = body.get("time_zone")
    if time_zone is not None and (not isinstance(time_zone, str) or time_zone == ""):
        raise err("ERR_INVALID_REQUEST", "time_zone must be a non-empty string")
    if time_zone is None:
        time_zone = "UTC"
    fid = new_id()
    facility = {
        "id": fid,
        "name": name,
        "time_zone": time_zone,
        "current_utc": "1970-01-01T00:00:00.000Z",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.facilities[fid] = facility
    return success(S.facility_out(facility), status=201)


@bp.get("/facilities/<fid>")
def get_facility(fid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    facility = get_or_404(db.facilities, fid)
    return success(S.facility_out(facility))


@bp.post("/facilities/<fid>/clock/advance")
def advance_clock(fid):
    require_roles("FacilityOperator")
    facility = get_or_404(db.facilities, fid)
    body = get_json()
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: to_iso8601")
    target = clock.parse_iso(to_iso)
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    current = clock.parse_iso(facility["current_utc"])
    if target < current:
        raise err("ERR_INVALID_CLOCK", "Clock cannot move backward")
    facility["current_utc"] = clock.to_iso_z(target)
    touch(facility)
    sweep.run_sweep(facility)
    return success(S.facility_out(facility))
