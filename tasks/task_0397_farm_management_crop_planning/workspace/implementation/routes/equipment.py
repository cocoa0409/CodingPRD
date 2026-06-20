"""EquipmentAsset + EquipmentUsage endpoints (PRD §3.8).

Equipment overlap is half-open [start, end): back-to-back permitted.
EquipmentUsage: RECORDED (no void endpoint declared in PRD §4).
"""
from flask import Blueprint, request

import db
import lookups
import serializers
from errors import err
from helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_str,
    round2,
)
from middleware import require_roles
from response import array_response, object_response
from services import compute
from timeutil import parse_iso

bp = Blueprint("equipment", __name__)
KINDS = {"TRACTOR", "COMBINE", "SPRAYER", "PLANTER"}
READ_ROLES = ("FarmManager", "Agronomist")


def _recompute_asset_hours(asset):
    total = sum(
        eu["hours"]
        for eu in db.equipment_usages.values()
        if eu["equipment_asset_id"] == asset["id"] and eu["status"] == "RECORDED"
    )
    asset["total_logged_hours"] = round2(total)


# ---------------- EquipmentAsset ----------------
@bp.post("/equipment-assets")
@require_roles("FarmManager")
def create_asset():
    body = get_json_body()
    name = require_str(body, "name")
    kind = require_enum(body, "kind", KINDS)
    hourly_cost = require_number(body, "hourly_cost")
    if hourly_cost < 0:
        raise err("ERR_INVALID_REQUEST", "hourly_cost must be >= 0.")

    rec = db.new_entity(
        {
            "name": name,
            "kind": kind,
            "hourly_cost": hourly_cost,
            "status": "ACTIVE",
            "total_logged_hours": round2(0),
        }
    )
    db.equipment_assets[rec["id"]] = rec
    return object_response(serializers.equipment_asset(rec), 201)


@bp.get("/equipment-assets/<aid>")
@require_roles(*READ_ROLES)
def get_asset(aid):
    rec = lookups.equipment_asset(aid)
    return object_response(serializers.equipment_asset(rec))


@bp.get("/equipment-assets/<aid>/usages")
@require_roles(*READ_ROLES)
def list_asset_usages(aid):
    lookups.equipment_asset(aid)
    limit, offset = parse_pagination()
    records = [u for u in db.equipment_usages.values() if u["equipment_asset_id"] == aid]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.equipment_usage(r) for r in page], limit, offset, total
    )


# ---------------- EquipmentUsage ----------------
@bp.post("/equipment-usages")
@require_roles("Agronomist")
def create_usage():
    body = get_json_body()
    equipment_asset_id = require_str(body, "equipment_asset_id")
    crop_plan_id = require_str(body, "crop_plan_id")
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")

    asset = lookups.equipment_asset(equipment_asset_id)
    plan = lookups.crop_plan(crop_plan_id)

    ws = parse_iso(window_start_raw)
    we = parse_iso(window_end_raw)
    if ws is None or we is None:
        raise err("ERR_INVALID_REQUEST", "window_start/window_end must be ISO 8601.")
    # window_end must be strictly after window_start (PRD §3.8).
    if not (we > ws):
        raise err("ERR_VALIDATION_WINDOW_INVALID", "window_end must be after window_start.")

    # Booking against a DOWN asset is rejected (PRD §3.8).
    if asset["status"] == "DOWN":
        raise err("ERR_EQUIPMENT_DOWN", "Equipment asset is DOWN.")

    # Half-open overlap: new.start < existing.end AND existing.start < new.end.
    for u in db.equipment_usages.values():
        if u["equipment_asset_id"] != equipment_asset_id or u["status"] != "RECORDED":
            continue
        u_start = parse_iso(u["window_start"])
        u_end = parse_iso(u["window_end"])
        if ws < u_end and u_start < we:
            raise err("ERR_EQUIPMENT_WINDOW_CONFLICT", "Equipment window conflicts.")

    hours = round2((we - ws).total_seconds() / 3600.0)
    usage_cost = round2(hours * asset["hourly_cost"])

    rec = db.new_entity(
        {
            "equipment_asset_id": equipment_asset_id,
            "crop_plan_id": crop_plan_id,
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "hours": hours,
            "usage_cost": usage_cost,
            "status": "RECORDED",
        }
    )
    db.equipment_usages[rec["id"]] = rec

    _recompute_asset_hours(asset)
    db.touch(asset)

    compute.recompute_actual_equipment_cost(plan)
    compute.recompute_provisional_cost_per_acre(plan)
    db.touch(plan)

    return object_response(serializers.equipment_usage(rec), 201)


@bp.get("/equipment-usages/<uid>")
@require_roles(*READ_ROLES)
def get_usage(uid):
    rec = lookups.equipment_usage(uid)
    return object_response(serializers.equipment_usage(rec))


@bp.get("/equipment-usages")
@require_roles(*READ_ROLES)
def list_usages():
    limit, offset = parse_pagination()
    records = list(db.equipment_usages.values())
    for key in ("crop_plan_id", "equipment_asset_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r[key] == val]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.equipment_usage(r) for r in page], limit, offset, total
    )
