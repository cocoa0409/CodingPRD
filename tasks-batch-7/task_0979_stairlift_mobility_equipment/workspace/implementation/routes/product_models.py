"""ProductModel endpoints."""

from flask import Blueprint, request

import db
from errors import err_not_found, err_invalid_request
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import stamp_lean, serialize

bp = Blueprint("product_models", __name__)

READ_ROLES = ("PlatformAdmin", "SalesRep", "Assessor", "AssessmentReviewer",
              "InstallCoordinator", "InventoryManager")


@bp.post("/stairlift-ops/product-models")
def create_product_model():
    require_role("PlatformAdmin")
    body = get_json_body(["model_code", "kind", "supports_curved",
                          "supports_outdoor", "min_stair_width_mm",
                          "base_purchase_price_cents",
                          "monthly_rental_rate_cents", "install_labor_hours"])
    if not isinstance(body["model_code"], str):
        raise err_invalid_request("model_code must be a string")
    if body["kind"] not in ("STAIRLIFT", "VERTICAL_LIFT", "SCOOTER"):
        raise err_invalid_request("kind invalid")
    for f in ("supports_curved", "supports_outdoor"):
        if not isinstance(body[f], bool):
            raise err_invalid_request(f"{f} must be boolean")
    for f in ("min_stair_width_mm", "base_purchase_price_cents",
              "monthly_rental_rate_cents", "install_labor_hours"):
        v = body[f]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err_invalid_request(f"{f} must be an integer")
    pm = {
        "model_code": body["model_code"],
        "kind": body["kind"],
        "supports_curved": body["supports_curved"],
        "supports_outdoor": body["supports_outdoor"],
        "min_stair_width_mm": body["min_stair_width_mm"],
        "base_purchase_price_cents": body["base_purchase_price_cents"],
        "monthly_rental_rate_cents": body["monthly_rental_rate_cents"],
        "install_labor_hours": body["install_labor_hours"],
    }
    stamp_lean(pm)
    db.product_models[pm["id"]] = pm
    db.product_models_by_code[pm["model_code"]] = pm["id"]
    return success_object(serialize(pm), 201)


@bp.get("/stairlift-ops/product-models")
def list_product_models():
    require_role(*READ_ROLES)
    limit, offset = get_pagination()
    kind = request.args.get("kind")
    items = sorted(db.product_models.values(), key=lambda p: p["created_at"])
    if kind:
        items = [p for p in items if p["kind"] == kind]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(p) for p in page], limit, offset, total)


@bp.get("/stairlift-ops/product-models/<model_code>")
def get_product_model(model_code):
    require_role(*READ_ROLES)
    pm_id = db.product_models_by_code.get(model_code)
    if pm_id is None:
        # also allow lookup by id
        pm = db.product_models.get(model_code)
        if pm is None:
            raise err_not_found("ProductModel not found")
    else:
        pm = db.product_models[pm_id]
    return success_object(serialize(pm))
