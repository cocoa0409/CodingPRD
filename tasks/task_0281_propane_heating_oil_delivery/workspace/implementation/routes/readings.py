"""TankMonitorReading and DegreeDayReading endpoints (PRD §3.4, §2.11)."""
from flask import Blueprint, request

import db
import errors
from common import (parse_pagination, paginate, sort_by_created,
                    require_int, require_iso_datetime, require_string)
from middleware import require_auth, require_role, check_owner, get_json_body
from response import object_response, array_response
from services import lookups as L
from routes.tanks import recompute_reorder

bp = Blueprint("readings", __name__)

ALL_ROLES = {"AccountManager", "Dispatcher", "Driver", "Inspector", "Customer"}


@bp.post("/tanks/<tank_id>/readings")
def create_reading(tank_id):
    _, role = require_auth()
    require_role(role, {"Driver", "Inspector", "Dispatcher"})
    tank = L.get_tank(tank_id)
    body = get_json_body()

    reading_gallons = require_int(body, "reading_gallons", minimum=0)
    if reading_gallons > tank["capacity_gallons"]:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400,
                              "reading_gallons exceeds tank capacity")
    read_at = require_iso_datetime(body, "read_at")

    rec = {
        "tank_id": tank["id"],
        "reading_gallons": reading_gallons,
        "read_at": read_at,
    }
    db.stamp_create_lean(rec)
    db.tank_readings[rec["id"]] = rec

    # Side effects on the parent tank.
    tank["current_gallons"] = reading_gallons
    tank["last_reading_at"] = read_at
    recompute_reorder(tank)
    db.touch(tank)

    return object_response(L.serialize_reading(rec), 201)


@bp.get("/tank-readings/<reading_id>")
def get_reading(reading_id):
    user_id, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = L.get_reading(reading_id)
    tank = db.tanks.get(rec["tank_id"])
    if tank is not None:
        check_owner(role, user_id, tank["account_id"])
    return object_response(L.serialize_reading(rec), 200)


@bp.get("/tank-readings")
def list_readings():
    user_id, role = require_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    tank_id = request.args.get("tank_id")

    items = list(db.tank_readings.values())
    if role == "Customer":
        owned = {t["id"] for t in L.tanks_for_account(user_id)}
        items = [r for r in items if r.get("tank_id") in owned]
    if tank_id is not None:
        items = [r for r in items if r.get("tank_id") == tank_id]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_reading(r) for r in page], limit, offset, total)


# --- DegreeDayReading ---

@bp.post("/degree-day-readings")
def create_degree_day():
    _, role = require_auth()
    require_role(role, {"Dispatcher", "AccountManager"})
    body = get_json_body()
    region_code = require_string(body, "region_code")
    reading_date = require_iso_datetime(body, "reading_date")
    heating_degree_days = require_int(body, "heating_degree_days", minimum=0)

    rec = {
        "region_code": region_code,
        "reading_date": reading_date,
        "heating_degree_days": heating_degree_days,
    }
    db.stamp_create_lean(rec)
    db.degree_day_readings[rec["id"]] = rec
    return object_response(L.serialize_degree_day(rec), 201)


@bp.get("/degree-day-readings")
def list_degree_day():
    _, role = require_auth()
    require_role(role, {"AccountManager", "Dispatcher"})
    limit, offset = parse_pagination()
    region_code = request.args.get("region_code")

    items = list(db.degree_day_readings.values())
    if region_code is not None:
        items = [r for r in items if r.get("region_code") == region_code]

    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([L.serialize_degree_day(r) for r in page], limit, offset, total)
