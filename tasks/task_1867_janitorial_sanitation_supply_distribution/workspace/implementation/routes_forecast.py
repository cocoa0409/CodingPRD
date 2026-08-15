"""Forecast profile endpoints."""
from flask import Blueprint, request

import db
import services as svc
from errors import ApiError, ERR_STALE_VERSION, ERR_VALIDATION, not_found
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list
from routes_facilities import get_facility_or_404
from routes_products import get_product_or_404

bp = Blueprint("forecast_profiles", __name__)

READ_ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep")
VARIANTS = ("PROVISIONAL", "FINAL")


def view(p):
    return dict(p)


@bp.post("/jansan/forecast-profiles")
def create_profile():
    require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    product_id = svc.as_str(svc.require_field(body, "product_id"), "product_id")
    get_facility_or_404(facility_id)
    get_product_or_404(product_id)
    horizon = body.get("horizon_days", 30)
    horizon = svc.as_int(horizon, "horizon_days", minimum=1)
    safety = body.get("safety_stock", 0)
    safety = svc.as_int(safety, "safety_stock", minimum=0)
    on_hand = body.get("current_on_hand", 0)
    on_hand = svc.as_int(on_hand, "current_on_hand", minimum=0)
    # uniqueness per (facility_id, product_id)
    for p in db.forecast_profiles.values():
        if p["facility_id"] == facility_id and p["product_id"] == product_id:
            raise ApiError(ERR_VALIDATION, "Forecast profile already exists for this facility+product", 400)

    p = svc.base_resource()
    p.update({
        "facility_id": facility_id,
        "product_id": product_id,
        "horizon_days": horizon,
        "safety_stock": safety,
        "current_on_hand": on_hand,
        "avg_daily_usage": 0.0,
        "reorder_point": safety,
        "recommended_qty": 0,
        "replenishment_recommended": on_hand <= safety,
        "variant_used": None,
        "last_computed_at": None,
    })
    db.forecast_profiles[p["id"]] = p
    return success_object(view(p), 201)


def get_profile_or_404(profile_id):
    p = db.forecast_profiles.get(profile_id)
    if p is None:
        raise not_found("Forecast profile not found")
    return p


@bp.get("/jansan/forecast-profiles/<forecast_profile_id>")
def get_profile(forecast_profile_id):
    user_id, role = require_roles(*READ_ROLES)
    p = get_profile_or_404(forecast_profile_id)
    check_facility_ownership(user_id, role, p["facility_id"])
    return success_object(view(p))


@bp.get("/jansan/forecast-profiles")
def list_profiles():
    user_id, role = require_roles(*READ_ROLES)
    facility_id = request.args.get("facility_id")
    product_id = request.args.get("product_id")
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    items = list(db.forecast_profiles.values())
    if role == "FacilityManager":
        items = [p for p in items if p["facility_id"] == user_id]
    if facility_id:
        items = [p for p in items if p["facility_id"] == facility_id]
    if product_id:
        items = [p for p in items if p["product_id"] == product_id]
    import clock
    items.sort(key=lambda p: clock.parse_iso(p["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([view(p) for p in page], limit, offset, total)


@bp.patch("/jansan/forecast-profiles/<forecast_profile_id>")
def patch_profile(forecast_profile_id):
    require_roles("DistributorAdmin")
    p = get_profile_or_404(forecast_profile_id)
    body = request.get_json(silent=True) or {}
    # request shape first (priority 5): required OCC field present and int
    expected = svc.as_int(svc.require_field(body, "expected_forecast_profile_version"),
                          "expected_forecast_profile_version")
    if "safety_stock" in body and body["safety_stock"] is not None:
        svc.as_int(body["safety_stock"], "safety_stock", minimum=0)
    if "horizon_days" in body and body["horizon_days"] is not None:
        svc.as_int(body["horizon_days"], "horizon_days", minimum=1)
    if "current_on_hand" in body and body["current_on_hand"] is not None:
        svc.as_int(body["current_on_hand"], "current_on_hand", minimum=0)
    # OCC (priority 6)
    if expected != p["version"]:
        raise ApiError(ERR_STALE_VERSION, "Stale forecast profile version", 412)
    if body.get("safety_stock") is not None:
        p["safety_stock"] = body["safety_stock"]
    if body.get("horizon_days") is not None:
        p["horizon_days"] = body["horizon_days"]
    if body.get("current_on_hand") is not None:
        p["current_on_hand"] = body["current_on_hand"]
    svc.touch(p)
    return success_object(view(p))


@bp.post("/jansan/forecast-profiles/<forecast_profile_id>/recompute")
def recompute_profile(forecast_profile_id):
    user_id, role = require_roles("DistributorAdmin", "FacilityManager")
    p = get_profile_or_404(forecast_profile_id)
    check_facility_ownership(user_id, role, p["facility_id"])
    body = request.get_json(silent=True) or {}
    variant = svc.as_enum(svc.require_field(body, "variant"), "variant", VARIANTS)
    svc.recompute_forecast(p, variant)
    return success_object(view(p))
