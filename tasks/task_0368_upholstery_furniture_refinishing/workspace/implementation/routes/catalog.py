"""FabricSku and FoamSpec catalog routes."""
from flask import Blueprint

from db import db
from errors import err
import errors
from middleware import get_identity, require_roles
from helpers import (base_record, get_body, require_string, require_int,
                     optional_number, get_resource_or_404, touch, serialize)
from response import ok_object

bp = Blueprint("catalog", __name__)


@bp.post("/fabric-skus")
def create_fabric_sku():
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    body = get_body()
    sku_code = require_string(body, "sku_code")
    name = require_string(body, "name")
    price = require_int(body, "price_cents_per_yard")
    roll_width = require_int(body, "roll_width_inches")
    if price < 0:
        raise err(errors.ERR_INVALID_REQUEST, "price_cents_per_yard must be >= 0")
    if roll_width <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "roll_width_inches must be > 0")
    in_stock = optional_number(body, "in_stock_yards", 0)
    if in_stock < 0:
        raise err(errors.ERR_INVALID_REQUEST, "in_stock_yards must be >= 0")
    rec = base_record(common=True)
    rec.update({
        "sku_code": sku_code,
        "name": name,
        "price_cents_per_yard": price,
        "roll_width_inches": roll_width,
        "in_stock_yards": in_stock,
        "status": "LISTED",
    })
    db.fabric_skus[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/fabric-skus/<fid>")
def get_fabric_sku(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator", "IntakeClerk"})
    rec = get_resource_or_404(db.fabric_skus, fid)
    return ok_object(serialize(rec), 200)


@bp.post("/fabric-skus/<fid>/discontinue")
def discontinue_fabric_sku(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.fabric_skus, fid)
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return ok_object(serialize(rec), 200)


@bp.post("/foam-specs")
def create_foam_spec():
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    body = get_body()
    grade_code = require_string(body, "grade_code")
    density = body.get("density_lb")
    if isinstance(density, bool) or not isinstance(density, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "density_lb must be a number")
    if density <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "density_lb must be > 0")
    price = require_int(body, "price_cents_per_board_foot")
    if price < 0:
        raise err(errors.ERR_INVALID_REQUEST, "price_cents_per_board_foot must be >= 0")
    rec = base_record(common=True)
    rec.update({
        "grade_code": grade_code,
        "density_lb": density,
        "price_cents_per_board_foot": price,
        "status": "LISTED",
    })
    db.foam_specs[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/foam-specs/<fid>")
def get_foam_spec(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager", "Estimator", "IntakeClerk"})
    rec = get_resource_or_404(db.foam_specs, fid)
    return ok_object(serialize(rec), 200)


@bp.post("/foam-specs/<fid>/discontinue")
def discontinue_foam_spec(fid):
    _, role = get_identity()
    require_roles(role, {"ShopManager"})
    rec = get_resource_or_404(db.foam_specs, fid)
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return ok_object(serialize(rec), 200)
