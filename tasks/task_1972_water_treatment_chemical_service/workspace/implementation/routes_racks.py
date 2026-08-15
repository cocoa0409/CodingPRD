"""CouponRack and CorrosionCoupon endpoints: rack install/archive, coupon
install with closed-interval + 7-day re-passivation buffer conflict, removal
with exposure/mpy/rating computation."""

from datetime import timedelta

from flask import Blueprint, g

import errors
from calc import coupon_corrosion, coupon_rating, REPASSIVATION_BUFFER_DAYS, SECONDS_PER_DAY
from db import db, create_entity, touch, now
from helpers import list_response, account_of_rack, account_of_coupon, query_filter
from response import success_object, success_list
from serializers import coupon_rack as ser_rack, corrosion_coupon as ser_coupon
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership, paginate)

bp = Blueprint("racks", __name__)

ALLOYS = ("MILD_STEEL", "COPPER", "ADMIRALTY", "STAINLESS_304")


@bp.route("/wt/racks", methods=["POST"])
def create_rack():
    body = get_body()
    asset = resolve_body_fk(body, "asset_id", "assets")
    vals = validate_shape(body, [
        ("asset_id", "str", True),
        ("rack_code", "str", True),
        ("position_count", "int", True),
    ])
    if not (1 <= vals["position_count"] <= 8):
        raise errors.field_constraint("position_count must be between 1 and 8 inclusive")
    for r in db["coupon_racks"].values():
        if r["asset_id"] == asset["id"] and r["rack_code"] == vals["rack_code"]:
            raise errors.field_constraint("rack_code must be unique per asset")
    ent = create_entity("coupon_racks", {
        "asset_id": asset["id"],
        "rack_code": vals["rack_code"],
        "position_count": vals["position_count"],
        "status": "INSTALLED",
    })
    return success_object(ser_rack(ent), 201)


@bp.route("/wt/racks", methods=["GET"])
def list_racks():
    user = (g.role, g.user_id)
    items = list(db["coupon_racks"].values())
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [r for r in items if r["asset_id"] == asset_id]
    return list_response(items, ser_rack, account_of_rack, user)


@bp.route("/wt/racks/<rackId>", methods=["GET"])
def get_rack(rackId):
    ent = db["coupon_racks"].get(rackId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, account_of_rack(ent))
    ent = resolve("coupon_racks", rackId)
    return success_object(ser_rack(ent), 200)


@bp.route("/wt/racks/<rackId>/archive", methods=["POST"])
def archive_rack(rackId):
    ent = resolve("coupon_racks", rackId)
    get_body()
    if ent["status"] != "INSTALLED":
        raise errors.invalid_state("Rack must be INSTALLED to archive")
    ent["status"] = "ARCHIVED"
    touch(ent)
    return success_object(ser_rack(ent), 200)


@bp.route("/wt/racks/<rackId>/coupons", methods=["POST"])
def install_coupon(rackId):
    rack = resolve("coupon_racks", rackId)
    body = get_body()
    vals = validate_shape(body, [
        ("position_index", "int", True),
        ("alloy", "str", True, ALLOYS),
        ("density_g_cm3", "num", True),
        ("area_in2", "num", True),
        ("pre_weight_g", "num", True),
        ("installed_at", "iso", True),
    ])
    # Tier 10 field constraints.
    if vals["position_index"] < 1 or vals["position_index"] > rack["position_count"]:
        raise errors.field_constraint("position_index must not exceed the rack's position_count")
    if vals["density_g_cm3"] <= 0:
        raise errors.field_constraint("density_g_cm3 must be > 0")
    if vals["area_in2"] <= 0:
        raise errors.field_constraint("area_in2 must be > 0")
    if vals["pre_weight_g"] <= 0:
        raise errors.field_constraint("pre_weight_g must be > 0")
    # Tier 12: closed-interval + 7-day re-passivation buffer on same position.
    # An INSTALLED coupon's interval is open-ended; adjacency is NOT allowed.
    buffer = timedelta(days=REPASSIVATION_BUFFER_DAYS)
    for c in db["corrosion_coupons"].values():
        if c["rack_id"] != rack["id"] or c["position_index"] != vals["position_index"]:
            continue
        if c["status"] == "INSTALLED":
            raise errors.ApiError(errors.ERR_COUPON_INTERVAL_CONFLICT, 409,
                                  "Position already hosts an INSTALLED coupon")
        if vals["installed_at"] < c["removed_at"] + buffer:
            raise errors.ApiError(errors.ERR_COUPON_INTERVAL_CONFLICT, 409,
                                  "Install must be at or after prior removal plus the 7-day buffer")
    # Tier 13: rack must be INSTALLED (not ARCHIVED).
    if rack["status"] == "ARCHIVED":
        raise errors.ApiError(errors.ERR_RACK_ARCHIVED, 409,
                              "Coupons may only be installed on an INSTALLED rack")
    ent = create_entity("corrosion_coupons", {
        "rack_id": rack["id"],
        "position_index": vals["position_index"],
        "alloy": vals["alloy"],
        "density_g_cm3": vals["density_g_cm3"],
        "area_in2": vals["area_in2"],
        "pre_weight_g": vals["pre_weight_g"],
        "installed_at": vals["installed_at"],
        "removed_at": None,
        "post_weight_g": None,
        "exposure_days": None,
        "corrosion_rate_mpy": None,
        "rating": None,
        "status": "INSTALLED",
    })
    return success_object(ser_coupon(ent), 201)


@bp.route("/wt/racks/<rackId>/coupons", methods=["GET"])
def list_coupons(rackId):
    rack = db["coupon_racks"].get(rackId)
    if rack is not None:
        check_cc_ownership(g.user_id, g.role, account_of_rack(rack))
    rack = resolve("coupon_racks", rackId)
    items = [c for c in db["corrosion_coupons"].values() if c["rack_id"] == rack["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([ser_coupon(c) for c in page], limit, offset, total)


@bp.route("/wt/coupons/<couponId>/remove", methods=["POST"])
def remove_coupon(couponId):
    ent = resolve("corrosion_coupons", couponId)
    body = get_body()
    vals = validate_shape(body, [("post_weight_g", "num", True)])
    # Tier 6
    if ent["status"] != "INSTALLED":
        raise errors.invalid_state("Coupon must be INSTALLED to remove")
    # Field constraints / weight-gain guard.
    if vals["post_weight_g"] <= 0:
        raise errors.field_constraint("post_weight_g must be > 0")
    if vals["post_weight_g"] > ent["pre_weight_g"] + 2.0:
        raise errors.ApiError(errors.ERR_COUPON_WEIGHT_GAIN, 422,
                              "post_weight_g exceeds pre_weight_g plus the 2.0 g deposit allowance")
    # Tier 11 temporal: exposure at least one full day.
    removed_at = now()
    exposure_days = int((removed_at - ent["installed_at"]).total_seconds() // SECONDS_PER_DAY)
    if exposure_days < 1:
        raise errors.ApiError(errors.ERR_EXPOSURE_TOO_SHORT, 422,
                              "Coupon exposure must be at least one full day")
    ent["removed_at"] = removed_at
    ent["post_weight_g"] = vals["post_weight_g"]
    ent["exposure_days"] = exposure_days
    ent["corrosion_rate_mpy"] = coupon_corrosion(
        ent["pre_weight_g"], vals["post_weight_g"], ent["density_g_cm3"],
        ent["area_in2"], exposure_days)
    ent["rating"] = coupon_rating(exposure_days)
    ent["status"] = "REMOVED"
    touch(ent)
    return success_object(ser_coupon(ent), 200)
