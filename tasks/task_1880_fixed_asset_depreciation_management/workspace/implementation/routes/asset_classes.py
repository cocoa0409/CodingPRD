"""AssetClass endpoints."""
from flask import Blueprint
import db
import errors
from db import new_id, now_iso
from middleware import (require_roles, get_body, require_string, require_int,
                        require_enum, require_bool)
from response import success_object
from services.serializers import asset_class_view

bp = Blueprint("asset_classes", __name__)

BOOK_METHODS = {"STRAIGHT_LINE", "DOUBLE_DECLINING"}
TAX_METHODS = {"MACRS_5YR", "MACRS_7YR", "TAX_STRAIGHT_LINE"}
ALL_ROLES = ("AssetAccountant", "Controller", "InventoryClerk", "TaxAnalyst")


@bp.route("/asset-classes", methods=["POST"])
def create_asset_class():
    require_roles("Controller")
    data = get_body()
    class_code = require_string(data, "class_code")
    name = require_string(data, "name")
    threshold = require_int(data, "capitalization_threshold_cents")
    default_life = require_int(data, "default_useful_life_months")
    book_method = require_enum(data, "book_method", BOOK_METHODS)
    tax_method = require_enum(data, "tax_method", TAX_METHODS)
    bonus_allowed = require_bool(data, "bonus_depreciation_allowed")
    if default_life <= 0:
        raise errors.invalid_request("default_useful_life_months must be > 0")
    # uniqueness
    for rec in db.asset_classes.values():
        if rec["class_code"] == class_code:
            raise errors.duplicate_tag("class_code already exists")
    ts = now_iso()
    rec = {
        "id": new_id(),
        "class_code": class_code,
        "name": name,
        "capitalization_threshold_cents": threshold,
        "default_useful_life_months": default_life,
        "book_method": book_method,
        "tax_method": tax_method,
        "bonus_depreciation_allowed": bonus_allowed,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.asset_classes[rec["id"]] = rec
    return success_object(asset_class_view(rec), 201)


@bp.route("/asset-classes/<cid>", methods=["GET"])
def get_asset_class(cid):
    require_roles(*ALL_ROLES)
    rec = db.asset_classes.get(cid)
    if rec is None:
        raise errors.not_found("Asset class not found")
    return success_object(asset_class_view(rec))
