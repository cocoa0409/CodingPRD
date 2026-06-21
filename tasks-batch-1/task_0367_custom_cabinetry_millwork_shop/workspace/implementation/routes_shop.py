"""Shop, clock, material, machine routes."""
from flask import Blueprint

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_int, require_enum,
                     parse_datetime, parse_pagination, paginate, sort_by_created)
from models import (_base_record, touch, serialize_shop, serialize_material,
                    serialize_machine, material_reserved_sheets)
from lookups import get_shop, get_material_in_shop, get_machine_in_shop

bp = Blueprint("shop", __name__)


# --------------------------------------------------------------------------
# Shop
# --------------------------------------------------------------------------
@bp.route("/shops", methods=["POST"])
def create_shop():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin"})
    body = get_body()
    name = require_str(body, "name")
    currency = require_str(body, "currency", required=False) or "USD"
    tax_rate_bps = require_int(body, "tax_rate_bps", required=False, default=0, minimum=0, maximum=2000)
    deposit_pct_bps = require_int(body, "deposit_pct_bps", required=False, default=3000, minimum=0, maximum=10000)
    retainage_pct_bps = require_int(body, "retainage_pct_bps", required=False, default=1000, minimum=0, maximum=5000)
    rush_surcharge_bps = require_int(body, "rush_surcharge_bps", required=False, default=1500, minimum=0, maximum=5000)
    max_installs_per_day = require_int(body, "max_installs_per_day", required=False, default=2, minimum=1)
    change_order_buffer_pct_bps = require_int(body, "change_order_buffer_pct_bps", required=False, default=0, minimum=0)

    rec = _base_record()
    rec.update({
        "name": name,
        "currency": currency,
        "tax_rate_bps": tax_rate_bps,
        "deposit_pct_bps": deposit_pct_bps,
        "retainage_pct_bps": retainage_pct_bps,
        "rush_surcharge_bps": rush_surcharge_bps,
        "max_installs_per_day": max_installs_per_day,
        "change_order_buffer_pct_bps": change_order_buffer_pct_bps,
        "current_utc": None,
    })
    store.shops[rec["id"]] = rec
    return success(serialize_shop(rec), 201)


@bp.route("/shops/<shop_id>", methods=["GET"])
def get_shop_route(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Installer", "Customer"})
    s = get_shop(shop_id)
    return success(serialize_shop(s), 200)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"ShopAdmin"})
    body = get_body()
    shop_id = require_str(body, "shop_id")
    to_iso = parse_datetime(body, "to_iso8601")
    s = get_shop(shop_id)
    # Store as canonical ISO string
    s["current_utc"] = body["to_iso8601"]
    touch(s)
    return success(serialize_shop(s), 200)


# --------------------------------------------------------------------------
# Material
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/materials", methods=["POST"])
def create_material(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    get_shop(shop_id)
    body = get_body()
    sku = require_str(body, "sku")
    sheet_area_mm2 = require_int(body, "sheet_area_mm2", minimum=1)
    sheet_price_cents = require_int(body, "sheet_price_cents", minimum=0)

    rec = _base_record()
    rec.update({
        "shop_id": shop_id,
        "sku": sku,
        "sheet_area_mm2": sheet_area_mm2,
        "sheet_price_cents": sheet_price_cents,
        "on_hand_sheets": 0,
    })
    store.materials[rec["id"]] = rec
    return success(serialize_material(rec), 201)


@bp.route("/shops/<shop_id>/materials/<material_id>", methods=["GET"])
def get_material(shop_id, material_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    m = get_material_in_shop(shop_id, material_id)
    return success(serialize_material(m), 200)


@bp.route("/shops/<shop_id>/materials", methods=["GET"])
def list_materials(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_shop(shop_id)
    limit, offset = parse_pagination()
    items = [m for m in store.materials.values() if m["shop_id"] == shop_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_material(m) for m in page], limit, offset, total)


@bp.route("/shops/<shop_id>/materials/<material_id>/restock", methods=["POST"])
def restock_material(shop_id, material_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    m = get_material_in_shop(shop_id, material_id)
    body = get_body()
    sheets = require_int(body, "sheets", minimum=1)
    m["on_hand_sheets"] += sheets
    touch(m)
    return success(serialize_material(m), 200)


# --------------------------------------------------------------------------
# Machine
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/machines", methods=["POST"])
def create_machine(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    get_shop(shop_id)
    body = get_body()
    name = require_str(body, "name")
    changeover_buffer_min = require_int(body, "changeover_buffer_min", required=False, default=30, minimum=0)
    status = require_enum(body, "status", {"ONLINE", "OFFLINE"}, required=False, default="ONLINE")

    rec = _base_record()
    rec.update({
        "shop_id": shop_id,
        "name": name,
        "changeover_buffer_min": changeover_buffer_min,
        "status": status,
    })
    store.machines[rec["id"]] = rec
    return success(serialize_machine(rec), 201)


@bp.route("/shops/<shop_id>/machines/<machine_id>", methods=["GET"])
def get_machine(shop_id, machine_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    m = get_machine_in_shop(shop_id, machine_id)
    return success(serialize_machine(m), 200)


@bp.route("/shops/<shop_id>/machines/<machine_id>", methods=["PATCH"])
def update_machine(shop_id, machine_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    m = get_machine_in_shop(shop_id, machine_id)
    body = get_body()
    status = require_enum(body, "status", {"ONLINE", "OFFLINE"})
    m["status"] = status
    touch(m)
    return success(serialize_machine(m), 200)
