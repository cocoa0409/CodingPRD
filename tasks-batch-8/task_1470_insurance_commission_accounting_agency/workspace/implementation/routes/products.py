"""Product endpoints."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import LINES_OF_BUSINESS, new_resource, ser_product
from util import apply_filters, as_enum, as_str, get_body, req, respond_list

bp = Blueprint("products", __name__)


@bp.post("/agency/products")
def create_product():
    auth(ADMIN_ACCT)
    data = get_body()
    # Priority 3: body FK reference.
    carrier_id = data.get("carrier_id")
    if isinstance(carrier_id, str) and carrier_id not in DB["carriers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "carrier_id does not reference an existing carrier")
    # Priority 8: product_code unique per carrier.
    code = data.get("product_code")
    if isinstance(carrier_id, str) and isinstance(code, str) and any(
        p["carrier_id"] == carrier_id and p["product_code"] == code
        for p in DB["products"].values()
    ):
        raise ApiError(
            "ERR_PRODUCT_CODE_EXISTS", 409, "product_code already in use for this carrier"
        )
    # Priority 10: shape.
    carrier_id = as_str(req(data, "carrier_id"), "carrier_id")
    product_code = as_str(req(data, "product_code"), "product_code")
    name = as_str(req(data, "name"), "name")
    lob = as_enum(req(data, "line_of_business"), "line_of_business", LINES_OF_BUSINESS)
    p = new_resource({
        "carrier_id": carrier_id,
        "product_code": product_code,
        "name": name,
        "line_of_business": lob,
    })
    DB["products"][p["id"]] = p
    return ok(ser_product(p), 201)


@bp.get("/agency/products")
def list_products():
    auth(ALL_ROLES)
    items = apply_filters(DB["products"].values(), {"carrier_id": "carrier_id"})
    return respond_list(items, ser_product)


@bp.get("/agency/products/<productId>")
def get_product(productId):
    auth(ALL_ROLES)
    p = DB["products"].get(productId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Product not found")
    return ok(ser_product(p))
