"""Warehouse, zone, bin routes."""
from __future__ import annotations

from typing import Any

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.validation import (
    require_enum,
    require_int,
    require_keys,
    require_number,
    require_str,
)
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


_ZONE_TYPES = {"FROZEN", "REFRIGERATED", "COOL", "ROOM_TEMP", "CONTROLLED_TEMP", "QUARANTINE"}
_BIN_TAGS = {"NONE", "NARCOTIC", "PSYCHOTROPIC", "BIOLOGICAL", "VACCINE"}
_POSTURES = {"OPEN", "RESTRICTED", "FROZEN"}
_BIN_STATUSES = {"AVAILABLE", "OCCUPIED", "LOCKED"}


_ALL_ROLES = ("WarehouseAdmin", "Receiver", "QAOfficer", "Picker", "RecallOfficer")


def register(app: Flask) -> None:
    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------
    @app.route("/warehouses", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def create_warehouse():
        body = get_json_body()
        require_keys(body, ["code", "name", "gsp_license_no"])
        with LOCK:
            wh = common_fields_create()
            wh.update(
                {
                    "code": require_str(body["code"], "code"),
                    "name": require_str(body["name"], "name"),
                    "gsp_license_no": require_str(body["gsp_license_no"], "gsp_license_no"),
                    "clock_minutes": 0,
                    "status": "ACTIVE",
                }
            )
            get_store().warehouses[wh["id"]] = wh
        return created(wh)

    @app.route("/warehouses", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def list_warehouses():
        limit, offset = parse_limit_offset()
        items = sorted(get_store().warehouses.values(), key=lambda w: w["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/warehouses/<wid>", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def get_warehouse(wid: str):
        wh = get_store().warehouses.get(wid)
        if not wh:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        return ok(wh)

    # ------------------------------------------------------------------
    # Zones
    # ------------------------------------------------------------------
    @app.route("/warehouses/<wid>/zones", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def create_zone(wid: str):
        body = get_json_body()
        wh = get_store().warehouses.get(wid)
        if not wh:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        require_keys(
            body,
            [
                "code",
                "zone_type",
                "target_temp_low_c",
                "target_temp_high_c",
                "alarm_low_c",
                "alarm_high_c",
                "capacity_units",
            ],
        )
        zone_type = require_enum(body["zone_type"], "zone_type", _ZONE_TYPES)
        target_low = require_number(body["target_temp_low_c"], "target_temp_low_c")
        target_high = require_number(body["target_temp_high_c"], "target_temp_high_c")
        alarm_low = require_number(body["alarm_low_c"], "alarm_low_c")
        alarm_high = require_number(body["alarm_high_c"], "alarm_high_c")
        capacity = require_int(body["capacity_units"], "capacity_units", allow_zero=True)
        if not (alarm_low <= target_low <= target_high <= alarm_high):
            raise ApiError(
                "ERR_VALIDATION_FAILED",
                "Required: alarm_low_c <= target_temp_low_c <= target_temp_high_c <= alarm_high_c",
            )
        with LOCK:
            z = common_fields_create()
            z.update(
                {
                    "warehouse_id": wid,
                    "code": require_str(body["code"], "code"),
                    "zone_type": zone_type,
                    "target_temp_low_c": target_low,
                    "target_temp_high_c": target_high,
                    "alarm_low_c": alarm_low,
                    "alarm_high_c": alarm_high,
                    "current_posture": "OPEN",
                    "last_sensor_reading_c": None,
                    "capacity_units": capacity,
                    "utilization_units": 0,
                }
            )
            get_store().zones[z["id"]] = z
        return created(z)

    @app.route("/warehouses/<wid>/zones", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def list_zones(wid: str):
        if wid not in get_store().warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        ztype = parse_filter("zone_type")
        posture = parse_filter("current_posture")
        items: list[dict[str, Any]] = [
            z for z in get_store().zones.values() if z["warehouse_id"] == wid
        ]
        if ztype is not None:
            items = [z for z in items if z["zone_type"] == ztype]
        if posture is not None:
            items = [z for z in items if z["current_posture"] == posture]
        items.sort(key=lambda z: z["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/zones/<zid>", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def get_zone(zid: str):
        z = get_store().zones.get(zid)
        if not z:
            raise ApiError("ERR_NOT_FOUND", "Zone not found")
        return ok(z)

    # ------------------------------------------------------------------
    # Bins
    # ------------------------------------------------------------------
    @app.route("/zones/<zid>/bins", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def create_bin(zid: str):
        body = get_json_body()
        zone = get_store().zones.get(zid)
        if not zone:
            raise ApiError("ERR_NOT_FOUND", "Zone not found")
        require_keys(body, ["code", "volume_units", "weight_limit_kg"])
        tag = body.get("special_storage_tag", "NONE") or "NONE"
        tag = require_enum(tag, "special_storage_tag", _BIN_TAGS)
        with LOCK:
            b = common_fields_create()
            b.update(
                {
                    "zone_id": zid,
                    "warehouse_id": zone["warehouse_id"],
                    "code": require_str(body["code"], "code"),
                    "volume_units": require_int(body["volume_units"], "volume_units", allow_zero=False),
                    "weight_limit_kg": require_number(body["weight_limit_kg"], "weight_limit_kg"),
                    "special_storage_tag": tag,
                    "current_lot_id": None,
                    "occupied_volume": 0,
                    "occupied_weight_kg": 0,
                    "status": "AVAILABLE",
                }
            )
            # If parent zone is FROZEN, new bin starts LOCKED.
            if zone.get("current_posture") == "FROZEN":
                b["status"] = "LOCKED"
            get_store().bins[b["id"]] = b
        return created(b)

    @app.route("/zones/<zid>/bins", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def list_bins(zid: str):
        if zid not in get_store().zones:
            raise ApiError("ERR_NOT_FOUND", "Zone not found")
        limit, offset = parse_limit_offset()
        status_f = parse_filter("status")
        items = [b for b in get_store().bins.values() if b["zone_id"] == zid]
        if status_f is not None:
            items = [b for b in items if b["status"] == status_f]
        items.sort(key=lambda b: b["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
