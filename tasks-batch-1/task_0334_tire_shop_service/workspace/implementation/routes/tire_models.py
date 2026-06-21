"""Tire-model catalog routes (PRD §3.1, §2.10)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NEGATIVE_STOCK
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_path_or_404,
    optional_int,
    require_enum,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("tire_models", __name__)

SPEED_RATINGS = {"S", "T", "H", "V", "W", "Y"}
TIRE_STATUSES = {"ACTIVE", "DISCONTINUED"}


@bp.post("/tire-models")
def create_tire_model():
    require_auth(["InventoryManager"])()
    body = get_json_body()
    require_fields(
        body,
        ["brand", "model_name", "size_token", "load_index", "speed_rating",
         "unit_price_cents", "original_tread_32nds"],
    )
    brand = require_string(body["brand"], "brand")
    model_name = require_string(body["model_name"], "model_name")
    size_token = require_string(body["size_token"], "size_token")
    load_index = require_int(body["load_index"], "load_index",
                             min_value=70, max_value=130)
    speed_rating = require_enum(body["speed_rating"], SPEED_RATINGS, "speed_rating")
    unit_price_cents = require_int(body["unit_price_cents"], "unit_price_cents",
                                   min_value=0)
    mileage_warranty_miles = optional_int(
        body.get("mileage_warranty_miles"), "mileage_warranty_miles", 0, min_value=0
    )
    original_tread_32nds = require_int(body["original_tread_32nds"],
                                       "original_tread_32nds",
                                       min_value=6, max_value=14)
    stock_qty = optional_int(body.get("stock_qty"), "stock_qty", 0, min_value=0)

    with db.mutation_lock:
        model = {
            "brand": brand,
            "model_name": model_name,
            "size_token": size_token,
            "load_index": load_index,
            "speed_rating": speed_rating,
            "unit_price_cents": unit_price_cents,
            "mileage_warranty_miles": mileage_warranty_miles,
            "original_tread_32nds": original_tread_32nds,
            "stock_qty": stock_qty,
            "status": "ACTIVE",
        }
        db.stamp_common(model)
        db.tire_models[model["id"]] = model
        return ok_object(model, 201)


@bp.get("/tire-models/<tid>")
def get_tire_model(tid: str):
    require_auth(["InventoryManager", "ServiceAdvisor", "Customer"])()
    model = lookup_path_or_404(db.tire_models, tid, "TireModel")
    return ok_object(model, 200)


@bp.get("/tire-models")
def list_tire_models():
    require_auth(["InventoryManager", "ServiceAdvisor", "Customer"])()
    limit, offset = paginate_params(request.args)
    items = list(db.tire_models.values())
    if "size_token" in request.args:
        items = [t for t in items if t["size_token"] == request.args["size_token"]]
    if "status" in request.args:
        items = [t for t in items if t["status"] == request.args["status"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/tire-models/<tid>/restock")
def restock_tire_model(tid: str):
    require_auth(["InventoryManager"])()
    model = lookup_path_or_404(db.tire_models, tid, "TireModel")
    body = get_json_body()
    require_fields(body, ["delta_qty"])
    delta_qty = require_int(body["delta_qty"], "delta_qty")
    with db.mutation_lock:
        new_qty = model["stock_qty"] + delta_qty
        if new_qty < 0:
            raise APIError(ERR_NEGATIVE_STOCK, 422,
                           "delta_qty would drive stock_qty below zero")
        model["stock_qty"] = new_qty
        db.bump(model)
        return ok_object(model, 200)


@bp.post("/tire-models/<tid>/discontinue")
def discontinue_tire_model(tid: str):
    require_auth(["InventoryManager"])()
    model = lookup_path_or_404(db.tire_models, tid, "TireModel")
    with db.mutation_lock:
        if model["status"] != "ACTIVE":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Tire model is already DISCONTINUED")
        model["status"] = "DISCONTINUED"
        db.bump(model)
        return ok_object(model, 200)
