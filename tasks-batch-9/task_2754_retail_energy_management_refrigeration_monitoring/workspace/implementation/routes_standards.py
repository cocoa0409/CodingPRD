"""The setpoint standard library and its supersession chain (PRD 3.1)."""

from flask import Blueprint, g

import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import CLIMATE_ZONES, SEASONS, STANDARD_STATUSES, STORE_FORMATS
from db import db, new_row, rows
from errors import ApiError
from security import ENERGY_MANAGER, NON_GATEWAY_ROLES, roles

bp = Blueprint("standards", __name__)


@bp.route("/setpoint-standards", methods=["POST"])
@roles(ENERGY_MANAGER)
def draft_standard():
    body = v.body()
    climate_zone = v.get_enum(body, "climate_zone", CLIMATE_ZONES)
    store_format = v.get_enum(body, "store_format", STORE_FORMATS)
    season = v.get_enum(body, "season", SEASONS)
    cooling = v.get_num(body, "cooling_setpoint_f", 1, ge="60.0", le="85.0")
    heating = v.get_num(body, "heating_setpoint_f", 1, ge="55.0", le="78.0")
    deadband = v.get_num(body, "deadband_f", 1, ge="1.0")
    lux_target = v.get_int(body, "lighting_lux_target", min_=1)
    supersedes_id = v.get_str(body, "supersedes_standard_id", required=False)
    if heating >= cooling:
        v.bad("'heating_setpoint_f' must be strictly below 'cooling_setpoint_f'")
    predecessor = None
    if supersedes_id is not None:
        predecessor = common.get_standard(supersedes_id)
    for existing in rows(db.standards):
        if existing["status"] not in ("DRAFT", "PUBLISHED"):
            continue
        if (existing["climate_zone"] != climate_zone
                or existing["store_format"] != store_format
                or existing["season"] != season):
            continue
        if existing["status"] == "PUBLISHED" and supersedes_id == existing["id"]:
            continue
        raise ApiError("ERR_DUPLICATE_STANDARD_SCOPE")
    revision = 1 if predecessor is None else predecessor["revision"] + 1
    standard = new_row(db.standards, {
        "climate_zone": climate_zone,
        "store_format": store_format,
        "season": season,
        "cooling_setpoint_f": cooling,
        "heating_setpoint_f": heating,
        "deadband_f": deadband,
        "lighting_lux_target": lux_target,
        "status": "DRAFT",
        "revision": revision,
        "supersedes_standard_id": supersedes_id,
        "published_at_iso": None,
        "published_by_user_id": None,
    })
    return envelope.created(serial.standard(standard))


@bp.route("/setpoint-standards", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_standards():
    limit, offset = v.query_pagination()
    climate_zone = v.query_enum("climate_zone", CLIMATE_ZONES)
    store_format = v.query_enum("store_format", STORE_FORMATS)
    season = v.query_enum("season", SEASONS)
    status = v.query_enum("status", STANDARD_STATUSES)
    supersedes_id = v.query_str("supersedes_standard_id")
    items = rows(db.standards)
    items = common.apply_eq(items, "climate_zone", climate_zone)
    items = common.apply_eq(items, "store_format", store_format)
    items = common.apply_eq(items, "season", season)
    items = common.apply_eq(items, "status", status)
    items = common.apply_eq(items, "supersedes_standard_id", supersedes_id)
    return common.list_response(items, serial.standard, limit, offset)


@bp.route("/setpoint-standards/<standard_id>", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def get_standard(standard_id):
    standard = common.get_standard(standard_id)
    return envelope.ok(serial.standard(standard))


@bp.route("/setpoint-standards/<standard_id>/publish", methods=["POST"])
@roles(ENERGY_MANAGER)
def publish_standard(standard_id):
    standard = common.get_standard(standard_id)
    if standard["status"] != "DRAFT":
        raise ApiError("ERR_STANDARD_STATE_INVALID")
    predecessor = None
    if standard["supersedes_standard_id"] is not None:
        predecessor = db.standards.get(standard["supersedes_standard_id"])
        if predecessor is None or predecessor["status"] != "PUBLISHED":
            raise ApiError("ERR_STANDARD_NOT_PUBLISHED")
    standard["status"] = "PUBLISHED"
    standard["published_at_iso"] = db.clock
    standard["published_by_user_id"] = g.user_id
    cascade.touch(standard)
    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        cascade.touch(predecessor)
        for store in rows(db.stores):
            if (store["active_standard_id"] == predecessor["id"]
                    and store["bms_status"] == "ACTIVE"):
                store["bms_status"] = "DEGRADED"
                cascade.touch(store)
                cascade.recompute_posture(store)
    return envelope.ok(serial.standard(standard))
