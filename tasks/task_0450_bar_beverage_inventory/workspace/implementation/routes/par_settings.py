"""Par setting endpoints (PRD §2.8)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create, touch
from errors import ApiError, ERR_INVALID_PAR
from middleware import require_roles
from money import D, to_number
from response import object_response, array_response
from routes.lookup import get_product
from services.product import recompute_needs_reorder_only
from validate import (get_json_body, require, as_number, parse_pagination, paginate)

bp = Blueprint("par_settings", __name__)


@bp.route("/par-settings", methods=["POST"])
@require_roles("InventoryManager")
def create_par_setting():
    body = get_json_body()
    product_id = require(body, "product_id")
    par_level_units = as_number(require(body, "par_level_units"), "par_level_units")
    reorder_point_units = as_number(require(body, "reorder_point_units"), "reorder_point_units")

    # existence (404) before business rules
    product = get_product(product_id)

    # ERR_INVALID_PAR (422): par_level > 0, reorder_point >= 0, reorder_point <= par_level
    pl = D(par_level_units)
    rp = D(reorder_point_units)
    if not (pl > 0) or not (rp >= 0) or not (rp <= pl):
        raise ApiError(ERR_INVALID_PAR, 422,
                       "reorder_point_units must be in [0, par_level_units] and par_level_units > 0.")

    # supersede any prior ACTIVE par for this product
    for ps in db.par_settings.values():
        if ps["product_id"] == product_id and ps["status"] == "ACTIVE":
            ps["status"] = "SUPERSEDED"
            touch(ps)

    record = {
        "product_id": product_id,
        "par_level_units": to_number(pl),
        "reorder_point_units": to_number(rp),
        "status": "ACTIVE",
    }
    stamp_create(record)
    db.par_settings[record["id"]] = record

    # referenced product recomputes needs_reorder against the new ACTIVE par
    recompute_needs_reorder_only(product)

    return object_response(serialize.par_setting(record), 201)


@bp.route("/par-settings", methods=["GET"])
@require_roles("InventoryManager", "PurchasingAgent")
def list_par_settings():
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = list(db.par_settings.values())
    if product_id is not None:
        items = [r for r in items if r["product_id"] == product_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.par_setting(r) for r in page], limit, offset, total)
