"""ThriftSale endpoints."""

import math

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, make_entity, touch, lookup, list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_THRIFT_PRICE_BELOW_FLOOR,
    ERR_THRIFT_STOCK_UNAVAILABLE,
)
from services.calculations import thrift_pool_available

bp = Blueprint("thrift_sales", __name__)


@bp.route("/bakery/thrift-sales", methods=["POST"])
def create_sale():
    _, role = get_auth()
    require_role(role, {"ThriftClerk"})
    data = body()
    product_id = req_string(data, "product_id")
    product = lookup(DB.products, product_id, "product")
    units = req_int(data, "units", min_value=1)
    unit_price_cents = req_int(data, "unit_price_cents", min_value=1)

    floor = math.ceil(int(product["base_price_cents"]) * 0.5)
    if unit_price_cents < floor:
        raise ApiError(ERR_THRIFT_PRICE_BELOW_FLOOR, "unit_price_cents below thrift floor", 409)

    available = thrift_pool_available(product_id)
    if units > available:
        raise ApiError(ERR_THRIFT_STOCK_UNAVAILABLE, "Insufficient thrift stock", 409)

    sale = make_entity({
        "plant_id": product["plant_id"],
        "product_id": product_id,
        "units": units,
        "unit_price_cents": unit_price_cents,
        "total_cents": units * unit_price_cents,
        "status": "RECORDED",
    })
    DB.thrift_sales[sale["id"]] = sale
    return success_object(public(sale), status=201)


@bp.route("/bakery/thrift-sales/<sid>", methods=["GET"])
def get_sale(sid):
    get_auth()
    sale = lookup(DB.thrift_sales, sid, "thrift sale")
    return success_object(public(sale))


@bp.route("/bakery/thrift-sales", methods=["GET"])
def list_sales():
    get_auth()
    filters = {
        "plant_id": request.args.get("plant_id"),
        "product_id": request.args.get("product_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB.thrift_sales.values()), filters)


@bp.route("/bakery/thrift-sales/<sid>/void", methods=["POST"])
def void_sale(sid):
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    sale = lookup(DB.thrift_sales, sid, "thrift sale")
    if sale.get("status") != "RECORDED":
        raise ApiError(ERR_INVALID_STATE, "Sale is not RECORDED", 409)
    sale["status"] = "VOIDED"
    touch(sale)
    return success_object(public(sale))
