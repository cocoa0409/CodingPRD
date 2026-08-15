"""CatalogItem endpoints (PRD §3.2)."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

import db
from db import new_record, sort_key, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_DUPLICATE_SKU,
)
from middleware import ROLES, atomic, require_roles
from response import success_list, success_object
from serializers import ser_catalog_item
from services.waterfall import run_backorder_waterfall
from util import get_json_body, paginate, require_int, require_number, require_string

bp = Blueprint("catalog", __name__, url_prefix="/distributor")

_REEL_FIELDS = ("reel_length_ft", "min_cut_ft", "cut_charge_cents")


@bp.post("/catalog-items")
@require_roles("WarehouseManager")
@atomic
def create_catalog_item():
    body = get_json_body()
    sku = require_string(body, "sku")
    manufacturer_name = require_string(body, "manufacturer_name")
    sell_uom = require_string(body, "sell_uom")
    if sell_uom not in ("EA", "FOOT"):
        raise_err(ERR_INVALID_REQUEST, "sell_uom must be EA or FOOT")
    list_price = require_number(body, "list_price_cents")
    if list_price < 0:
        raise_err(ERR_INVALID_REQUEST, "list_price_cents must be >= 0")

    reel_length_ft = None
    min_cut_ft = None
    cut_charge_cents = None
    if sell_uom == "FOOT":
        reel_length_ft = require_int(body, "reel_length_ft")
        min_cut_ft = require_int(body, "min_cut_ft")
        cut_charge_cents = require_int(body, "cut_charge_cents")
        if reel_length_ft <= 0:
            raise_err(ERR_INVALID_REQUEST, "reel_length_ft must be > 0")
        if min_cut_ft <= 0:
            raise_err(ERR_INVALID_REQUEST, "min_cut_ft must be > 0")
        if cut_charge_cents < 0:
            raise_err(ERR_INVALID_REQUEST, "cut_charge_cents must be >= 0")
    else:
        for field in _REEL_FIELDS:
            if field in body and body[field] is not None:
                raise_err(ERR_INVALID_REQUEST, f"{field} is forbidden when sell_uom is EA")

    if any(i["sku"] == sku for i in db.catalog_items.values()):
        raise_err(ERR_DUPLICATE_SKU, "Catalog item sku already exists")

    item = new_record(
        {
            "sku": sku,
            "manufacturer_name": manufacturer_name,
            "sell_uom": sell_uom,
            "list_price_cents": list_price,
            "reel_length_ft": reel_length_ft,
            "min_cut_ft": min_cut_ft,
            "cut_charge_cents": cut_charge_cents,
            "stock_on_hand": Decimal(0),
            "stock_allocated": Decimal(0),
        }
    )
    db.catalog_items[item["id"]] = item
    return success_object(ser_catalog_item(item), 201)


@bp.get("/catalog-items")
@require_roles(*ROLES)
def list_catalog_items():
    manufacturer = _query_arg("manufacturer_name")
    items = sorted(db.catalog_items.values(), key=sort_key)
    if manufacturer is not None:
        items = [i for i in items if i["manufacturer_name"] == manufacturer]
    page, limit, offset, total = paginate(items)
    return success_list([ser_catalog_item(i) for i in page], limit, offset, total)


def _query_arg(name: str):
    from flask import request

    value = request.args.get(name)
    return value if value not in (None, "") else None


@bp.get("/catalog-items/<item_id>")
@require_roles(*ROLES)
def get_catalog_item(item_id: str):
    item = db.catalog_items.get(item_id)
    if item is None:
        raise_err(ERR_CATALOG_ITEM_NOT_FOUND, "No catalog item with the given id")
    return success_object(ser_catalog_item(item))


@bp.post("/catalog-items/<item_id>/stock-receipts")
@require_roles("WarehouseManager")
@atomic
def receive_stock(item_id: str):
    body = get_json_body()
    qty = require_number(body, "qty")
    if qty <= 0:
        raise_err(ERR_INVALID_REQUEST, "qty must be > 0")
    item = db.catalog_items.get(item_id)
    if item is None:
        raise_err(ERR_CATALOG_ITEM_NOT_FOUND, "No catalog item with the given id")
    item["stock_on_hand"] += qty
    touch(item)
    run_backorder_waterfall(item)
    return success_object(ser_catalog_item(item), 201)
