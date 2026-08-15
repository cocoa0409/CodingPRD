"""StructureModel endpoints."""

from flask import Blueprint

import db
from errors import invalid_request
from middleware import authenticate, require_roles
from response import success_object
from services.common import new_id, get_body, require, get_model, check_enum, is_str

bp = Blueprint("models", __name__)


@bp.post("/api/models")
def create_model():
    authenticate()
    require_roles("SalesRep")
    body = get_body()
    row = {"id": new_id()}
    row["name"] = require(body, "name", "str")
    row["sku"] = require(body, "sku", "str")
    row["min_width_ft"] = require(body, "min_width_ft", "num")
    row["max_width_ft"] = require(body, "max_width_ft", "num")
    row["min_depth_ft"] = require(body, "min_depth_ft", "num")
    row["max_depth_ft"] = require(body, "max_depth_ft", "num")
    row["wall_height_ft"] = require(body, "wall_height_ft", "num")
    modes = require(body, "supported_delivery_modes", "array")
    for m in modes:
        check_enum(m, {"PRE_BUILT", "ON_SITE_BUILD"}, "supported_delivery_modes")
    row["supported_delivery_modes"] = list(modes)
    row["base_price_cents"] = require(body, "base_price_cents", "int")
    row["overage_rate_tier1_cents"] = require(body, "overage_rate_tier1_cents", "int")
    row["overage_rate_tier2_cents"] = require(body, "overage_rate_tier2_cents", "int")
    now = db.now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    db.models[row["id"]] = row
    return success_object(row, 201)


@bp.get("/api/models/<mid>")
def read_model(mid):
    authenticate()
    require_roles("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
                  "FinanceManager", "OperationsAdmin")
    return success_object(get_model(mid))
