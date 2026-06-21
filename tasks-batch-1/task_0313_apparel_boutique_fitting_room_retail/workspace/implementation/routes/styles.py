"""Styles and the size-by-color SKU-variant matrix (PRD §3.1)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, require_enum,
    parse_pagination, paginate, serialize, serialize_list, bubble_style_total,
)

bp = Blueprint("styles", __name__)

CATEGORIES = {"TOPS", "BOTTOMS", "DRESSES", "OUTERWEAR", "ACCESSORIES"}
SEASONS = {"SPRING", "SUMMER", "FALL", "WINTER"}
SIZES = {"XS", "S", "M", "L", "XL"}

ALL_READ_ROLES = {"StoreManager", "Merchandiser", "StoreAssociate", "Customer"}


@bp.post("/styles")
def create_style():
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    body = get_json_body()

    boutique_id = require_str(body, "boutique_id")
    style_code = require_str(body, "style_code")
    name = require_str(body, "name")
    category = require_enum(body, "category", CATEGORIES)
    season = require_enum(body, "season", SEASONS)
    list_price_cents = require_int(body, "list_price_cents")
    if list_price_cents <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "list_price_cents must be > 0")

    get_or_404("boutique", boutique_id)

    for s in db.styles.values():
        if s["boutique_id"] == boutique_id and s["style_code"] == style_code:
            raise err(errors.ERR_DUPLICATE_KEY, "style_code already exists in this boutique")

    rec = stamp_new({
        "boutique_id": boutique_id,
        "style_code": style_code,
        "name": name,
        "category": category,
        "season": season,
        "list_price_cents": list_price_cents,
        "current_price_cents": list_price_cents,
        "clearance": False,
        "total_available": 0,
    })
    db.styles[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/styles/<rid>")
def get_style(rid):
    _, role = authenticate()
    require_role(role, ALL_READ_ROLES)
    rec = get_or_404("style", rid)
    return success(serialize(rec))


@bp.get("/styles")
def list_styles():
    _, role = authenticate()
    require_role(role, ALL_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.styles.values())
    boutique_id = request.args.get("boutique_id")
    season = request.args.get("season")
    category = request.args.get("category")
    if boutique_id is not None:
        items = [s for s in items if s["boutique_id"] == boutique_id]
    if season is not None:
        items = [s for s in items if s["season"] == season]
    if category is not None:
        items = [s for s in items if s["category"] == category]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/styles/<rid>/sku-variants")
def create_variant(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    style = get_or_404("style", rid)
    body = get_json_body()

    size = require_enum(body, "size", SIZES)
    color = require_str(body, "color")
    on_hand = require_int(body, "on_hand")
    if on_hand < 0:
        raise err(errors.ERR_INVALID_REQUEST, "on_hand must be >= 0")

    rec = stamp_new({
        "style_id": style["id"],
        "size": size,
        "color": color,
        "on_hand": on_hand,
        "reserved": 0,
        "available": on_hand,
        "status": "STOCKED",
    })
    db.sku_variants[rec["id"]] = rec
    bubble_style_total(style["id"])
    return success(serialize(rec), 201)


@bp.get("/styles/<rid>/sku-variants")
def list_style_variants(rid):
    _, role = authenticate()
    require_role(role, ALL_READ_ROLES)
    get_or_404("style", rid)
    limit, offset = parse_pagination()
    items = [v for v in db.sku_variants.values() if v["style_id"] == rid]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.get("/sku-variants/<rid>")
def get_variant(rid):
    _, role = authenticate()
    require_role(role, ALL_READ_ROLES)
    rec = get_or_404("sku_variant", rid)
    return success(serialize(rec))


@bp.post("/sku-variants/<rid>/restock")
def restock_variant(rid):
    _, role = authenticate()
    require_role(role, {"Merchandiser"})
    variant = get_or_404("sku_variant", rid)
    body = get_json_body()

    units = require_int(body, "units")
    if units < 1:
        raise err(errors.ERR_INVALID_REQUEST, "units must be >= 1")

    variant["on_hand"] += units
    variant["available"] += units
    touch(variant)
    bubble_style_total(variant["style_id"])
    return success(serialize(variant))
