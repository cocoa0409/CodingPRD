"""Variety endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_VARIETY_IN_USE,
    ERR_VARIETY_NOT_FOUND,
)
from middleware import get_body, req_int, req_str, require_roles
from response import success, serialize
from services import new_resource, touch
from routes.listing import list_response

bp = Blueprint("varieties", __name__)

ALL = ("Grower", "Chef", "OpsManager")
CATEGORIES = ("MICROGREEN", "PETITE_GREEN", "EDIBLE_FLOWER", "SPECIALTY_HERB")


@bp.post("/varieties")
@require_roles("Grower")
def create_variety():
    body = get_body()
    category = req_str(body, "crop_category")
    if category not in CATEGORIES:
        raise ApiError(400, ERR_INVALID_REQUEST, "crop_category is not a valid value.")
    days_to_harvest = req_int(body, "days_to_harvest")
    yield_per_tray = req_int(body, "expected_yield_grams_per_tray")
    listed_price = req_int(body, "listed_price_cents_per_kg")
    min_order_grams = req_int(body, "min_order_grams")
    if days_to_harvest <= 0 or yield_per_tray <= 0 or listed_price < 0 or min_order_grams < 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "Numeric field out of range.")
    rec = new_resource(
        {
            "name": req_str(body, "name"),
            "crop_category": category,
            "days_to_harvest": days_to_harvest,
            "expected_yield_grams_per_tray": yield_per_tray,
            "listed_price_cents_per_kg": listed_price,
            "stage": "TRIAL",
            "min_order_grams": min_order_grams,
        }
    )
    db.varieties[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/varieties")
@require_roles(*ALL)
def list_varieties():
    stage = request.args.get("stage")
    records = list(db.varieties.values())
    if stage is not None:
        records = [r for r in records if r["stage"] == stage]
    return list_response(records)


@bp.get("/varieties/<vid>")
@require_roles(*ALL)
def get_variety(vid):
    rec = db.varieties.get(vid)
    if rec is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    return success(serialize(rec), "object", 200)


@bp.post("/varieties/<vid>/retire")
@require_roles("Grower")
def retire_variety(vid):
    rec = db.varieties.get(vid)
    if rec is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if rec["stage"] != "LISTED":
        raise ApiError(409, ERR_INVALID_STATE, "Only a LISTED variety can be retired.")
    in_use = any(
        li["variety_id"] == vid and li["fulfillment"] in ("PLANNED", "ALLOCATED")
        for li in db.order_items.values()
    )
    if in_use:
        raise ApiError(
            409, ERR_VARIETY_IN_USE, "Open order lines reference this variety."
        )
    rec["stage"] = "RETIRED"
    touch(rec)
    return success(serialize(rec), "object", 200)
