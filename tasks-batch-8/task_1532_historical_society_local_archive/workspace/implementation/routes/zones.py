"""StorageZone routes (PRD §2.6)."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import raise_err, ERR_NOT_FOUND, ERR_ZONE_CODE_EXISTS
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.zone import compute_breach, apply_posture
from util import (
    get_json_body, as_str, as_number, parse_iso8601, paginate, public_view,
    require_field,
)

bp = Blueprint("zones", __name__)

DEFAULT_TEMP_HIGH = Decimal("24.0")
DEFAULT_TEMP_LOW = Decimal("14.0")
DEFAULT_HUMIDITY_HIGH = Decimal("60.0")
DEFAULT_HUMIDITY_LOW = Decimal("30.0")


def _serialize_reading(r: dict) -> dict:
    return {
        "reading_id": r["reading_id"],
        "recorded_at": r["recorded_at"],
        "temperature_c": r["temperature_c"],
        "humidity_pct": r["humidity_pct"],
        "is_breach": r["is_breach"],
        "is_severe": r["is_severe"],
    }


def serialize_zone(zone: dict) -> dict:
    view = public_view(zone)
    view["recent_readings"] = [
        _serialize_reading(r)
        for r in sorted(
            zone["recent_readings"],
            key=lambda r: (r["_recorded_dt"], r["_created_at"], r["_seq"]),
        )
    ]
    return view


def _get_zone(zone_id: str) -> dict:
    zone = db.zones.get(zone_id)
    if zone is None:
        raise_err(ERR_NOT_FOUND, f"StorageZone not found: {zone_id}")
    return zone


@bp.route("/storage-zones", methods=["POST"])
@require_roles("Registrar", "SystemAdmin")
def create_zone(_user_id: str, _role: str):
    body = get_json_body()
    zone_code = as_str(body, "zone_code", required=True)
    name = as_str(body, "name", required=True)
    temp_high = as_number(body, "temp_high_c", required=False, default=DEFAULT_TEMP_HIGH)
    temp_low = as_number(body, "temp_low_c", required=False, default=DEFAULT_TEMP_LOW)
    hum_high = as_number(body, "humidity_high_pct", required=False, default=DEFAULT_HUMIDITY_HIGH)
    hum_low = as_number(body, "humidity_low_pct", required=False, default=DEFAULT_HUMIDITY_LOW)

    if any(z["zone_code"] == zone_code for z in db.zones.values()):
        raise_err(ERR_ZONE_CODE_EXISTS, f"zone_code already in use: {zone_code}")

    zone = {
        **db.make_common_fields(),
        "zone_code": zone_code,
        "name": name,
        "temp_high_c": temp_high,
        "temp_low_c": temp_low,
        "humidity_high_pct": hum_high,
        "humidity_low_pct": hum_low,
        "posture": "OPEN",
        "breach_streak": 0,
        "recent_readings": [],
    }
    db.zones[zone["id"]] = zone
    return success_object(serialize_zone(zone), 201)


@bp.route("/storage-zones", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_zones(_user_id: str, _role: str):
    posture = request.args.get("posture")
    items = list(db.zones.values())
    if posture is not None:
        items = [z for z in items if z["posture"] == posture]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_zone(z) for z in page], limit, offset, total)


@bp.route("/storage-zones/<zone_id>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_zone(zone_id: str, _user_id: str, _role: str):
    return success_object(serialize_zone(_get_zone(zone_id)))


@bp.route("/storage-zones/<zone_id>/readings", methods=["POST"])
@require_roles("SystemAdmin", "Archivist")
def post_reading(zone_id: str, _user_id: str, _role: str):
    body = get_json_body()
    recorded_at_raw = require_field(body, "recorded_at")
    recorded_dt = parse_iso8601(recorded_at_raw, "recorded_at")
    temperature_c = as_number(body, "temperature_c", required=True)
    humidity_pct = as_number(body, "humidity_pct", required=True)

    zone = _get_zone(zone_id)

    is_breach, is_severe = compute_breach(zone, temperature_c, humidity_pct)
    reading = {
        "reading_id": db.new_id(),
        "recorded_at": recorded_at_raw,
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "is_breach": is_breach,
        "is_severe": is_severe,
        "_recorded_dt": recorded_dt,
        "_created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    zone["recent_readings"].append(reading)
    apply_posture(zone)
    db.touch(zone)
    return success_object(serialize_zone(zone), 201)
