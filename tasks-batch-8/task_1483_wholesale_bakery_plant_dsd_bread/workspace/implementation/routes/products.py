"""Product endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, req_number, req_enum, make_entity, lookup,
    list_response, public,
)
from response import success_object
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("products", __name__)

ALLERGEN_CLASSES = {"NONE", "SESAME", "TREE_NUT", "PEANUT"}


@bp.route("/bakery/products", methods=["POST"])
def create_product():
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    data = body()
    plant_id = req_string(data, "plant_id")
    lookup(DB.plants, plant_id, "plant")
    sku = req_string(data, "sku")
    name = req_string(data, "name")
    allergen_class = req_enum(data, "allergen_class", ALLERGEN_CLASSES)
    unit_weight_g = req_int(data, "unit_weight_g", min_value=1)
    shelf_life_hours = req_int(data, "shelf_life_hours", min_value=1)
    base_price_cents = req_int(data, "base_price_cents", min_value=1)
    flour_share_pct = req_number(data, "flour_share_pct", min_value=0, allow_zero=True)
    butter_share_pct = req_number(data, "butter_share_pct", min_value=0, allow_zero=True)
    if flour_share_pct > 1:
        raise ApiError(ERR_INVALID_REQUEST, "flour_share_pct must be <= 1", 400)
    if butter_share_pct > 1:
        raise ApiError(ERR_INVALID_REQUEST, "butter_share_pct must be <= 1", 400)
    batch_capacity_units = req_int(data, "batch_capacity_units", min_value=1)

    # sku unique within plant
    for p in DB.products.values():
        if p.get("plant_id") == plant_id and p.get("sku") == sku:
            raise ApiError(ERR_INVALID_REQUEST, f"sku {sku} already exists in plant", 400)

    product = make_entity({
        "plant_id": plant_id,
        "sku": sku,
        "name": name,
        "allergen_class": allergen_class,
        "unit_weight_g": unit_weight_g,
        "shelf_life_hours": shelf_life_hours,
        "base_price_cents": base_price_cents,
        "flour_share_pct": flour_share_pct,
        "butter_share_pct": butter_share_pct,
        "batch_capacity_units": batch_capacity_units,
        "current_surcharge_cents": 0,
    })
    DB.products[product["id"]] = product
    return success_object(public(product), status=201)


@bp.route("/bakery/products/<pid>", methods=["GET"])
def get_product(pid):
    get_auth()
    product = lookup(DB.products, pid, "product")
    return success_object(public(product))


@bp.route("/bakery/products", methods=["GET"])
def list_products():
    get_auth()
    filters = {"plant_id": request.args.get("plant_id")}
    return list_response(list(DB.products.values()), filters)
