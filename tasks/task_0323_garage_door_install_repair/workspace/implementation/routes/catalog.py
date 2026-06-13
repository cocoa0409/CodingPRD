"""Catalog & configuration routes: door-models, opener-models, parts, equipment-units.

PRD §3.1. DoorModel/OpenerModel are immutable reference data (no version /
updated_at, PRD §2.4).
"""
from flask import Blueprint

import db
import errors
import lookup
import serialize
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("catalog", __name__)

PART_CATEGORIES = {"SPRING", "CABLE", "PANEL", "ROLLER", "SENSOR"}


def _check_unique_sku(collection, sku):
    for ent in collection.values():
        if ent["sku"] == sku:
            raise errors.err(errors.ERR_DUPLICATE, "sku already exists")


# ----- Door models -----
@bp.route("/door-models", methods=["POST"])
def create_door_model():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["sku", "name", "width_in", "height_in",
                               "list_price_cents", "install_labor_minutes"])
    sku = util.require_string(body, "sku")
    name = util.require_string(body, "name")
    width_in = util.require_int(body, "width_in")
    height_in = util.require_int(body, "height_in")
    list_price_cents = util.require_int(body, "list_price_cents")
    install_labor_minutes = util.require_int(body, "install_labor_minutes")
    requires_lift = util.optional_bool(body, "requires_lift", False)
    _check_unique_sku(db.door_models, sku)
    d = {
        "sku": sku, "name": name, "width_in": width_in, "height_in": height_in,
        "list_price_cents": list_price_cents,
        "install_labor_minutes": install_labor_minutes,
        "requires_lift": requires_lift,
    }
    db.stamp_create(d, common_fields=False, versioned=False)
    db.door_models[d["id"]] = d
    return success(serialize.door_model(d), status=201)


@bp.route("/door-models/<id>", methods=["GET"])
def get_door_model(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer", "Dispatcher", "Technician"])
    d = lookup.door_model(id)
    return success(serialize.door_model(d))


# ----- Opener models -----
@bp.route("/opener-models", methods=["POST"])
def create_opener_model():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["sku", "name", "horsepower",
                               "list_price_cents", "install_labor_minutes"])
    sku = util.require_string(body, "sku")
    name = util.require_string(body, "name")
    horsepower = util.optional_number(body, "horsepower", None)
    if horsepower is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "horsepower required")
    list_price_cents = util.require_int(body, "list_price_cents")
    install_labor_minutes = util.require_int(body, "install_labor_minutes")
    _check_unique_sku(db.opener_models, sku)
    o = {
        "sku": sku, "name": name, "horsepower": horsepower,
        "list_price_cents": list_price_cents,
        "install_labor_minutes": install_labor_minutes,
    }
    db.stamp_create(o, common_fields=False, versioned=False)
    db.opener_models[o["id"]] = o
    return success(serialize.opener_model(o), status=201)


@bp.route("/opener-models/<id>", methods=["GET"])
def get_opener_model(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer", "Dispatcher", "Technician"])
    o = lookup.opener_model(id)
    return success(serialize.opener_model(o))


# ----- Parts -----
@bp.route("/parts", methods=["POST"])
def create_part():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["sku", "category", "unit_price_cents", "on_hand_qty"])
    sku = util.require_string(body, "sku")
    category = util.require_enum(body, "category", PART_CATEGORIES)
    unit_price_cents = util.require_int(body, "unit_price_cents")
    markup_pct = util.optional_number(body, "markup_pct", 0.35)
    on_hand_qty = util.require_int(body, "on_hand_qty")
    _check_unique_sku(db.parts, sku)
    p = {
        "sku": sku, "category": category, "unit_price_cents": unit_price_cents,
        "markup_pct": markup_pct, "on_hand_qty": on_hand_qty,
    }
    db.stamp_create(p, common_fields=True, versioned=True)
    db.parts[p["id"]] = p
    return success(serialize.part(p), status=201)


@bp.route("/parts/<id>", methods=["GET"])
def get_part(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer", "Dispatcher", "Technician"])
    p = lookup.part(id)
    return success(serialize.part(p))


# ----- Equipment units -----
@bp.route("/equipment-units", methods=["POST"])
def create_equipment_unit():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["name"])
    name = util.require_string(body, "name")
    concurrent_capacity = util.optional_int(body, "concurrent_capacity", 1)
    e = {"name": name, "concurrent_capacity": concurrent_capacity}
    db.stamp_create(e, common_fields=True, versioned=True)
    db.equipment_units[e["id"]] = e
    return success(serialize.equipment_unit(e), status=201)
