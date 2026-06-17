"""MaterialSku endpoints (PRD §3.1).

SKU: sku_code (unique), description, unit_price_cents, taxable (default true).
"""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_bool,
                     require_fields, require_nonneg_int, require_string,
                     serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("material_skus", __name__)


@bp.post("/v1/material-skus")
def create_sku():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["sku_code", "description", "unit_price_cents"])
    require_string(body["sku_code"], "sku_code")
    require_string(body["description"], "description")
    require_nonneg_int(body["unit_price_cents"], "unit_price_cents")

    taxable = body.get("taxable", True)
    if taxable is None:
        taxable = True
    require_bool(taxable, "taxable")

    # sku_code unique across SKUs (ERR_DUPLICATE).
    for s in db.material_skus.values():
        if s["sku_code"] == body["sku_code"]:
            raise err("ERR_DUPLICATE", "A SKU with this sku_code already exists")

    record = {
        "sku_code": body["sku_code"],
        "description": body["description"],
        "unit_price_cents": body["unit_price_cents"],
        "taxable": taxable,
    }
    db.stamp_new(record)
    db.material_skus[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/material-skus/<sku_id>")
def get_sku(sku_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    record = db.material_skus.get(sku_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "SKU not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/material-skus")
def list_skus():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    limit, offset = parse_pagination()
    sku_code = request.args.get("sku_code")

    items = list(db.material_skus.values())
    if sku_code is not None:
        items = [s for s in items if s["sku_code"] == sku_code]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)
