from flask import Blueprint, request

from db import db
from errors import not_found
from helpers import get_body, list_query, new_entity, ser_product
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object

bp = Blueprint("products", __name__)


@bp.post("/rack/products")
def create_product():
    require_roles(["PlatformAdmin"])
    body = get_body()
    p = new_entity({
        "product_code": body.get("product_code"),
        "display_name": body.get("display_name"),
        "product_family": body.get("product_family"),
        "is_brandable": bool(body.get("is_brandable", False)),
    })
    db.products[p["id"]] = p
    return success_object(ser_product(p), 201)


@bp.get("/rack/products/<productId>")
def get_product(productId):
    require_roles(ALL_ROLES)
    p = db.products.get(productId)
    if p is None:
        raise not_found("Product {} does not exist".format(productId))
    return success_object(ser_product(p))


@bp.get("/rack/products")
def list_products():
    require_roles(ALL_ROLES)
    page, total, limit, offset = list_query(
        db.products.values(), request.args, ["product_family"]
    )
    return success_list([ser_product(p) for p in page], total, limit, offset)
