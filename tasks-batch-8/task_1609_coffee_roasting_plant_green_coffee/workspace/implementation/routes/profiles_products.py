"""Roast profiles and products (PRD §3.7)."""

from flask import Blueprint, request

from db import DB
from errors import ERR_INVALID_REQUEST, ERR_NOT_FOUND, err
from middleware import (
    COMMON_SYS, base_fields, check_unknown_fields, get_json_body, paginate,
    pub, require_fields, require_role, sort_created, v_enum, v_int, v_num,
    v_string,
)
from response import success_list, success_object

bp = Blueprint("profiles_products", __name__)

PROFILE_ALLOWED = {
    "profile_code", "charge_temp_c", "target_drop_temp_c",
    "expected_yield_loss_pct", "shrinkage_alert_band_pct",
} | COMMON_SYS

PRODUCT_ALLOWED = {
    "sku", "display_name", "channel", "target_roast_profile_id",
    "freshness_days", "product_status",
} | COMMON_SYS

CHANNELS = {"PRIVATE_LABEL", "SUBSCRIPTION", "WHOLESALE"}
PRODUCT_READ_ROLES = ("HeadRoaster", "RoastOperator", "FulfillmentPlanner", "Trader")


@bp.post("/roastery/roast-profiles")
def create_roast_profile():
    require_role("HeadRoaster")
    body = get_json_body()
    check_unknown_fields(body, PROFILE_ALLOWED)
    require_fields(body, ["profile_code", "charge_temp_c", "target_drop_temp_c",
                          "expected_yield_loss_pct", "shrinkage_alert_band_pct"])
    code = v_string(body, "profile_code")
    charge = v_int(body, "charge_temp_c")
    drop = v_int(body, "target_drop_temp_c")
    expected = v_num(body, "expected_yield_loss_pct", ge=0, le=1)
    band = v_num(body, "shrinkage_alert_band_pct", ge=0, le=0.10)
    if not (drop > charge):
        raise err(ERR_INVALID_REQUEST, "target_drop_temp_c must be > charge_temp_c")
    p = base_fields()
    p.update({
        "profile_code": code,
        "charge_temp_c": charge,
        "target_drop_temp_c": drop,
        "expected_yield_loss_pct": expected,
        "shrinkage_alert_band_pct": band,
    })
    DB.roast_profiles[p["id"]] = p
    return success_object(pub(p), status=201)


@bp.get("/roastery/roast-profiles/<profile_id>")
def get_roast_profile(profile_id):
    require_role("HeadRoaster", "RoastOperator")
    p = DB.roast_profiles.get(profile_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Roast profile id does not exist")
    return success_object(pub(p))


@bp.post("/roastery/products")
def create_product():
    require_role("HeadRoaster")
    body = get_json_body()
    # Priority 5: body FK existence.
    profile_id = body.get("target_roast_profile_id")
    if isinstance(profile_id, str) and profile_id not in DB.roast_profiles:
        raise err(ERR_NOT_FOUND, "target_roast_profile_id does not exist")
    check_unknown_fields(body, PRODUCT_ALLOWED)
    require_fields(body, ["sku", "display_name", "channel",
                          "target_roast_profile_id", "freshness_days"])
    sku = v_string(body, "sku")
    name = v_string(body, "display_name")
    channel = v_enum(body, "channel", CHANNELS)
    pid = v_string(body, "target_roast_profile_id")
    if pid not in DB.roast_profiles:
        raise err(ERR_NOT_FOUND, "target_roast_profile_id does not exist")
    freshness = v_int(body, "freshness_days", gt=0)
    p = base_fields()
    p.update({
        "sku": sku,
        "display_name": name,
        "channel": channel,
        "target_roast_profile_id": pid,
        "freshness_days": freshness,
        "product_status": "ACTIVE",
    })
    DB.products[p["id"]] = p
    return success_object(pub(p), status=201)


@bp.get("/roastery/products/<product_id>")
def get_product(product_id):
    require_role(*PRODUCT_READ_ROLES)
    p = DB.products.get(product_id)
    if p is None:
        raise err(ERR_NOT_FOUND, "Product id does not exist")
    return success_object(pub(p))


@bp.get("/roastery/products")
def list_products():
    require_role(*PRODUCT_READ_ROLES)
    items = sort_created(DB.products.values())
    profile_id = request.args.get("target_roast_profile_id")
    channel = request.args.get("channel")
    status = request.args.get("product_status")
    if profile_id is not None:
        items = [p for p in items if p["target_roast_profile_id"] == profile_id]
    if channel is not None:
        items = [p for p in items if p["channel"] == channel]
    if status is not None:
        items = [p for p in items if p["product_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(p) for p in page], limit, offset, total)
