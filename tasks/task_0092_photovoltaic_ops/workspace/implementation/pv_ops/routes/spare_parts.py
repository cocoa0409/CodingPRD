"""Spare part endpoints."""
from __future__ import annotations

from flask import Blueprint, current_app

from pv_ops.auth import require_roles
from pv_ops.errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_UNIQUE_VIOLATION,
    ERR_VALIDATION,
    ERR_VERSION_CONFLICT,
)
from pv_ops.responses import created, success
from pv_ops.services import serializers
from pv_ops.utils import (
    get_body,
    opt_int,
    require_int,
    require_number,
    require_str,
)


bp = Blueprint("spare_parts", __name__)


@bp.route("/pv-ops/spare-parts", methods=["POST"])
@require_roles("PlatformAdmin")
def create_spare_part():
    body = get_body()
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    stock = require_int(body, "stock_on_hand", ge=0)
    unit_cost = require_number(body, "unit_cost_cny", ge=0.0)
    store = current_app.extensions["store"]
    with store.lock:
        for p in store.spare_parts.values():
            if p.get("sku") == sku:
                raise APIError(ERR_UNIQUE_VIOLATION, 409, "Spare part SKU already exists")
        row = {
            "sku": sku,
            "name": name,
            "stock_on_hand": stock,
            "reserved_qty": 0,
            "unit_cost_cny": float(unit_cost),
        }
        store.insert_common(row)
        store.spare_parts[row["id"]] = row
        return created(serializers.spare_part_view(row))


@bp.route("/pv-ops/spare-parts/<part_id>", methods=["PATCH"])
@require_roles("PlatformAdmin")
def patch_spare_part(part_id: str):
    body = get_body()
    store = current_app.extensions["store"]
    with store.lock:
        part = store.spare_parts.get(part_id)
        if not part:
            raise APIError(ERR_NOT_FOUND, 404, "Spare part not found")
        version = opt_int(body, "version")
        if version is not None and version != part.get("version"):
            raise APIError(ERR_VERSION_CONFLICT, 409, "Version mismatch")
        if "stock_on_hand" in body and body["stock_on_hand"] is not None:
            new_stock = require_int(body, "stock_on_hand", ge=0)
            part["stock_on_hand"] = new_stock
        store.bump(part)
        return success(serializers.spare_part_view(part))
