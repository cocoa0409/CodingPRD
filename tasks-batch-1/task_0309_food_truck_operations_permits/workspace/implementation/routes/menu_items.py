"""MenuItem endpoints (PRD §3.5)."""

from flask import request, Blueprint

import errors
import serializers
from db import db
from errors import err
from helpers import get_body, require_str, require_fk, require_int, get_pagination, paginate
from lookups import get_menu_item, get_truck
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("menu_items", __name__)

WRITE_ROLES = {"OperatorTruck", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}


@bp.post("/menu-items")
def create_menu_item():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    truck_id = require_fk(body, "truck_id")
    get_truck(truck_id)
    require_truck_ownership(user_id, role, truck_id)
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    unit_price_cents = require_int(body, "unit_price_cents", minimum=0)
    par_units = require_int(body, "par_units", minimum=0)
    rec = db.new_record({
        "truck_id": truck_id,
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price_cents,
        "par_units": par_units,
        "status": "AVAILABLE",
    })
    db.menu_items[rec["id"]] = rec
    return ok_object(serializers.menu_item(rec), 201)


@bp.get("/menu-items")
def list_menu_items():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.menu_items.values())
    truck_id = request.args.get("truck_id")
    if truck_id is not None:
        records = [r for r in records if r["truck_id"] == truck_id]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.menu_item(r) for r in window], limit, offset, total)


@bp.get("/menu-items/<menu_item_id>")
def get_menu_item_route(menu_item_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_menu_item(menu_item_id)
    return ok_object(serializers.menu_item(rec))


@bp.post("/menu-items/<menu_item_id>/unlist")
def unlist_menu_item(menu_item_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_menu_item(menu_item_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    if rec["status"] != "AVAILABLE":
        raise err(errors.ERR_MENU_ITEM_UNLISTED, "Menu item is already UNLISTED")
    rec["status"] = "UNLISTED"
    db.touch(rec)
    return ok_object(serializers.menu_item(rec))
