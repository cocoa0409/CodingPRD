"""Shipping wave endpoints (PRD §3.8, §3.9)."""
from flask import Blueprint, request

from db import db
from common import (new_record, touch, serialize, get_body, require_field,
                    require_int, require_enum, parse_datetime, must_exist, paginate)
from middleware import authenticate, require_roles
from response import success, list_success
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CUTOFF_NOT_REACHED, ERR_EMPTY_WAVE)
from services.inventory import release_allocation, commit_allocation

bp = Blueprint("waves", __name__)

CADENCES = {"MONTHLY", "QUARTERLY"}


@bp.post("/waves")
def create_wave():
    authenticate()
    require_roles("CurationAdmin")
    body = get_body()
    cadence = require_enum(body, "cadence", CADENCES)
    cutoff_raw = require_field(body, "cutoff_at")
    ship_raw = require_field(body, "ship_date")
    cutoff_at = parse_datetime(cutoff_raw, "cutoff_at")
    ship_date = parse_datetime(ship_raw, "ship_date")
    capacity = require_int(body, "capacity", minimum=1)

    # ship_date must be strictly after cutoff_at (PRD §3.8)
    if not ship_date > cutoff_at:
        raise err(ERR_INVALID_REQUEST, "ship_date must be strictly after cutoff_at.")

    wave = new_record({
        "cadence": cadence,
        "cutoff_at": cutoff_at,
        "ship_date": ship_date,
        "capacity": capacity,
        "reserved_count": 0,
        "status": "OPEN",
    })
    db.shipping_waves[wave["id"]] = wave
    return success(serialize(wave), status=201)


@bp.get("/waves/<wid>")
def get_wave(wid):
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    wave = must_exist(db.shipping_waves, wid, "ShippingWave")
    return success(serialize(wave))


@bp.get("/waves")
def list_waves():
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    records = list(db.shipping_waves.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    cadence = request.args.get("cadence")
    if cadence is not None:
        records = [r for r in records if r["cadence"] == cadence]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.post("/waves/<wid>/lock")
def lock_wave(wid):
    authenticate()
    require_roles("CurationAdmin")
    wave = must_exist(db.shipping_waves, wid, "ShippingWave")
    if wave["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Lock requires an OPEN wave.")
    # temporal: clock must be at-or-after cutoff_at
    if db.now() < wave["cutoff_at"]:
        raise err(ERR_CUTOFF_NOT_REACHED, "Cannot lock before cutoff.")
    wave["status"] = "LOCKED"
    touch(wave)
    return success(serialize(wave))


@bp.post("/waves/<wid>/ship")
def ship_wave(wid):
    authenticate()
    require_roles("CurationAdmin")
    wave = must_exist(db.shipping_waves, wid, "ShippingWave")
    if wave["status"] != "LOCKED":
        raise err(ERR_INVALID_STATE, "Ship requires a LOCKED wave.")
    reserved = [a for a in db.allocations.values()
                if a["wave_id"] == wid and a["status"] == "RESERVED"]
    if len(reserved) < 1:
        raise err(ERR_EMPTY_WAVE, "Cannot ship a wave with zero reserved allocations.")
    reserved.sort(key=lambda a: a.get("_seq", 0))
    for alloc in reserved:
        commit_allocation(alloc)
    wave["status"] = "SHIPPED"
    touch(wave)
    return success(serialize(wave))


@bp.post("/waves/<wid>/cancel")
def cancel_wave(wid):
    authenticate()
    require_roles("CurationAdmin")
    wave = must_exist(db.shipping_waves, wid, "ShippingWave")
    if wave["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Cancel requires an OPEN wave.")
    reserved = [a for a in db.allocations.values()
                if a["wave_id"] == wid and a["status"] == "RESERVED"]
    reserved.sort(key=lambda a: a.get("_seq", 0))
    for alloc in reserved:
        # wave cancel reverts box decision FINALIZED -> CURATED (PRD §3.9)
        release_allocation(alloc, revert_decision="CURATED")
    wave["reserved_count"] = 0
    wave["status"] = "CANCELLED"
    touch(wave)
    return success(serialize(wave))
