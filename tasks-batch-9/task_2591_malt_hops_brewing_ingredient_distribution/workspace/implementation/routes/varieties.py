"""Hop varieties: registration, fetch and spot repricing."""

from flask import Blueprint

from db import db, new_entity, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import object_response
from serialize import variety_out
from util import D
from validation import body, f_bool, f_dec, f_str, must_exist

bp = Blueprint("varieties", __name__)


@bp.post("/hop-varieties")
def create_variety():
    require(("AllocationManager", "PlatformAdmin"))
    payload = body()
    variety_code = f_str(payload, "variety_code", min_len=1, max_len=20)
    name = f_str(payload, "name", min_len=1, max_len=60)
    substitution_group = f_str(payload, "substitution_group", min_len=1, max_len=40)
    alpha = f_dec(
        payload,
        "alpha_acid_target_pct",
        required=True,
        scale=2,
        minimum="0.01",
        maximum="30.00",
    )
    spot_price = f_dec(
        payload, "spot_price_cents_per_lb", required=True, scale=2, exclusive_min=0
    )
    cold_storage_required = f_bool(
        payload, "cold_storage_required", required=False, default=True
    )
    pallet_quantity = f_dec(
        payload, "pallet_quantity_lbs", required=False, scale=2, minimum=1, default=D(880)
    )
    min_order = f_dec(
        payload, "min_order_lbs", required=False, scale=2, minimum=1, default=D(44)
    )
    available_spot = f_dec(
        payload, "available_spot_lbs", required=False, scale=2, minimum=0, default=D(0)
    )

    for existing in db.varieties.values():
        if existing["variety_code"] == variety_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE_CODE", "variety_code is already registered"
            )

    variety = new_entity()
    variety.update(
        {
            "variety_code": variety_code,
            "name": name,
            "substitution_group": substitution_group,
            "alpha_acid_target_pct": alpha,
            "cold_storage_required": cold_storage_required,
            "pallet_quantity_lbs": pallet_quantity,
            "min_order_lbs": min_order,
            "spot_price_cents_per_lb": spot_price,
            "available_spot_lbs": available_spot,
        }
    )
    db.varieties[variety["id"]] = variety
    return object_response(variety_out(variety), 201)


@bp.get("/hop-varieties/<variety_id>")
def get_variety(variety_id):
    require(ALL_ROLES)
    variety = must_exist("varieties", variety_id)
    return object_response(variety_out(variety))


@bp.put("/hop-varieties/<variety_id>/spot-price")
def reprice_variety(variety_id):
    require(("AllocationManager",))
    payload = body()
    spot_price = f_dec(
        payload, "spot_price_cents_per_lb", required=True, scale=2, exclusive_min=0
    )
    available_spot = f_dec(
        payload, "available_spot_lbs", required=False, scale=2, minimum=0
    )

    variety = must_exist("varieties", variety_id)
    variety["spot_price_cents_per_lb"] = spot_price
    if available_spot is not None:
        variety["available_spot_lbs"] = available_spot
    touch(variety)
    return object_response(variety_out(variety))
