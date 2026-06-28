"""Catalog: TurfProduct + InfillProduct (PRD 3.2). Catalog records carry only
id + created_at (no updated_at, no version — PRD 2.4). Created by OpsAdmin only;
sku unique. Listed by OpsAdmin/SalesRep with active filter."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_bool,
    require_enum,
    require_fields,
    require_int_gt,
    require_number_gt,
    require_string,
    stamp_new_minimal,
)
from db import db
from errors import err
from lookups import get_infill_or_404, get_turf_or_404
from middleware import get_auth, require_role
from response import success

bp = Blueprint("catalog", __name__)

INFILL_MATERIALS = {"SILICA", "ACRYLIC_COATED", "ZEOLITE", "RUBBER", "CORK"}


def _active_filter(items):
    active_raw = request.args.get("active")
    if active_raw is None:
        return items
    if active_raw.lower() in ("true", "1"):
        want = True
    elif active_raw.lower() in ("false", "0"):
        want = False
    else:
        raise err("ERR_INVALID_REQUEST", "active filter must be a boolean.")
    return [i for i in items if i["active"] == want]


# --------------------------------------------------------------------------
# TurfProduct
# --------------------------------------------------------------------------
@bp.route("/turf-products", methods=["POST"])
def create_turf():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    body = get_json_body()
    require_fields(body, ["sku", "name", "pile_height_mm", "price_per_sqft_cents", "roll_width_ft"])
    sku = require_string(body, "sku")
    name = require_string(body, "name")
    pile_height_mm = require_number_gt(body, "pile_height_mm", 0)
    price = require_int_gt(body, "price_per_sqft_cents", 0)
    roll_width_ft = require_number_gt(body, "roll_width_ft", 0)
    pet_approved = require_bool(body, "pet_approved", False)
    playground_rated = require_bool(body, "playground_rated", False)
    putting_rated = require_bool(body, "putting_rated", False)
    active = require_bool(body, "active", True)

    for t in db.turf_products.values():
        if t["sku"] == sku:
            raise err("ERR_DUPLICATE_RESOURCE", "Turf product sku already exists.")

    rec = {
        "sku": sku,
        "name": name,
        "pile_height_mm": pile_height_mm,
        "price_per_sqft_cents": price,
        "roll_width_ft": roll_width_ft,
        "pet_approved": pet_approved,
        "playground_rated": playground_rated,
        "putting_rated": putting_rated,
        "active": active,
    }
    stamp_new_minimal(rec)
    db.turf_products[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/turf-products", methods=["GET"])
def list_turf():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    items = _active_filter(list(db.turf_products.values()))
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/turf-products/<turf_product_id>", methods=["GET"])
def get_turf(turf_product_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    rec = get_turf_or_404(turf_product_id)
    return success(public(rec), status=200)


# --------------------------------------------------------------------------
# InfillProduct
# --------------------------------------------------------------------------
@bp.route("/infill-products", methods=["POST"])
def create_infill():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    body = get_json_body()
    require_fields(body, ["sku", "name", "material", "price_per_sqft_cents", "coverage_lbs_per_sqft"])
    sku = require_string(body, "sku")
    name = require_string(body, "name")
    material = require_enum(body, "material", INFILL_MATERIALS)
    price = require_int_gt(body, "price_per_sqft_cents", 0)
    coverage = require_number_gt(body, "coverage_lbs_per_sqft", 0)
    antimicrobial = require_bool(body, "antimicrobial", False)
    nonabrasive = require_bool(body, "nonabrasive", False)
    active = require_bool(body, "active", True)

    for i in db.infill_products.values():
        if i["sku"] == sku:
            raise err("ERR_DUPLICATE_RESOURCE", "Infill product sku already exists.")

    rec = {
        "sku": sku,
        "name": name,
        "material": material,
        "price_per_sqft_cents": price,
        "coverage_lbs_per_sqft": coverage,
        "antimicrobial": antimicrobial,
        "nonabrasive": nonabrasive,
        "active": active,
    }
    stamp_new_minimal(rec)
    db.infill_products[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/infill-products", methods=["GET"])
def list_infill():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    items = _active_filter(list(db.infill_products.values()))
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/infill-products/<infill_product_id>", methods=["GET"])
def get_infill(infill_product_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    rec = get_infill_or_404(infill_product_id)
    return success(public(rec), status=200)
