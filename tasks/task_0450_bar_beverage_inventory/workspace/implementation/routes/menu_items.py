"""Menu item endpoints (PRD §3.4)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create, touch
from errors import ApiError, ERR_RECIPE_NOT_PUBLISHED, invalid_state
from middleware import require_roles
from response import object_response, array_response
from routes.lookup import get_menu_item, get_recipe
from services.calc import menu_engineering
from services.product import recompute_pour_cost_pct
from services.finalize import record_sale
from clock import clock
from validate import (get_json_body, require, as_int, parse_pagination, paginate)
from timeutil import parse_iso

bp = Blueprint("menu_items", __name__)


@bp.route("/menu-items", methods=["POST"])
@require_roles("BarManager")
def create_menu_item():
    body = get_json_body()
    recipe_id = require(body, "recipe_id")
    menu_price_cents = as_int(require(body, "menu_price_cents"), "menu_price_cents", gt=0)
    # body FK existence (404)
    recipe = get_recipe(recipe_id)
    # business: recipe must be PUBLISHED (422)
    if recipe["status"] != "PUBLISHED":
        raise ApiError(ERR_RECIPE_NOT_PUBLISHED, 422, "MenuItem may only reference a PUBLISHED recipe.")
    record = {
        "recipe_id": recipe_id,
        "menu_price_cents": menu_price_cents,
        "units_sold": 0,
        "pour_cost_pct": 0,
        "menu_class": "UNCLASSIFIED",
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.menu_items[record["id"]] = record
    # pour_cost_pct computed (this touches the record -> version 2). Recompute
    # in place before serializing the created item.
    recompute_pour_cost_pct(record)
    return object_response(serialize.menu_item(record), 201)


@bp.route("/menu-items/engineering", methods=["GET"])
@require_roles("BarManager")
def menu_engineering_report():
    universe = menu_engineering()
    for mi in universe:
        touch(mi)
    # report returns the classified ACTIVE items, in creation order
    universe_sorted = sorted(universe, key=lambda m: (m["created_at"], m["_seq"]))
    limit, offset = parse_pagination()
    page, total = paginate(universe_sorted, limit, offset)
    return array_response([serialize.menu_item(m) for m in page], limit, offset, total)


@bp.route("/menu-items/<mid>", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def read_menu_item(mid):
    m = get_menu_item(mid)
    return object_response(serialize.menu_item(m))


@bp.route("/menu-items", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def list_menu_items():
    limit, offset = parse_pagination()
    recipe_id = request.args.get("recipe_id")
    status = request.args.get("status")
    items = list(db.menu_items.values())
    if recipe_id is not None:
        items = [m for m in items if m["recipe_id"] == recipe_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.menu_item(m) for m in page], limit, offset, total)


@bp.route("/menu-items/<mid>/record-sales", methods=["POST"])
@require_roles("BarManager")
def record_sales(mid):
    m = get_menu_item(mid)
    body = get_json_body()
    quantity = as_int(require(body, "quantity"), "quantity", gt=0)
    sold_at_raw = require(body, "sold_at")
    sold_at_dt = parse_iso(sold_at_raw, "sold_at")
    # DELISTED items cannot accept recorded sales (PRD §3.4)
    if m["status"] != "ACTIVE":
        raise invalid_state("A delisted menu item cannot accept recorded sales.")
    m["units_sold"] = int(m["units_sold"]) + quantity
    record_sale(mid, quantity, sold_at_dt)
    touch(m)
    return object_response(serialize.menu_item(m))


@bp.route("/menu-items/<mid>/delist", methods=["POST"])
@require_roles("BarManager")
def delist_menu_item(mid):
    m = get_menu_item(mid)
    if m["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE menu item can be delisted.")
    m["status"] = "DELISTED"
    touch(m)
    return object_response(serialize.menu_item(m))
