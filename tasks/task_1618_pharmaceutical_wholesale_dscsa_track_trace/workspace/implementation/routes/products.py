"""Products (PRD §3.2): NDC master data and shortage declaration."""
from flask import Blueprint

import db
import errors
from db import store
from errors import ApiError
from middleware import endpoint, ALL_ROLES
from response import ok, created, Paginator
from validation import (get_body, req_str, req_int, req_bool, opt_bool,
                        opt_int, path_entity)

bp = Blueprint("products", __name__)


@bp.route("/wholesale/products", methods=["POST"])
@endpoint(["OrderManager"])
def create_product():
    body = get_body()
    ndc = req_str(body, "ndc")
    product_name = req_str(body, "product_name")
    is_controlled = req_bool(body, "is_controlled")
    is_cold_chain = req_bool(body, "is_cold_chain")
    wac = req_int(body, "wholesale_acquisition_cost_cents", minimum=0)
    is_340b = opt_bool(body, "is_340b_contracted", default=False)
    contract_price = opt_int(body, "contract_340b_price_cents", default=None, minimum=0)
    if is_340b and contract_price is None:
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "contract_340b_price_cents is required when is_340b_contracted is true")
    if any(p["ndc"] == ndc for p in store.products.values()):
        raise ApiError(errors.ERR_DUPLICATE_UNIQUE_FIELD[0], errors.ERR_DUPLICATE_UNIQUE_FIELD[1],
                       "ndc must be unique across Products")
    product = {
        "id": db.new_id(),
        "ndc": ndc,
        "product_name": product_name,
        "is_controlled": is_controlled,
        "is_cold_chain": is_cold_chain,
        "wholesale_acquisition_cost_cents": wac,
        "is_340b_contracted": is_340b,
        "contract_340b_price_cents": contract_price if is_340b else None,
        "shortage_status": "NORMAL",
    }
    db.new_common(product)
    store.products[product["id"]] = product
    return created(product)


@bp.route("/wholesale/products", methods=["GET"])
@endpoint(ALL_ROLES)
def list_products():
    pg = Paginator()
    rows = list(store.products.values())
    rows = pg.filter(rows, "shortage_status")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.route("/wholesale/products/<productId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_product(productId):
    product = path_entity(store.products, productId, "Product")
    return ok(product)


@bp.route("/wholesale/products/<productId>/declare-shortage", methods=["POST"])
@endpoint(["OrderManager"])
def declare_shortage(productId):
    product = path_entity(store.products, productId, "Product")
    product["shortage_status"] = "SHORTAGE"
    db.touch(product)
    return ok(product)
