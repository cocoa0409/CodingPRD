"""Product catalog endpoints (PRD 3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import ALL_ROLES, PLATFORM_ADMIN, body, endpoint
from response import object_response
from routes.common import FK_MARKET, filtered, list_page, path_lookup, resolve_fks
from services import serialize
from util import (as_bool, as_enum, as_int, as_ratio, as_str, get_required)

bp = Blueprint("products", __name__)

PRODUCT_STATUSES = ("ACTIVE", "DISCONTINUED")
DEFAULT_MARGIN_FLOOR_PCT = 0.20
DEFAULT_MAP_FLOOR_CENTS = 0
DEFAULT_INDEX_WEIGHT_BP = 10000


@bp.post("/products")
@endpoint([PLATFORM_ADMIN])
def create_product(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_MARKET])

    market = fks["market_id"]
    if market is None:
        get_required(payload, "market_id")
    sku = as_str(get_required(payload, "sku"), "sku", min_len=1)
    category_code = as_str(get_required(payload, "category_code"),
                           "category_code", min_len=1)
    brand = as_str(get_required(payload, "brand"), "brand", min_len=1)
    own_price_cents = as_int(get_required(payload, "own_price_cents"),
                             "own_price_cents", gt=0)
    unit_cost_cents = as_int(get_required(payload, "unit_cost_cents"),
                             "unit_cost_cents", gt=0)

    margin_floor_pct = DEFAULT_MARGIN_FLOOR_PCT
    if payload.get("margin_floor_pct") is not None:
        margin_floor_pct = as_ratio(payload["margin_floor_pct"], "margin_floor_pct",
                                    min_inclusive=0, max_exclusive=1)
    map_floor_cents = DEFAULT_MAP_FLOOR_CENTS
    if payload.get("map_floor_cents") is not None:
        map_floor_cents = as_int(payload["map_floor_cents"], "map_floor_cents",
                                 minimum=0)
    brand_repricing_restricted = False
    if payload.get("brand_repricing_restricted") is not None:
        brand_repricing_restricted = as_bool(payload["brand_repricing_restricted"],
                                             "brand_repricing_restricted")
    index_weight_bp = DEFAULT_INDEX_WEIGHT_BP
    if payload.get("index_weight_bp") is not None:
        index_weight_bp = as_int(payload["index_weight_bp"], "index_weight_bp", gt=0)
    status = "ACTIVE"
    if payload.get("status") is not None:
        status = as_enum(as_str(payload["status"], "status", min_len=1), "status",
                         PRODUCT_STATUSES)

    for existing in db.products.values():
        if existing["market_id"] == market["id"] and existing["sku"] == sku:
            raise err("ERR_DUPLICATE_RESOURCE",
                      "sku '%s' is already used in this market." % sku)

    record = db.new_record()
    record.update({
        "market_id": market["id"],
        "sku": sku,
        "category_code": category_code,
        "brand": brand,
        "own_price_cents": own_price_cents,
        "unit_cost_cents": unit_cost_cents,
        "margin_floor_pct": margin_floor_pct,
        "map_floor_cents": map_floor_cents,
        "brand_repricing_restricted": brand_repricing_restricted,
        "index_weight_bp": index_weight_bp,
        "status": status,
        "last_price_change_at": None,
    })
    db.products[record["id"]] = record
    return object_response(serialize.product(record), 201)


@bp.get("/products/<product_id>")
@endpoint(ALL_ROLES)
def read_product(user_id, role, product_id):
    product = path_lookup("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    return object_response(serialize.product(product))


@bp.get("/products")
@endpoint(ALL_ROLES)
def list_products(user_id, role):
    rows = filtered(db.ordered(db.products), request.args,
                    [("market_id", "market_id"),
                     ("category_code", "category_code"),
                     ("brand", "brand"), ("status", "status")])
    return list_page(rows, serialize.product)
