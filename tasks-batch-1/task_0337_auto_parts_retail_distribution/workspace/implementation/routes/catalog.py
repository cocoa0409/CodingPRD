"""Vehicle, Fitment, CrossReference, and PriceTier endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from middleware import require_role, get_body
from response import success, list_success
from services import common as c
from services.model import (
    stamp_common,
    stamp_immutable,
    serialize,
    get_vehicle,
    get_fitment,
    get_cross_reference,
    get_price_tier,
    get_part,
)

bp = Blueprint("catalog", __name__)

ALL_ROLES = ("CounterClerk", "WholesaleRep", "InventoryManager", "WarrantyAdmin")

POSITIONS = {"FRONT", "REAR", "LEFT", "RIGHT", "UNIVERSAL"}
RELATIONS = {"SUPERSEDES", "EQUIVALENT", "OE_TO_AFTERMARKET"}


# ---- Vehicle ----
@bp.post("/vehicles")
def create_vehicle():
    require_role("InventoryManager")
    body = get_body()
    year = c.as_int(body, "year", required=True, min_value=1900, max_value=2100)
    make = c.as_nonempty_string(body, "make", required=True)
    model = c.as_nonempty_string(body, "model", required=True)
    engine = c.as_string(body, "engine", required=False, default="")
    veh = {"year": year, "make": make, "model": model, "engine": engine}
    stamp_common(veh)
    db.vehicles[veh["id"]] = veh
    return success(serialize(veh), 201)


@bp.get("/vehicles")
def list_vehicles():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    year = request.args.get("year")
    make = request.args.get("make")
    model = request.args.get("model")
    filters = []
    if year is not None:
        try:
            year_i = int(year)
        except (TypeError, ValueError):
            year_i = None
        filters.append(lambda v: v["year"] == year_i)
    if make is not None:
        filters.append(lambda v: v["make"] == make)
    if model is not None:
        filters.append(lambda v: v["model"] == model)
    page, total = c.paginate(db.vehicles.values(), limit, offset, filters)
    return list_success([serialize(v) for v in page], limit, offset, total)


@bp.get("/vehicles/<vid>")
def get_one_vehicle(vid):
    require_role(*ALL_ROLES)
    return success(serialize(get_vehicle(vid)))


# ---- Fitment ----
@bp.post("/fitments")
def create_fitment():
    require_role("InventoryManager")
    body = get_body()
    part_id = c.as_nonempty_string(body, "part_id", required=True)
    vehicle_id = c.as_nonempty_string(body, "vehicle_id", required=True)
    position = c.as_enum(body, "position", POSITIONS, required=False, default="UNIVERSAL")
    notes = c.as_string(body, "notes", required=False, default="")
    # existence: body ids left-to-right
    get_part(part_id)
    get_vehicle(vehicle_id)
    fit = {
        "part_id": part_id,
        "vehicle_id": vehicle_id,
        "position": position,
        "notes": notes,
    }
    stamp_immutable(fit)
    db.fitments[fit["id"]] = fit
    return success(serialize(fit), 201)


@bp.get("/fitments")
def list_fitments():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    part_id = request.args.get("part_id")
    vehicle_id = request.args.get("vehicle_id")
    filters = []
    if part_id is not None:
        filters.append(lambda f: f["part_id"] == part_id)
    if vehicle_id is not None:
        filters.append(lambda f: f["vehicle_id"] == vehicle_id)
    page, total = c.paginate(db.fitments.values(), limit, offset, filters)
    return list_success([serialize(f) for f in page], limit, offset, total)


@bp.get("/fitments/<fid>")
def get_one_fitment(fid):
    require_role(*ALL_ROLES)
    return success(serialize(get_fitment(fid)))


# ---- CrossReference ----
@bp.post("/cross-references")
def create_cross_reference():
    require_role("InventoryManager")
    body = get_body()
    part_id = c.as_nonempty_string(body, "part_id", required=True)
    interchange_part_id = c.as_nonempty_string(body, "interchange_part_id", required=True)
    relation = c.as_enum(body, "relation", RELATIONS, required=False, default="SUPERSEDES")
    get_part(part_id)
    get_part(interchange_part_id)
    xr = {
        "part_id": part_id,
        "interchange_part_id": interchange_part_id,
        "relation": relation,
    }
    stamp_immutable(xr)
    db.cross_references[xr["id"]] = xr
    return success(serialize(xr), 201)


@bp.get("/cross-references")
def list_cross_references():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    part_id = request.args.get("part_id")
    interchange_part_id = request.args.get("interchange_part_id")
    filters = []
    if part_id is not None:
        filters.append(lambda x: x["part_id"] == part_id)
    if interchange_part_id is not None:
        filters.append(lambda x: x["interchange_part_id"] == interchange_part_id)
    page, total = c.paginate(db.cross_references.values(), limit, offset, filters)
    return list_success([serialize(x) for x in page], limit, offset, total)


@bp.get("/cross-references/<xid>")
def get_one_cross_reference(xid):
    require_role(*ALL_ROLES)
    return success(serialize(get_cross_reference(xid)))


# ---- PriceTier ----
@bp.post("/price-tiers")
def create_price_tier():
    require_role("InventoryManager")
    body = get_body()
    name = c.as_nonempty_string(body, "name", required=True)
    discount_pct = c.as_number(body, "discount_pct", required=True, min_value=0.0, max_value=0.90)
    core_discount_pct = c.as_number(body, "core_discount_pct", required=False, default=0, min_value=0.0, max_value=0.90)
    min_margin_pct = c.as_number(body, "min_margin_pct", required=False, default=0, min_value=0.0, max_value=5.00)
    tier = {
        "name": name,
        "discount_pct": discount_pct,
        "core_discount_pct": core_discount_pct,
        "min_margin_pct": min_margin_pct,
    }
    stamp_common(tier)
    db.price_tiers[tier["id"]] = tier
    return success(serialize(tier), 201)


@bp.get("/price-tiers")
def list_price_tiers():
    require_role(*ALL_ROLES)
    limit, offset = c.parse_pagination()
    page, total = c.paginate(db.price_tiers.values(), limit, offset)
    return list_success([serialize(t) for t in page], limit, offset, total)


@bp.get("/price-tiers/<tid>")
def get_one_price_tier(tid):
    require_role(*ALL_ROLES)
    return success(serialize(get_price_tier(tid)))
