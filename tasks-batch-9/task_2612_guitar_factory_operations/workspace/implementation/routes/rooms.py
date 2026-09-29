"""Storage rooms, climate readings and certification (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import auth
import domain
import store
import validate as v
from constants import CLIMATE_STATUSES, ROOM_TYPES
from envelope import object_response, paginate
from errors import ApiError
from serialize import room_view
from store import ROOMS, new_record, touch

bp = Blueprint("rooms", __name__)


@bp.post("/storage-rooms")
def create_room():
    auth.require(auth.PLANT_ADMIN)
    body = v.body()
    room_code = v.get_str(body, "room_code", min_len=1, max_len=32)
    room_type = v.get_enum(body, "room_type", ROOM_TYPES)
    target_rh = v.get_dec(body, "target_rh_pct", minimum=20.0, maximum=80.0)
    target_temp = v.get_dec(body, "target_temp_c", minimum=10.0, maximum=35.0)
    capacity = v.get_int(body, "capacity_slots", minimum=1)
    tolerance = v.get_dec(body, "rh_tolerance_pct", required=False,
                          minimum=0.5, maximum=15.0, default=Decimal("3.0"))
    v.unique_code(ROOMS, "room_code", room_code)
    rec = new_record(ROOMS, {
        "room_code": room_code,
        "room_type": room_type,
        "target_rh_pct": target_rh,
        "rh_tolerance_pct": tolerance,
        "target_temp_c": target_temp,
        "capacity_slots": capacity,
        "latest_rh_pct": target_rh,
        "latest_temp_c": target_temp,
        "last_reading_at": None,
        "climate_status": "IN_SPEC",
        "out_of_spec_since": None,
    })
    return object_response(room_view(rec), 201)


@bp.get("/storage-rooms/<room_id>")
def read_room(room_id):
    auth.require_staff()
    rec = v.fetch(ROOMS, room_id, "ERR_STORAGE_ROOM_NOT_FOUND")
    return object_response(room_view(rec))


@bp.get("/storage-rooms")
def list_rooms():
    auth.require_staff()
    rows = v.apply_filters(list(ROOMS.values()), [
        ("room_type", v.filter_enum("room_type", ROOM_TYPES)),
        ("climate_status", v.filter_enum("climate_status", CLIMATE_STATUSES)),
    ])
    rows.sort(key=lambda r: r["room_code"])
    return paginate(rows, room_view)


@bp.post("/storage-rooms/<room_id>/climate-readings")
def climate_reading(room_id):
    auth.require(auth.PLANT_ADMIN, auth.FINISH_TECH)
    body = v.body()
    rh = v.get_dec(body, "rh_pct")
    temp = v.get_dec(body, "temp_c")
    rec = v.fetch(ROOMS, room_id, "ERR_STORAGE_ROOM_NOT_FOUND")
    domain.record_climate_reading(rec, rh, temp)
    return object_response(room_view(rec))


@bp.post("/storage-rooms/<room_id>/certify")
def certify_room(room_id):
    auth.require(auth.PLANT_ADMIN, auth.QUALITY_INSPECTOR)
    rec = v.fetch(ROOMS, room_id, "ERR_STORAGE_ROOM_NOT_FOUND")
    if rec["climate_status"] != "QUARANTINED":
        raise ApiError("ERR_ROOM_STATE_INVALID",
                       "only a QUARANTINED room may be certified")
    if not domain.climate_in_band(rec, rec["latest_rh_pct"]):
        raise ApiError("ERR_ROOM_CLIMATE_OUT_OF_SPEC",
                       "latest humidity is still outside tolerance")
    rec["climate_status"] = "IN_SPEC"
    rec["out_of_spec_since"] = None
    touch(rec)
    return object_response(room_view(rec))
