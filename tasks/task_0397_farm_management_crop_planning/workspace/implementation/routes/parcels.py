"""Parcel endpoints (PRD §3.1).

POST /parcels                       FarmManager
GET  /parcels/{id}                  all
GET  /parcels                       all (filter status; paginated)
GET  /parcels/{id}/crop-plans       all
GET  /parcels/{id}/irrigation-events all
"""
from flask import Blueprint

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
)
from middleware import require_roles
from response import array_response, object_response
from flask import request

bp = Blueprint("parcels", __name__)

SOIL_TYPES = {"CLAY", "LOAM", "SAND", "SILT"}
PARCEL_STATUSES = {"AVAILABLE", "RESTRICTED", "RETIRED"}

ALL_ROLES = ("FarmManager", "Agronomist", "Applicator", "SalesAgent")


@bp.post("/parcels")
@require_roles("FarmManager")
def create_parcel():
    body = get_json_body()
    name = require_str(body, "name")
    acreage = require_number(body, "acreage")
    soil_type = require_enum(body, "soil_type", SOIL_TYPES)
    if acreage <= 0:
        raise err("ERR_INVALID_REQUEST", "acreage must be > 0.")

    rec = db.new_entity(
        {
            "name": name,
            "acreage": acreage,
            "soil_type": soil_type,
            "status": "AVAILABLE",
            "reentry_blocked_until": None,
            "active_crop_plan_count": 0,
        }
    )
    db.parcels[rec["id"]] = rec
    return object_response(serializers.parcel(rec), 201)


@bp.get("/parcels/<pid>")
@require_roles(*ALL_ROLES)
def get_parcel(pid):
    rec = lookups.parcel(pid)
    return object_response(serializers.parcel(rec))


@bp.get("/parcels")
@require_roles(*ALL_ROLES)
def list_parcels():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = list(db.parcels.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([serializers.parcel(r) for r in page], limit, offset, total)


@bp.get("/parcels/<pid>/crop-plans")
@require_roles(*ALL_ROLES)
def list_parcel_crop_plans(pid):
    lookups.parcel(pid)
    limit, offset = parse_pagination()
    records = [p for p in db.crop_plans.values() if p["parcel_id"] == pid]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.crop_plan(r) for r in page], limit, offset, total
    )


@bp.get("/parcels/<pid>/irrigation-events")
@require_roles(*ALL_ROLES)
def list_parcel_irrigation(pid):
    lookups.parcel(pid)
    limit, offset = parse_pagination()
    records = [e for e in db.irrigation_events.values() if e["parcel_id"] == pid]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.irrigation_event(r) for r in page], limit, offset, total
    )
