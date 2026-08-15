"""Tenant unit endpoints: add, list, get, patch (completeness recompute)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok, paginate
from services import core
from validation import parse_body, require_path_entity

bp = Blueprint("tenant_units", __name__)


def _owning_building(unit):
    return store.buildings.get(unit["building_id"])


@bp.post("/v1/buildings/<building_id>/tenant-units")
def create_tenant_unit(building_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    building = require_path_entity(store.buildings, building_id)
    if building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this building")
    body = parse_body({
        "unit_label": ("string", True, None),
        "floor_area_sqft": ("integer", True, None),
        "space_type": ("string", True, core.SPACE_TYPES),
        "occupied": ("boolean", False, None),
    }, allow_empty=False)
    if body["floor_area_sqft"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "floor_area_sqft must be greater than zero")
    unit = db.new_common({
        "id": db.new_id(),
        "building_id": building["id"],
        "unit_label": body["unit_label"],
        "floor_area_sqft": body["floor_area_sqft"],
        "space_type": body["space_type"],
        "occupied": body.get("occupied", True),
    })
    store.tenant_units[unit["id"]] = unit
    return created(unit)


@bp.get("/v1/tenant-units")
def list_tenant_units():
    get_context()
    rows = list(store.tenant_units.values())
    rows = paginate.filter(rows, "building_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/v1/tenant-units/<unit_id>")
def get_tenant_unit(unit_id):
    get_context()
    unit = require_path_entity(store.tenant_units, unit_id)
    return ok(unit)


@bp.patch("/v1/tenant-units/<unit_id>")
def patch_tenant_unit(unit_id):
    uid, _ = get_context()
    require_roles(["BuildingOwner"])
    unit = require_path_entity(store.tenant_units, unit_id)
    building = _owning_building(unit)
    if building is None or building["owner_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "BuildingOwner does not own this unit's building")
    body = parse_body({
        "floor_area_sqft": ("integer", False, None),
        "occupied": ("boolean", False, None),
    })
    if "floor_area_sqft" in body and body["floor_area_sqft"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "floor_area_sqft must be greater than zero")
    for field in ("floor_area_sqft", "occupied"):
        if field in body:
            unit[field] = body[field]
    db.touch(unit)
    # Recompute data_completeness_pct on the building's DRAFT|FLAGGED reports.
    for r in store.reports.values():
        if r["building_id"] == building["id"] and r["status"] in ("DRAFT", "FLAGGED"):
            cycle = store.cycles.get(r["cycle_id"])
            if cycle is not None:
                r["data_completeness_pct"] = core.compute_completeness(building, cycle)
                db.touch(r)
    return ok(unit)
